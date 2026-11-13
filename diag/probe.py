import sys, json, importlib.util
spec=importlib.util.spec_from_file_location("sn","scripts/scrape_news.py"); sn=importlib.util.module_from_spec(spec); spec.loader.exec_module(sn)
print("=== API PATH"); [print(" ",i["date"],"|",i["title"],"|",i["url"],"|",i["image"]) for i in sn.wcfr_api()]
print("=== HTML FALLBACK"); [print(" ",i["date"],"|",i["title"]) for i in sn.wcfr_html()]
print("=== GOONHAMMER"); [print(" ",i["date"],"|",i["title"]) for i in sn.goonhammer()]
print("=== FULL main()"); sn.main(); d=json.load(open("data/news.json")); print({k:(len(v) if isinstance(v,list) else v) for k,v in d.items()})
