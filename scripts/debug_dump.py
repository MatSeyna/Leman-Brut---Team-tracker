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
