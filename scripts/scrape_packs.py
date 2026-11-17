#!/usr/bin/env python3
"""Current Warhammer 40,000 Faction Pack PDFs on the Warhammer Community downloads page.

Writes data/factionpacks.json:
  {"fetched_at", "source", "packs": {key: {"name", "url", "file", "date", "lang"}}}
key is the faction slug used by the app (see FACTIONS below); a pack whose faction is not
in that list is still kept under its own slug, so a new faction shows up without a code change.

The PDF links change at every update (the file name carries a random suffix), so the app
cannot hard-code them: this script finds the newest ones twice a day. If nothing is found
(site down, layout changed), the previous file is kept and the app falls back to opening
the downloads page. A few requests per run, robots.txt respected, polite User-Agent.
"""
import html
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from scrape_news import UA, WC, ASSETS, allowed  # noqa: E402  (same politeness rules as the news)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "factionpacks.json"
PAGE = WC + "/en-gb/downloads/warhammer-40000/"
API = WC + "/api/search/downloads/"

# app key -> (display name, slugs found in the PDF file names, underscores removed)
FACTIONS = {
    "space_marines": ("Space Marines", ["spacemarines", "adeptusastartes"]),
    "black_templars": ("Black Templars", ["blacktemplars"]),
    "blood_angels": ("Blood Angels", ["bloodangels"]),
    "dark_angels": ("Dark Angels", ["darkangels"]),
    "space_wolves": ("Space Wolves", ["spacewolves"]),
    "deathwatch": ("Deathwatch", ["deathwatch"]),
    "grey_knights": ("Grey Knights", ["greyknights"]),
    "adepta_sororitas": ("Adepta Sororitas", ["adeptasororitas", "sistersofbattle"]),
    "adeptus_custodes": ("Adeptus Custodes", ["adeptuscustodes", "custodes"]),
    "adeptus_mechanicus": ("Adeptus Mechanicus", ["adeptusmechanicus"]),
    "astra_militarum": ("Astra Militarum", ["astramilitarum"]),
    "imperial_knights": ("Imperial Knights", ["imperialknights"]),
    "imperial_agents": ("Imperial Agents", ["imperialagents", "agentsoftheimperium"]),
    "adeptus_titanicus": ("Adeptus Titanicus", ["adeptustitanicus"]),
    "chaos_space_marines": ("Chaos Space Marines", ["chaosspacemarines", "hereticastartes"]),
    "death_guard": ("Death Guard", ["deathguard"]),
    "thousand_sons": ("Thousand Sons", ["thousandsons"]),
    "world_eaters": ("World Eaters", ["worldeaters"]),
    "emperors_children": ("Emperor’s Children", ["emperorschildren"]),
    "chaos_daemons": ("Chaos Daemons", ["chaosdaemons", "daemons"]),
    "chaos_knights": ("Chaos Knights", ["chaosknights"]),
    "aeldari": ("Aeldari", ["aeldari", "craftworlds"]),
    "drukhari": ("Drukhari", ["drukhari"]),
    "genestealer_cults": ("Genestealer Cults", ["genestealercults", "genestealercult"]),
    "leagues_of_votann": ("Leagues of Votann", ["leaguesofvotann", "votann"]),
    "necrons": ("Necrons", ["necrons"]),
    "orks": ("Orks", ["orks"]),
    "tau_empire": ("T’au Empire", ["tauempire", "tau"]),
    "tyranids": ("Tyranids", ["tyranids"]),
}
ALIAS = {s: k for k, (_, ss) in FACTIONS.items() for s in ss}

# e.g. eng_08-10_warhammer40000_faction_pack_adeptus_titanicus-ovucwiw1o6-jmk9dpdulj.pdf
# Factions with a recent codex get "Printed Product Updates" instead of a Faction Pack,
# e.g. eng_14-10_wh40k_printed_product_updates_space_marines_updates-91hillwcff-wzs8qnozam.pdf
PDF = re.compile(r"[A-Za-z0-9_./%:-]*(?:faction[_-]?pack|printed[_-]?product[_-]?updates)[A-Za-z0-9_./%-]*\.pdf", re.I)
SLUG = re.compile(r"(?:faction[_-]?pack|printed[_-]?product[_-]?updates)[_-]+([a-z0-9_-]+?)(?:[_-]v?\d[\d_.-]*)?-[a-z0-9]{6,}-[a-z0-9]{6,}\.pdf$", re.I)
LANG = re.compile(r"^(eng|en|fra|fre|fr|ger|de|spa|es|ita|it|jpn|jp|chi|zh|kor|pol|rus)[_-]", re.I)
DATEKEYS = ("date_universal", "date", "updated_at", "last_updated", "updated", "modified", "published")


