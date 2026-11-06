#!/usr/bin/env python3
"""Latest Warhammer 40,000 articles from Goonhammer (RSS) and Warhammer Community FR.

Writes data/news.json: {"fetched_at", "goonhammer":[3 items], "wcfr":[3 items]}.
Each item: title, url, date (ISO), summary, image. A source that fails keeps its previous
items (from the existing file) so the app never shows an empty column because of one bad run.
One short burst of requests per run, robots.txt respected, polite User-Agent.
"""
import html
import json
import pathlib
import re
import sys
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = "LemanBrutTeamTracker/1.0 (private team tool; 2 runs per day)"
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "news.json"
N = 3
K40 = re.compile(r"40[\s,.  -]*0{3}|40k|40-?000|\bw40k\b", re.I)
FACT = re.compile(r"\b(astartes|space marines?|necrons?|orks?|tyranids?|genestealer|aeldari|drukhari|t.au|death guard|custodes|adepta|astra militarum|votann|grey knights|world eaters|thousand sons|chaos (space|knights|daemons)|imperial knights|codex|kill team|primaris|warhammer 40)\b", re.I)
WC = "https://www.warhammer-community.com"
_robots = {}


def allowed(url):
    host = re.match(r"https?://[^/]+", url).group(0)
    rp = _robots.get(host)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = requests.get(host + "/robots.txt", headers={"User-Agent": UA}, timeout=30)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            rp.parse([])
        _robots[host] = rp
    return rp.can_fetch(UA, url)


def get(url, **kw):
    if not allowed(url):
        raise RuntimeError("robots.txt disallows " + url)
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "fr,en;q=0.8"}, timeout=60, **kw)
    r.raise_for_status()
    return r


