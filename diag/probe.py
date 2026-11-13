import json, requests
UA="LemanBrutTeamTracker/1.0 (private team tool; 2 runs per day)"
WC="https://www.warhammer-community.com"
H={"User-Agent":UA,"Accept-Language":"fr,en;q=0.8","Content-Type":"application/json","Accept":"application/json"}
def q(**kw):
    body={"sortBy":"date_desc","category":"","collections":["articles"],"game_systems":[],"index":"news","locale":"fr-fr","page":0,"perPage":30,"topics":[]}
    body.update(kw)
    r=requests.post(WC+"/api/search/news/",json=body,headers=H,timeout=30); r.raise_for_status(); return r.json()
d=q()
print("TOP KEYS", {k:(v if not isinstance(v,list) else len(v)) for k,v in d.items()})
print("ITEM0", json.dumps(d["news"][0],ensure_ascii=False)[:2500])
for n in d["news"]:
    print("-", n.get("date"), "|", (n.get("game_system") or {}).get("title"), "|", n.get("title"), "|", n.get("uuid"), [t.get("title") for t in (n.get("topics") or [])][:4])
for gs in ["warhammer-40000","warhammer-40-000","40k"]:
    try:
        d2=q(game_systems=[gs],perPage=5)
        print("\nFILTER",gs,[(n.get("date"),n.get("title")) for n in d2["news"]])
    except Exception as e: print("FILTER",gs,"ERR",e)