def absolute(path):
    path = path.replace("\\/", "/")
    if path.startswith("//"):
        return "https:" + path
    if path.startswith("http"):
        return path
    return ASSETS + path.lstrip("/")


def parse(url):
    """(key, name, lang) from a pack URL, or None if the faction cannot be read from it."""
    file = url.rsplit("/", 1)[-1]
    m = SLUG.search(file)
    if not m:
        return None
    slug = m.group(1).lower().replace("-", "_").strip("_")
    slug = re.sub(r"_updates$", "", slug)
    key = ALIAS.get(slug.replace("_", ""))
    name = FACTIONS[key][0] if key else slug.replace("_", " ").title()
    lm = LANG.match(file)
    lang = (lm.group(1).lower() if lm else "eng")[:2]
    return key or slug, name, lang


def kind(url):
    return "updates" if re.search(r"printed[_-]?product[_-]?updates", url, re.I) else "pack"


def walk(o, found, date=None):
    """Every pack URL inside a JSON value, with the closest date field seen above it."""
    if isinstance(o, dict):
        d = next((str(o[k]) for k in DATEKEYS if isinstance(o.get(k), str) and o.get(k)), None) or date
        for v in o.values():
            walk(v, found, d)
    elif isinstance(o, list):
        for v in o:
            walk(v, found, date)
    elif isinstance(o, str):
        for m in PDF.finditer(o):
            found.append((absolute(m.group(0)), date))


def from_text(text, found):
    text = html.unescape(text).replace("\\u002F", "/").replace("\\/", "/")
    for m in PDF.finditer(text):
        found.append((absolute(m.group(0)), None))


def fetch_api(found):
    if not allowed(API):
        raise RuntimeError("robots.txt disallows " + API)
    bodies = [
        {"index": "downloads_v2", "searchTerm": "", "gameSystem": "warhammer-40000", "language": "english"},
        {"index": "downloads", "locale": "en-gb", "game_systems": ["warhammer-40000"], "page": 0, "perPage": 300,
         "sortBy": "date_desc", "category": "", "collections": ["downloads"], "topics": []},
    ]
    for body in bodies:
        try:
            r = requests.post(API, json=body, timeout=60, headers={
                "User-Agent": UA, "Accept": "application/json", "Accept-Language": "en"})
            if r.ok:
                before = len(found)
                try:
                    walk(r.json(), found)
                except ValueError:
                    from_text(r.text, found)
                print("API", body.get("index"), "->", len(found) - before, "pack link(s)")
                if len(found) > before:
                    return
            else:
                print("API", body.get("index"), "-> HTTP", r.status_code)
        except requests.RequestException as exc:
            print("API", body.get("index"), "->", exc)


def fetch_page(found):
    if not allowed(PAGE):
        raise RuntimeError("robots.txt disallows " + PAGE)
    r = requests.get(PAGE, timeout=60, headers={"User-Agent": UA, "Accept-Language": "en"})
    r.raise_for_status()
    before = len(found)
    from_text(r.text, found)
    print("page ->", len(found) - before, "pack link(s)")


def newest(found):
    """One pack per faction: English first, then the newest date, then the first one listed."""
    packs = {}
    for i, (url, date) in enumerate(found):
        p = parse(url)
        if not p:
            continue
        key, name, lang = p
        rank = (lang == "en", kind(url) == "pack", date or "", -i)
        cur = packs.get(key)
        if cur is None or rank > cur["_rank"]:
            packs[key] = {"name": name, "url": url, "file": url.rsplit("/", 1)[-1],
                          "date": date, "lang": lang, "kind": kind(url), "_rank": rank}
    for v in packs.values():
        v.pop("_rank")
    return dict(sorted(packs.items(), key=lambda kv: kv[1]["name"].lower()))


def main():
    found = []
    for step in (fetch_api, fetch_page):
        try:
            step(found)
        except Exception as exc:
            print(step.__name__, "failed:", exc)
        if found:
            break
    packs = newest(found)
    if not packs:
        print("No faction pack found: keeping the previous file.")
        if not OUT.exists():
            OUT.write_text(json.dumps({"fetched_at": None, "source": PAGE, "packs": {}}, indent=1) + "\n")
        return 1
    OUT.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": PAGE, "packs": packs}, ensure_ascii=False, indent=1) + "\n")
    print(len(packs), "faction pack(s):", ", ".join(packs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
