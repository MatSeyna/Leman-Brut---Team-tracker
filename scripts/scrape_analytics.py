#!/usr/bin/env python3
"""Large-sample force-disposition matchups from the "State of the game" report
(https://40k-analytics.github.io/stateofthegame/). One request per run.

It reads the page's pairing tables:
  - "Force Disposition against Force Disposition": the whole season so far
  - the first pairing table of each milestone section: the 28 days after that
    milestone (cut off where the data ends)

Output: data/analytics.json (and a gzip copy per day in data/history/).
If the page changes shape the script exits with an error and leaves the previous
file untouched. It never touches the MiniHeadQuarters snapshot.
"""
import gzip
import json
import pathlib
import re
import sys
import urllib.robotparser
from datetime import date, datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

HOST = "https://40k-analytics.github.io"
URL = HOST + "/stateofthegame/"
UA = "LemanBrutTeamTracker/1.0 (private team tool; one run per day)"
ORDER = ["Take and Hold", "Priority Assets", "Purge the Foe", "Reconnaissance", "Disruption"]
HEAD = ["pairing", "games", "first choice wins", "draws", "second choice wins"]
SEASON_HEADING = "Force Disposition against Force Disposition"
FR_MONTH = ["", "janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def txt(el):
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""


def num(s):
    m = re.search(r"\d[\d,]*", s or "")
    return int(m.group(0).replace(",", "")) if m else None


def pct(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", s or "")
    return float(m.group(1)) if m else None


def parse_day_month(s, year):
    """'17 October' -> date(year, 10, 17)."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)", s or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {year}", "%d %B %Y").date()
    except ValueError:
        return None


def fr(d):
    return f"{d.day} {FR_MONTH[d.month]}"


def parse_pairing_table(table):
    """Return (pairs, mirrors) if this is a complete disposition pairing table, else None."""
    rows = []
    for tr in table.find_all("tr"):
        cells = [txt(c) for c in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    if not rows or [c.lower() for c in rows[0][:5]] != HEAD:
        return None
    pairs, mirrors = [], []
    for r in rows[1:]:
        if len(r) < 5:
            return None
        m = re.match(r"^(.+?) against (.+)$", r[0])
        mm = re.match(r"^(.+), both sides$", r[0])
        if m and m.group(1) in ORDER and m.group(2) in ORDER:
            pairs.append({"a": m.group(1), "b": m.group(2), "games": num(r[1]),
                          "a_win": pct(r[2]), "draw": pct(r[3]), "b_win": pct(r[4])})
        elif mm and mm.group(1) in ORDER:
            mirrors.append({"a": mm.group(1), "games": num(r[1]), "draw": pct(r[3])})
        else:
            return None
    if len(pairs) != 10 or len(mirrors) != 5:
        return None
    return pairs, mirrors


def main():
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = requests.get(HOST + "/robots.txt", headers={"User-Agent": UA}, timeout=30)
        rp.parse(r.text.splitlines() if r.status_code == 200 else [])
    except requests.RequestException:
        rp.parse([])
    if not rp.can_fetch(UA, URL):
        raise RuntimeError("robots.txt disallows the report page")

    resp = requests.get(URL, headers={"User-Agent": UA}, timeout=120)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    now = datetime.now(timezone.utc)
    year = now.year

    meta = soup.find("meta", attrs={"name": "description"})
    desc = meta.get("content", "") if meta else ""
    rng = re.search(r"from\s+(\d{1,2}\s+[A-Za-z]+)\s+to\s+(\d{1,2}\s+[A-Za-z]+)", desc)
    if not rng:
        raise RuntimeError("could not read the data range from the page description")
    start, end = parse_day_month(rng.group(1), year), parse_day_month(rng.group(2), year)
    if not start or not end:
        raise RuntimeError("could not parse the data range dates")
    tm = re.search(r"([\d,]{5,})\s+matches\s+from\s+([\d,]+)\s+events", txt(soup))

    season = None
    milestones = []
    seen = set()
    heading = ""
    for el in soup.find_all(["h2", "h3", "table"]):
        if el.name in ("h2", "h3"):
            heading = txt(el)
            continue
        parsed = parse_pairing_table(el)
        if not parsed:
            continue
        if heading == SEASON_HEADING and season is None:
            season = parsed
        elif heading not in seen:
            m = re.match(r"^(.*)\((\d{1,2}\s+[A-Za-z]+)\)\s*$", heading)
            d = parse_day_month(m.group(2), year) if m else None
            if d:
                seen.add(heading)
                milestones.append((m.group(1).strip(), d, parsed))
    if season is None:
        raise RuntimeError("season-wide disposition table not found — page layout changed?")
    if not milestones:
        raise RuntimeError("no milestone disposition tables found — page layout changed?")

    def view(key, label, since, until, parsed, **extra):
        pairs, mirrors = parsed
        total = sum(p["games"] or 0 for p in pairs) + sum(m["games"] or 0 for m in mirrors)
        return {"key": key, "label": label, "since": since.isoformat(), "until": until.isoformat(),
                "days": (until - since).days + 1, "games_total": total, "pairs": pairs, "mirrors": mirrors, **extra}

    views = [view("season", f"Saison complète ({fr(start)} → {fr(end)})", start, end, season)]
    for title, d, parsed in sorted(milestones, key=lambda x: x[1], reverse=True):
        until = min(d + timedelta(days=27), end)
        partial = d + timedelta(days=27) > end
        n = (until - d).days + 1
        label = (f"Depuis le {fr(d)} · {title} ({n} jours)" if partial
                 else f"28 jours après le {fr(d)} · {title}")
        views.append(view(f"m{d.isoformat()}", label, d, until, parsed, partial=partial, milestone=title))

    out = {
        "fetched_at": now.isoformat(timespec="seconds"),
        "source": "40k-analytics — State of the game",
        "source_url": URL,
        "total_matches": tm.group(0) if tm else None,
        "data_start": start.isoformat(),
        "data_end": end.isoformat(),
        "data_end_label": fr(end),
        "disposition": {"order": ORDER, "views": views},
    }
    DATA.mkdir(exist_ok=True)
    (DATA / "history").mkdir(exist_ok=True)
    blob = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    (DATA / "analytics.json").write_text(blob, encoding="utf-8")
    with gzip.open(DATA / "history" / f"analytics-{now.strftime('%Y-%m-%d')}.json.gz", "wt", encoding="utf-8") as fh:
        fh.write(blob)
    print(f"OK: data {start} → {end}; views: {[v['key'] for v in views]}; season games {views[0]['games_total']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