def clean(s, n=240):
    s = BeautifulSoup(html.unescape(s or ""), "html.parser").get_text(" ", strip=True)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*(The post|Cet article|L’article|L'article).*$", "", s) if "The post" in s else s
    s = s.replace("[…]", "").replace("[&#8230;]", "").replace("…", "").strip()
    if len(s) > n:
        s = s[:n].rsplit(" ", 1)[0].rstrip(",;:.") + "…"
    return s


def iso(s):
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
        except Exception:
            return None


# ---------------------------------------------------------------- Goonhammer
def goonhammer():
    ns = {"c": "http://purl.org/rss/1.0/modules/content/", "m": "http://search.yahoo.com/mrss/"}
    items = []
    urls_seen = []
    firsts = set()
    for page in range(1, 7):
        url = "https://www.goonhammer.com/feed/" + ("?paged=%d" % page if page > 1 else "")
        if page > 1 and urls_seen and urls_seen[-1] == "same":
            url = "https://www.goonhammer.com/feed/page/%d/" % page
        try:
            root = ET.fromstring(get(url).content)
            if page > 1 and root.find(".//item/link") is not None and root.find(".//item/link").text in firsts:
                root = ET.fromstring(get("https://www.goonhammer.com/feed/page/%d/" % page).content)
        except Exception as exc:
            if page == 1:
                raise
            print("goonhammer page", page, "skipped:", exc)
            break
        first = (root.find(".//item/link").text if root.find(".//item/link") is not None else "")
        urls_seen.append("same" if first in firsts else "new")
        firsts.add(first)
        print("goonhammer feed page", page, "first item:", first)
        for it in root.iter("item"):
            title = html.unescape(it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            cats = [c.text or "" for c in it.findall("category")]
            body = it.findtext("c:encoded", namespaces=ns) or ""
            desc = it.findtext("description") or ""
            hay = " ".join([title, link] + cats)
            if not K40.search(hay) or re.search(r"battletech|age of sigmar|old world", title, re.I):
                continue
            img = None
            mc = it.find("m:content", ns) or it.find("m:thumbnail", ns)
            if mc is not None and mc.get("url"):
                img = mc.get("url")
            if not img:
                m = re.search(r'<img[^>]+src="([^"]+)"', body)
                img = m.group(1) if m else None
            items.append({"title": title, "url": link, "date": iso(it.findtext("pubDate") or ""),
                          "summary": clean(desc or body), "image": img})
        if len({i["url"] for i in items}) >= N:
            break
    items = list({i["url"]: i for i in items}.values())
    items.sort(key=lambda x: x["date"] or "", reverse=True)
    if not items:
        raise RuntimeError("no 40k item found in the Goonhammer feed")
    return items[:N]


# ------------------------------------------------------- Warhammer Community FR
ART = re.compile(r"/fr-fr/articles/[A-Za-z0-9]+/[^\"'<>\s?#\\]+")


def meta(soup, *names):
    for n in names:
        el = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
        if el and el.get("content"):
            return el["content"].strip()
    return None


def wcfr():
    links = []
    feeds = [WC + "/fr-fr/feed/", WC + "/feed/"]
    for f in feeds:  # an RSS feed is the cleanest source if it exists
        try:
            r = get(f)
            if b"<item" in r.content[:200000]:
                for it in ET.fromstring(r.content).iter("item"):
                    u = (it.findtext("link") or "").strip()
                    if "/fr-fr/" in u:
                        links.append(u)
                break
        except Exception:
            pass
    if not links:
        for page in (WC + "/fr-fr/", WC + "/fr-fr/all-news-and-features/", WC + "/fr-fr/the-latest/"):
            try:
                txt = get(page).text.replace("\\u002F", "/").replace("\\/", "/")
            except Exception as exc:
                print("wcfr listing skipped:", page, exc)
                continue
            for m in ART.finditer(txt):
                links.append(urljoin(WC, m.group(0)))
    seen, uniq = set(), []
    for u in links:
        u = u.split("#")[0]
        if not u.endswith("/"):
            u += "/"
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    if not uniq:
        raise RuntimeError("no article link found on Warhammer Community FR")
    items = []
    for u in uniq[:40]:
        try:
            soup = BeautifulSoup(get(u).text, "html.parser")
        except Exception as exc:
            print("wcfr article skipped:", u, exc)
            continue
        title = meta(soup, "og:title", "twitter:title") or (soup.title.string if soup.title else "")
        title = re.sub(r"\s*[-|–]\s*Warhammer Community\s*$", "", title or "").strip()
        desc = meta(soup, "og:description", "description") or ""
        tags = " ".join(t.get("content", "") for t in soup.find_all("meta", attrs={"property": "article:tag"}))
        kw = meta(soup, "keywords") or ""
        jl = " ".join(re.findall(r'"(?:keywords|articleSection)"\s*:\s*("?[^"\]}]*)', str(soup)))
        hay = " ".join([title, desc, tags, kw, jl, u])
        slug = u.rsplit("/", 2)[-2].replace("-", " ")
        if not (K40.search(title + " " + u) or FACT.search(title + " " + slug)):
            continue
        d = iso(meta(soup, "article:published_time", "og:article:published_time") or "")
        if not d:
            m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', str(soup))
            d = iso(m.group(1)) if m else None
        items.append({"title": title, "url": u, "date": d, "summary": clean(desc), "image": meta(soup, "og:image")})
        if len(items) >= 6:  # a few spare, then sort by date
            break
    if not items:
        raise RuntimeError("no 40k article found on Warhammer Community FR")
    items.sort(key=lambda x: x["date"] or "", reverse=True)
    return items[:N]


def main():
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            old = {}
    out = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    errors = []
    for key, fn in (("goonhammer", goonhammer), ("wcfr", wcfr)):
        try:
            out[key] = fn()
            print("OK", key, [i["title"][:50] for i in out[key]])
        except Exception as exc:
            print("ERROR", key, exc, file=sys.stderr)
            errors.append(key)
            out[key] = old.get(key, [])
            out[key + "_error"] = str(exc)[:200]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if len(errors) == 2:
        sys.exit(1)


if __name__ == "__main__":
    main()
