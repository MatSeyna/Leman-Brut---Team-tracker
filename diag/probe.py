import re, json, requests
UA="LemanBrutTeamTracker/1.0 (private team tool; 2 runs per day)"
WC="https://www.warhammer-community.com"
H={"User-Agent":UA,"Accept-Language":"fr,en;q=0.8"}
ART=re.compile(r"/fr-fr/articles/[A-Za-z0-9]+/[^\"'<>\s?#\\]+")
print("ROBOTS:\n", requests.get(WC+"/robots.txt",headers=H,timeout=30).text[:1500])
for p in ["/fr-fr/","/fr-fr/feed/","/feed/","/fr-fr/latest-news-features/","/fr-fr/warhammer-40000/","/fr-fr/setting/warhammer-40000/","/fr-fr/latest/"]:
    try:
        r=requests.get(WC+p,headers=H,timeout=30); t=r.text.replace("\\u002F","/").replace("\\/","/")
        print("\n=== GET",p,r.status_code,len(t),r.headers.get("content-type"))
        links=[]
        for m in ART.finditer(t):
            if m.group(0) not in links: links.append(m.group(0))
        print(" n links",len(links))
        for l in links[:25]: print("  ",l)
        for k in ["__NEXT_DATA__","__NUXT__","/api/","algolia","date_desc","perPage"]:
            i=t.find(k)
            if i>=0: print(" FOUND",k,":",t[max(0,i-150):i+250].replace("\n"," ")[:400])
    except Exception as e: print("ERR",p,e)
body={"sortBy":"date_desc","category":"","collections":["articles"],"game_systems":[],"index":"news","locale":"fr-fr","page":0,"perPage":12,"topics":[]}
for url in [WC+"/api/search/news/",WC+"/api/search/news"]:
    try:
        r=requests.post(url,json=body,headers={**H,"Content-Type":"application/json","Accept":"application/json"},timeout=30)
        print("\n=== POST",url,r.status_code,r.headers.get("content-type")); print(r.text[:3000])
    except Exception as e: print("ERR",url,e)
