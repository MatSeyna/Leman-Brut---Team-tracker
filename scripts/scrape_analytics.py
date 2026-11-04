#!/usr/bin/env python3
"""Second source for force-disposition matchups: the "State of the game" report
(40k-analytics.github.io). One request per run. It never touches the main snapshot.

Output (under data/):
  analytics.json                 disposition tables found on the page, with their headings
  debug/analytics_probe.json     what the page contains (headings, scripts, data files)
  debug/analytics_tables.html    raw HTML of the disposition tables, to check the parser
"""
import json
import pathlib
import re
import sys
import urllib.robotparser
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

HOST = "https://40k-analytics.github.io"
URL = HOST + "/stateofthegame/"
UA = "LemanBrutTeamTracker/1.0 (private team tool; one run per day)"
DISPOSITIONS = ["take and hold", "priority assets", "purge the foe", "reconnaissance", "disruption"]

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def txt(el):
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""


def disp_hits(s):
    s = s.lower()
    return sum(1 for d in DISPOSITIONS if d in s)


def table_rows(table):
    out = []
    for tr in table.find_all("tr"):
        cells = [txt(c) for c in tr.find_all(["th", "td"])]
        if cells:
            out.append(cells)
    return out


def main():
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = requests.get(HOST + "/robots.txt", headers={"User-Agent": UA}, timeout=30)
        rp.parse(r.text.splitlines() if r.status_code == 200 else [])
    except requests.RequestException:
        rp.parse([])
    if not rp.can_fetch(UA, URL):
        raise RuntimeError("robots.txt disallows the report page")

    resp = requests.get(URL, headers={"User-Agent": UA}, timeout=60)
    resp.raise_for_status()
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")
    now = datetime.now(timezone.utc)

    tables = soup.find_all("table")
    found = []
    for i, t in enumerate(tables):
        rows = table_rows(t)
        flat = " ".join(" ".join(r) for r in rows[:8])
        if disp_hits(flat) >= 3:
            h = t.find_previous(["h1", "h2", "h3", "h4"])
            # nearest paragraph / caption text before the table, for the window description
            prev = t.find_previous(["p", "caption", "summary"])
            found.append({
                "index": i,
                "heading": txt(h),
                "context": txt(prev)[:300],
                "rows": rows,
                "html": str(t),
            })

    text = txt(soup)
    m_total = re.search(r"([\d,]{5,})\s+matches\s+from\s+([\d,]+)\s+events", text)
    m_upd = re.search(r"last updated[:\s]+([A-Za-z0-9 ,]+?\d{4})", text, re.I)

    probe = {
        "fetched_at": now.isoformat(timespec="seconds"),
        "bytes": len(html),
        "title": txt(soup.title),
        "n_tables": len(tables),
        "n_disposition_tables": len(found),
        "scripts": [s.get("src") for s in soup.find_all("script") if s.get("src")][:30],
        "data_urls": sorted(set(re.findall(r"""["'(]([^"'()\s]+\.(?:json|csv)(?:\?[^"'()\s]*)?)""", html)))[:40],
        "headings": [f"{h.name}: {txt(h)}" for h in soup.find_all(["h1", "h2", "h3", "h4"])][:120],
        "total_matches": m_total.group(0) if m_total else None,
        "last_updated": m_upd.group(1) if m_upd else None,
        "disposition_tables": [{k: v for k, v in f.items() if k != "html"} for f in found],
        "first_html_chars": html[:600],
    }
    (DATA / "debug").mkdir(parents=True, exist_ok=True)
    (DATA / "debug" / "analytics_probe.json").write_text(json.dumps(probe, ensure_ascii=False, indent=1))
    (DATA / "debug" / "analytics_tables.html").write_text("\n\n".join(f["html"] for f in found)[:120000])

    result = {
        "fetched_at": probe["fetched_at"],
        "source": "40k-analytics State of the game",
        "source_url": URL,
        "total_matches": probe["total_matches"],
        "last_updated": probe["last_updated"],
        "tables": [{k: v for k, v in f.items() if k != "html"} for f in found],
    }
    (DATA / "analytics.json").write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    print(f"tables on page: {len(tables)}; disposition tables: {len(found)}; data files: {probe['data_urls'][:5]}")
    if not found:
        print("WARNING: no disposition table found in the static HTML (page may build its tables with JavaScript)", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
