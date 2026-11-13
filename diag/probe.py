import json, importlib.util
spec=importlib.util.spec_from_file_location("sn","scripts/scrape_news.py"); sn=importlib.util.module_from_spec(spec); spec.loader.exec_module(sn)
print("=== MERGED COLUMN"); [print(" ",i["lang"],"|",i["date"][:10],"|",i["title"],"|",i["url"]) for i in sn.wcfr_api()]
en=sn.wc_api("en-gb"); fr={sn.wc_uuid(n) for n in sn.wc_api("fr-fr")}
print("=== EN 40k candidates (x = has FR version)")
for n in en:
    if sn.is_40k(n): print(" ","x" if sn.wc_uuid(n) in fr else "-",n["date_universal"],n["title"][:70])
print("=== FULL main()"); sn.main(); d=json.load(open("data/news.json")); print([(i.get("lang"),i["title"][:40]) for i in d["wcfr"]], d.get("wcfr_error"))
