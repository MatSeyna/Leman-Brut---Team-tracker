#!/usr/bin/env python3
"""Temporary: save the raw MiniHeadQuarters pages so the parser can be fixed."""
import pathlib, sys, time
import requests
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from scrape import STATS, FACTION, UA

out = pathlib.Path("debug_html"); out.mkdir(exist_ok=True)
s = requests.Session(); s.headers.update({"User-Agent": UA, "Accept-Language": "en"})
pages = {
    "stats_base": (STATS, None),
    "stats_week": (STATS, {"buckets": "1"}),
    "stats_month": (STATS, {"buckets": "4"}),
}
for name, (url, params) in pages.items():
    r = s.get(url, params=params, timeout=40)
    (out / f"{name}.html").write_text(r.text)
    print(name, r.status_code, len(r.text), r.headers.get("content-type"))
    time.sleep(1.5)

from bs4 import BeautifulSoup
import re
for name in pages:
    soup = BeautifulSoup((out / f"{name}.html").read_text(), "html.parser")
    print(f"===== {name}: {len(soup.find_all('table'))} tables")
    for t in soup.find_all("table"):
        first = t.find("tr")
        print("  TABLE head:", [c.get_text(" ", strip=True) for c in first.find_all(["th","td"])] if first else None,
              "rows:", len(t.find_all("tr")))
    main = soup.find("main") or soup.body
    text = re.sub(r"\s+", " ", main.get_text(" ", strip=True))
    print("  TEXT:", text[:3000])
