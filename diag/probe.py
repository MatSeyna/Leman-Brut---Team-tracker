import json, requests
WC="https://www.warhammer-community.com"
H={"User-Agent":"LemanBrutTeamTracker/1.0 (private team tool; 2 runs per day)","Accept":"application/json"}
def q(loc,n=60):
    body={"sortBy":"date_desc","category":"","collections":["articles"],"game_systems":[],"index":"news","locale":loc,"page":0,"perPage":n,"topics":[]}
    r=requests.post(WC+"/api/search/news/",json=body,headers=H,timeout=30); r.raise_for_status(); return r.json()["news"]
fr=q("fr-fr",40); en=q("en-gb",80)
print("EN0", json.dumps(en[0],ensure_ascii=False)[:1500])
print("EN site values", set(n.get("site") for n in en))
frk={k:{n.get(k) for n in fr} for k in ("id","uuid","slug")}
print("shared keys:", {k:len(frk[k] & {n.get(k) for n in en}) for k in frk})
import re
def ip(n): return re.sub(r"(_fre|_eng|_en)?-[a-z0-9]{10}\.(jpg|png|webp)$","",(n.get("image") or {}).get("path") or "")
fri={ip(n):n for n in fr}
print("\nEN (date | uuid | title | FR match by image stem)")
for n in en[:60]:
    m=fri.get(ip(n))
    print(n.get("date_universal"),"|",n.get("uuid"),"|",n.get("title")[:70],"|",(n.get("game_system") or {}).get("title"),"|", ("FR="+m["uuid"]+" "+m["title"][:40]) if m else "-", "|", ip(n))
print("\nFR stems")
for n in fr[:20]: print(n.get("date_universal"),n.get("uuid"),ip(n),n["title"][:50])
