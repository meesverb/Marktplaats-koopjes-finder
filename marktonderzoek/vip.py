"""Stap 2: een steekproef van advertentiepagina's per hoofdcategorie (weergaven,
favorieten, echte plaatsingsdatum, particulier/handelaar, verzending) uit de
subcategorieën die collect.py bewaarde. Argument: aantal per hoofdcategorie.
"""
import json, glob, os, time, random, requests, sys, collections, re
S=os.getcwd(); RAW=os.path.join(S,'raw'); OUT=os.path.join(S,'vip.json')
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
s=requests.Session(); s.headers.update({"User-Agent":UA,"Accept-Language":"nl-NL,nl;q=0.9"})
res=json.load(open(OUT)) if os.path.exists(OUT) else {}
N=int(sys.argv[1]) if len(sys.argv)>1 else 14
random.seed(7)
per=collections.defaultdict(list)
for f in sorted(glob.glob(os.path.join(RAW,'l2_*.json'))):
    l1=f.split('_')[1]; t=os.path.getmtime(f)
    for l in json.load(open(f))['listings']:
        if not any('TOPPER' in x for x in l.get('traits',[])) and l.get('vipUrl'):
            per[l1].append(dict(id=l['itemId'],url=l['vipUrl'],t=t,cat=l['categoryId'],pt=l['priceInfo'].get('priceType'),price=l['priceInfo'].get('priceCents'),date=l.get('date')))
def g(pat,t,conv=str):
    m=re.search(pat,t); return conv(m.group(1)) if m else None
for l1,items in sorted(per.items(),key=lambda x:int(x[0])):
    random.shuffle(items)
    for it in items[:N]:
        if it['id'] in res: continue
        time.sleep(2.0)
        try: r=s.get("https://www.marktplaats.nl"+it['url'],timeout=20,allow_redirects=False); code=r.status_code; t=r.text if code==200 else ''
        except Exception as e: code=-1; t=''
        if code in (403,429): print('blocked',code,flush=True); time.sleep(60); continue
        rec=dict(it, l1=l1, code=code, age_h=(time.time()-it['t'])/3600)
        if t:
            rec.update(views=g(r'"viewCount":(\d+)',t,int), favs=g(r'"favoritedCount":(\d+)',t,int), since=g(r'"stats":\{[^}]*"since":"([^"]+)"',t),
                seller_type=g(r'"sellerType":"([A-Z_]+)"',t), active_years=g(r'"activeYears":(\d+)',t,int), ad_type=g(r'"adType":"(\w+)"',t),
                shipping_method=g(r'"shipping_method":"([^"]*)"',t), shippable=g(r'"shippable":(true|false)',t),
                ship_price=g(r'"price":"€ ([0-9,]+)","carrierName"',t), nbids=len(re.findall(r'"bidId"|"bidder"',t)) if '"bids":[]' not in t else 0,
                buyer_prot=g(r'"buyerProtection":"(\d)"',t), availability=g(r'schema.org\\u002F(InStock|SoldOut|OutOfStock|Discontinued)',t),
                reserved=g(r'"isReserved":(true|false)',t), desc_len=len(g(r'"description":"((?:[^"\\]|\\.)*)"',t) or ''))
        res[it['id']]=rec; json.dump(res,open(OUT,'w'))
    print(l1,flush=True)
print('done')
