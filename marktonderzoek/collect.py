"""Stap 1 van het marktonderzoek (MARKTONDERZOEK.md): per hoofdcategorie en
subcategorie de zoek-API bevragen en de antwoorden als JSON in raw/ bewaren.

Draai vanuit een lege map, niet vanuit de repo: alles komt in de werkmap
(~270 MB). Al opgehaalde bestanden worden overgeslagen, dus een tweede run
haalt alleen op wat de eerste keer mislukte (Marktplaats weigert soms een
reeks verzoeken met 403). Eén verzoek tegelijk, met pauze.

    python /pad/naar/repo/marktonderzoek/collect.py
"""
import json, time, os, sys, re, requests
from urllib.parse import urlencode
S=os.getcwd(); RAW=os.path.join(S,'raw'); os.makedirs(RAW,exist_ok=True)
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
s=requests.Session(); s.headers.update({"User-Agent":UA,"Accept-Language":"nl-NL,nl;q=0.9"})
DELAY=3.5
def get(name, params):
    p=os.path.join(RAW,name+'.json')
    if os.path.exists(p): return json.load(open(p))
    for attempt in range(4):
        time.sleep(DELAY*(1+2*attempt))
        try:
            r=s.get("https://www.marktplaats.nl/lrp/api/search?"+urlencode(params),timeout=20)
            if r.status_code==200 and r.text.strip():
                d=r.json(); json.dump(d,open(p,'w')); return d
            print('status',r.status_code,name,file=sys.stderr)
        except Exception as e: print('err',name,e,file=sys.stderr)
    return None
HOME=os.path.join(S,'home.html')
if not os.path.exists(HOME):
    open(HOME,'w').write(s.get("https://www.marktplaats.nl/",timeout=20).text)
home=open(HOME).read()
L1=sorted(set((int(a),b) for a,b in re.findall(r'/cp/(\d+)/([a-z0-9-]+)/',home)))
base=[("limit",30),("sortBy","SORT_INDEX"),("sortOrder","DECREASING")]
n=0
for l1,key in L1:
    d=get(f'l1_{l1}_p1',[("l1CategoryId",l1),("offset",0)]+base)
    if not d: continue
    get(f'l1_{l1}_bin',[("l1CategoryId",l1),("offset",0),("attributesByKey[]","buyitnow:true")]+base)
    for pg in (2,3,4):
        get(f'l1_{l1}_p{pg}',[("l1CategoryId",l1),("offset",(pg-1)*30)]+base)
    # L2 list
    l2s=[c for f in d['facets'] if f['key']=='RelevantCategories' for c in f.get('categories',[]) if c.get('parentId')==l1]
    for c in l2s:
        get(f'l2_{l1}_{c["id"]}',[("l1CategoryId",l1),("l2CategoryIds",c['id']),("offset",0)]+base)
        n+=1
    print(l1,key,d['totalResultCount'],len(l2s),flush=True)
print('done',n)
