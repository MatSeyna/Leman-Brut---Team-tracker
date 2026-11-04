#!/usr/bin/env python3
"""Daily snapshot of the MiniHeadQuarters Warhammer 40K meta stats.

For each time window (last week, last 4 weeks, last 12 weeks) it saves:
  - the faction win-rate table
  - the force-disposition matrix (and overall disposition win rates)
  - the matchup table of every faction

Output (all under data/):
  latest.json          full snapshot of the newest successful run (read by the app)
  trend.json           compact win-rate history per faction and window (read by the app)
  history/DATE.json.gz full snapshot of each day
  update_log.json      one line per run, says whether the numbers changed

If anything essential fails the script exits with an error and leaves the
previous data untouched.
"""
import gzip
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.robotparser
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://miniheadquarters.com"
STATS = BASE + "/meta/solo/warhammer-40000/stats/"
FACTION = BASE + "/meta/solo/warhammer-40000/factions/{id}/"
UA = "LemanBrutTeamTracker/1.0 (private team tool; one run per day)"

# our key -> label used by the site's time-window selector
WINDOWS = {
    "week": "Last week",
    "month": "Last 4 weeks",
    "quarter": "Last 12 weeks",
}
DISPOSITIONS = ["take and hold", "priority assets", "purge the foe", "reconnaissance", "disruption"]
DELAY = float(os.environ.get("SCRAPE_DELAY", "1.2"))

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Language": "en"})
_robots = None


# ---------------------------------------------------------------- fetching
def allowed(url):
    global _robots
    if _robots is None:
        _robots = urllib.robotparser.RobotFileParser()
        try:
            r = _session.get(BASE + "/robots.txt", timeout=30)
            _robots.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            _robots.parse([])
    return _robots.can_fetch(UA, url)


def get(url, params=None):
    if not allowed(url):
        raise RuntimeError(f"robots.txt disallows {url}")
    last = None
    for attempt in range(3):
        time.sleep(DELAY)
        try:
            r = _session.get(url, params=params, timeout=40)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"GET {url} {params or ''} failed: {last}")


# ---------------------------------------------------------------- parsing helpers
def txt(el):
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""


def num(s, default=None):
    m = re.search(r"-?\d[\d,]*\.?\d*", s or "")
    if not m:
        return default
    v = m.group(0).replace(",", "")
    return float(v) if "." in v else int(v)


def pct_list(s):
    return [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", s or "")]


def rows_of(table):
    out = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if cells:
            out.append((cells, all(c.name == "th" for c in cells)))
    return out


def header_texts(table):
    for cells, is_head in rows_of(table):
        if is_head:
            return [txt(c).lower() for c in cells]
    return []


def faction_id(cell):
    a = cell.find("a", href=True)
    if a:
        m = re.search(r"/factions/(\d+)", a["href"])
        if m:
            return int(m.group(1)), txt(a)
    return None, txt(cell)


# ---------------------------------------------------------------- window selector discovery
def discover_window_param(soup):
    """Find the query parameter that selects the time window."""
    override = os.environ.get("WINDOW_PARAM")
    if override:
        values = json.loads(os.environ["WINDOW_VALUES"])  # {"Last week": "1", ...}
        return override, values

    labels = list(WINDOWS.values())
    # 1) a <select> whose options include the window labels
    for sel in soup.find_all("select"):
        opts = {txt(o): o.get("value", txt(o)) for o in sel.find_all("option")}
        if all(l in opts for l in labels) and sel.get("name"):
            return sel["name"], opts
    # 2) radio inputs with labels
    radios = {}
    name = None
    for inp in soup.find_all("input", attrs={"type": "radio"}):
        lab = None
        if inp.get("id"):
            lab = soup.find("label", attrs={"for": inp["id"]})
        if lab is None:
            lab = inp.find_parent("label")
        if lab and txt(lab) in labels:
            radios[txt(lab)] = inp.get("value", "")
            name = inp.get("name")
    if name and all(l in radios for l in labels):
        return name, radios
    # 3) plain links carrying a query string
    links = {}
    keys = set()
    for a in soup.find_all("a", href=True):
        if txt(a) in labels and "?" in a["href"]:
            q = dict(parse_qsl(urlparse(a["href"]).query))
            if len(q) >= 1:
                links[txt(a)] = q
                keys.update(q)
    if all(l in links for l in labels):
        # the parameter that differs between the links
        for k in keys:
            vals = {links[l].get(k) for l in labels}
            if len(vals) == len(labels):
                return k, {l: links[l][k] for l in labels}
    found = [
        f"select[{s.get('name')}]: {[txt(o) for o in s.find_all('option')][:10]}"
        for s in soup.find_all("select")
    ]
    raise RuntimeError(
        "Could not find the time-window control on the stats page. "
        "Controls seen: " + "; ".join(found)
        + ". Set WINDOW_PARAM and WINDOW_VALUES (JSON) as environment variables to override."
    )


# ---------------------------------------------------------------- table parsers
def parse_factions(soup):
    for table in soup.find_all("table"):
        head = header_texts(table)
        if any(h.startswith("faction") for h in head) and any("games" in h for h in head):
            out = []
            for cells, is_head in rows_of(table):
                if is_head or len(cells) < 3:
                    continue
                fid, name = faction_id(cells[0])
                win = txt(cells[1])
                p = pct_list(win)
                ci = re.search(r"\((\d+(?:\.\d+)?)\s*[–-]\s*(\d+(?:\.\d+)?)\)", win)
                games_txt = txt(cells[2])
                share = pct_list(games_txt)
                out.append({
                    "id": fid,
                    "name": name,
                    "win_rate": p[0] if p else None,
                    "ci_low": float(ci.group(1)) if ci else None,
                    "ci_high": float(ci.group(2)) if ci else None,
                    "games": num(games_txt, 0),
                    "share": share[0] if share else None,
                    "x0": num(txt(cells[3])) if len(cells) > 3 else None,
                    "x1": num(txt(cells[4])) if len(cells) > 4 else None,
                })
            if out:
                return out
    return []


def parse_matchups(soup):
    for table in soup.find_all("table"):
        head = header_texts(table)
        if head and head[0].startswith("opponent"):
            out = []
            for cells, is_head in rows_of(table):
                if is_head or len(cells) < 3:
                    continue
                oid, name = faction_id(cells[0])
                name = re.sub(r"\s*i?\s*Small sample\s*$", "", name).strip()
                rng = re.search(r"(\d+(?:\.\d+)?)\s*%\s*[–-]\s*(\d+(?:\.\d+)?)\s*%", txt(cells[3])) if len(cells) > 3 else None
                p = pct_list(txt(cells[2]))
                out.append({
                    "id": oid,
                    "name": name,
                    "games": num(txt(cells[1]), 0),
                    "win_rate": p[0] if p else None,
                    "low": float(rng.group(1)) if rng else None,
                    "high": float(rng.group(2)) if rng else None,
                })
            return out
    return []


def canon_disp(s):
    """'vs Take and hold' / 'Take and hold' -> 'take and hold'; anything else -> None."""
    s = re.sub(r"^\s*vs\.?\s+", "", (s or "").strip().lower())
    return s if s in DISPOSITIONS else None


def parse_stat_cell(raw):
    """'54.6% (46.4 – 62.6) 141 games' -> win rate, interval, games. '-' -> all None."""
    p = pct_list(raw)
    ci = re.search(r"\((\d+(?:\.\d+)?)\s*[–-]\s*(\d+(?:\.\d+)?)\)", raw or "")
    g = re.search(r"(\d[\d,]*)\s*games?", raw or "")
    return {
        "raw": raw,
        "win_rate": p[0] if p else None,
        "low": float(ci.group(1)) if ci else None,
        "high": float(ci.group(2)) if ci else None,
        "games": int(g.group(1).replace(",", "")) if g else None,
    }


def parse_dispositions(soup):
    """Return (matrix, overall). The site's grid has a 'Global win rate' column
    and one 'vs <disposition>' column per disposition."""
    for table in soup.find_all("table"):
        all_rows = rows_of(table)
        if not all_rows:
            continue
        head_cells = next((c for c, h in all_rows if h), all_rows[0][0])
        heads = [txt(c) for c in head_cells]
        cols = [(i, canon_disp(h)) for i, h in enumerate(heads) if canon_disp(h)]
        if len(cols) < 3:
            continue
        gi = next((i for i, h in enumerate(heads) if "global" in h.lower()), None)
        rows, overall = [], []
        for cells, _ in all_rows:
            if cells is head_cells:
                continue
            name = canon_disp(txt(cells[0]))
            if not name:
                continue
            label = name.capitalize()
            data = [parse_stat_cell(txt(cells[i]) if i < len(cells) else "") for i, _ in cols]
            row = {"name": label, "cells": data}
            if gi is not None and gi < len(cells):
                g = parse_stat_cell(txt(cells[gi]))
                row["global"] = g
                overall.append({"name": label, "games": g["games"] or 0, "win_rate": g["win_rate"]})
            rows.append(row)
        if rows:
            return {"labels": [n.capitalize() for _, n in cols], "rows": rows}, (overall or None)
    return None, None


# ---------------------------------------------------------------- main
def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def content_hash(windows):
    return hashlib.sha256(json.dumps(windows, sort_keys=True).encode()).hexdigest()


def main():
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    previous = load_json(DATA / "latest.json", None)
    prev_windows = (previous or {}).get("windows", {})

    base = get(STATS)
    param, values = discover_window_param(base)
    print(f"Window parameter: {param} -> {values}")

    windows = {}
    stale = []
    for key, label in WINDOWS.items():
        value = values[label]
        soup = get(STATS, {param: value})
        factions = parse_factions(soup)
        if len(factions) < 15:
            raise RuntimeError(f"[{key}] only {len(factions)} factions parsed — page layout changed?")
        matrix, overall = parse_dispositions(soup)
        matchups = {}
        for f in factions:
            if f["id"] is None:
                continue
            try:
                rows = parse_matchups(get(FACTION.format(id=f["id"]), {param: value}))
                if not rows and f["games"]:
                    raise RuntimeError("no matchup table")
                matchups[str(f["id"])] = rows
            except RuntimeError as e:
                old = prev_windows.get(key, {}).get("matchups", {}).get(str(f["id"]))
                print(f"[{key}] {f['name']}: {e}; keeping previous data", file=sys.stderr)
                if old is not None:
                    matchups[str(f["id"])] = old
                stale.append(f"{key}:{f['id']}")
        windows[key] = {
            "label": label,
            "factions": factions,
            "dispositions": matrix,
            "dispositions_overall": overall,
            "matchups": matchups,
        }
        print(f"[{key}] {len(factions)} factions, {len(matchups)} matchup tables")

    changed = content_hash(windows) != content_hash(prev_windows) if previous else True
    snapshot = {
        "date": today,
        "fetched_at": now.isoformat(timespec="seconds"),
        "source": "MiniHeadQuarters",
        "source_url": STATS,
        "changed_since_previous": changed,
        "stale": stale,
        "windows": windows,
    }

    (DATA / "history").mkdir(parents=True, exist_ok=True)
    with gzip.open(DATA / "history" / f"{today}.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(snapshot, fh, separators=(",", ":"))
    (DATA / "latest.json").write_text(json.dumps(snapshot, separators=(",", ":")))

    trend = load_json(DATA / "trend.json", {})
    for key, w in windows.items():
        t = trend.setdefault(key, {})
        for f in w["factions"]:
            if f["id"] is None or f["win_rate"] is None:
                continue
            entry = t.setdefault(str(f["id"]), {"name": f["name"], "points": []})
            entry["name"] = f["name"]
            if not entry["points"] or entry["points"][-1][0] != today:
                entry["points"].append([today, f["win_rate"], f["games"]])
            else:
                entry["points"][-1] = [today, f["win_rate"], f["games"]]
    (DATA / "trend.json").write_text(json.dumps(trend, separators=(",", ":")))

    log = load_json(DATA / "update_log.json", [])
    log = [e for e in log if e.get("date") != today] + [{"date": today, "changed": changed, "stale": len(stale)}]
    (DATA / "update_log.json").write_text(json.dumps(log[-400:], separators=(",", ":")))
    print("Done. changed =", changed)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # leave previous data untouched
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
