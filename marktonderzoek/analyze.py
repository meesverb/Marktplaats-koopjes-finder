"""Stap 3: raw/*.json omzetten naar metrics.json (per hoofd- en subcategorie)."""
import json, glob, os, re, statistics as st, collections, csv, sys
S=os.getcwd(); RAW=os.path.join(S,'raw')
def load(n):
    p=os.path.join(RAW,n+'.json'); return json.load(open(p)) if os.path.exists(p) else None
home=open(os.path.join(S,'home.html')).read()
L1=sorted(set((int(a),b) for a,b in re.findall(r'/cp/(\d+)/([a-z0-9-]+)/',home)))
GENERIC={'PriceCents','RelevantCategories','buyitnow','condition','urgency','delivery','offeredSince','advertiser','priceType'}
def facet(d,key): return next((f for f in d['facets'] if f['key']==key),None)
def grp(d,key):
    f=facet(d,key); return {a.get('attributeValueLabel'):(a.get('histogramCount') or 0) for a in (f or {}).get('attributeGroup',[])}
def metrics(d, listings):
    T=d['totalResultCount']; dl=grp(d,'delivery'); os_=grp(d,'offeredSince'); cond=grp(d,'condition')
    V=dl.get('Verzenden') or 0; O=dl.get('Ophalen') or 0
    week=os_.get('Een week') or 0; today=os_.get('Vandaag') or 0; yest=os_.get('Gisteren') or 0
    pt=collections.Counter(l['priceInfo'].get('priceType') for l in listings)
    nt=[l for l in listings if not any('TOPPER' in t for t in l.get('traits',[]))]
    base_=nt if len(nt)>=8 else listings
    prices=[l['priceInfo']['priceCents']/100 for l in base_ if l['priceInfo'].get('priceType') in('FIXED','MIN_BID') and l['priceInfo'].get('priceCents')]
    n=len(listings) or 1
    attrs=[len({a['key'] for a in l.get('extendedAttributes',[])+l.get('attributes',[])} - {'condition','delivery','priceType'}) for l in listings]
    brand=sum(1 for l in listings if any(a['key'] in('brand','model','merk') and 'Overige' not in a.get('value','') for a in l.get('extendedAttributes',[])+l.get('attributes',[])))
    dagtop=sum(1 for l in listings if any('TOPPER' in t for t in l.get('traits',[])))
    desc=[len(l.get('categorySpecificDescription') or l.get('description') or '') for l in listings]
    nl=sum(1 for l in listings if (l.get('location') or {}).get('countryAbbreviation')=='NL')
    abroad=sum(1 for l in listings if (l.get('location') or {}).get('abroad'))
    verified=sum(1 for l in listings if l['sellerInformation'].get('isVerified'))
    sellers=collections.Counter(l['sellerInformation'].get('sellerId') for l in listings)
    ship_attr=sum(1 for l in listings if any(a['key']=='delivery' and 'Verzenden' in a.get('value','') for a in l.get('attributes',[])))
    fk=[f['key'] for f in d['facets'] if f['key'] not in GENERIC]
    bf=[f for f in d['facets'] if f['key'] not in GENERIC and re.search('brand|merk|model',f['key'],re.I) and 'kenmerk' not in f['key'].lower() and f.get('attributeGroup')]
    if not bf:
        bf=[f for f in d['facets'] if f['key']=='type' and f.get('attributeGroup') and len(f['attributeGroup'])>=5 and 'iPhone' in str(f)]
    brand_fill=None; brand_n=0; brand_top=[]
    if bf:
        g=bf[0]['attributeGroup']; spec=[a for a in g if not re.search('overig|other|onbekend|anders',a.get('attributeValueLabel',''),re.I)]
        brand_fill=min(1,sum(a.get('histogramCount') or 0 for a in spec)/T) if T else None; brand_n=len(spec)
        brand_top=[(a.get('attributeValueLabel'),a.get('histogramCount')) for a in sorted(spec,key=lambda a:-(a.get('histogramCount') or 0))[:6]]
    fill={}
    for f in d['facets']:
        if f['key'] in GENERIC or not f.get('attributeGroup'): continue
        fill[f['key']]=min(1,sum(a.get('histogramCount') or 0 for a in f['attributeGroup'])/T) if T else 0
    return dict(V=V,O=O,has_dl=bool(dl),total=T, ship=(V/T if T and dl else None), pickup_only=((T-V)/T if T and dl else None), ship_only=(T-O)/T if T and O else None,
        today=today, yest=yest, week=week, per_day=week/7, life_days=(T/(week/7) if week else None),
        cond_new=(cond.get('Nieuw',0)/T if T and cond else None), cond_used=((cond.get('Gebruikt',0)+cond.get('Zo goed als nieuw',0))/T if T and cond else None),
        cond_broken=(cond.get('Niet werkend',0)/T if T and cond else None),
        n=len(listings), n_nt=len(nt), pt=pt, numeric=sum(pt[k] for k in('FIXED','MIN_BID'))/n, bid=(pt['FAST_BID']+pt['MIN_BID'])/n,
        fast_bid=pt['FAST_BID']/n, see_desc=(pt['SEE_DESCRIPTION']+pt['NOTK']+pt['ON_REQUEST'])/n,
        med=st.median(prices) if prices else None, p25=(st.quantiles(prices,n=4)[0] if len(prices)>3 else None), p75=(st.quantiles(prices,n=4)[2] if len(prices)>3 else None),
        attrs=st.mean(attrs) if attrs else 0, brand=brand/n, dagtop=dagtop/n, desc=st.median(desc) if desc else 0,
        abroad=abroad/n, verified=verified/n, top_seller_share=(sellers.most_common(1)[0][1]/n if sellers else 0), ship_attr=ship_attr/n,
        facets=fk, brand_key=(bf[0]['key'] if bf else None), brand_fill=brand_fill, brand_n=brand_n, brand_top=brand_top, fill=fill, maxpage=d.get('maxAllowedPageNumber'))
out={'l1':{}, 'l2':{}}
for l1,key in L1:
    d=load(f'l1_{l1}_p1')
    if not d: continue
    ls=[]; seen=set()
    for p in (1,2,3,4):
        x=load(f'l1_{l1}_p{p}')
        for l in (x or {}).get('listings',[]):
            if l['itemId'] not in seen: seen.add(l['itemId']); ls.append(l)
    m=metrics(d,ls); b=load(f'l1_{l1}_bin'); m['bin']=(b['totalResultCount']/m['total']) if b and m['total'] else None
    name=d['searchCategory'] if isinstance(d['searchCategory'],str) else None
    cats=[c for f in d['facets'] if f['key']=='RelevantCategories' for c in f['categories']]
    m['name']=next((c['label'] for c in cats if c['id']==l1), key); m['key']=key
    m['l2']=[(c['id'],c['label'],c.get('histogramCount')) for c in cats if c.get('parentId')==l1]
    out['l1'][l1]=m
    sv=st_=0
    for cid,lab,cnt in m['l2']:
        e=load(f'l2_{l1}_{cid}')
        if not e: continue
        mm=metrics(e,e['listings']); mm.update(name=lab,l1=l1,l1name=m['name'],id=cid)
        out['l2'][cid]=mm
        if mm['has_dl']: sv+=mm['V']; st_+=mm['total']
    pool=[]
    for cid,lab,cnt in m['l2']:
        e=load(f'l2_{l1}_{cid}')
        if not e or cid not in out['l2']: continue
        nt=[l for l in e['listings'] if not any('TOPPER' in t for t in l.get('traits',[]))] or e['listings']
        w=out['l2'][cid]['per_day']/max(len(nt),1)
        pool+=[(l,w) for l in nt]
    W=sum(w for _,w in pool) or 1
    def wshare(pred): return sum(w for l,w in pool if pred(l))/W
    m['w_numeric']=wshare(lambda l:l['priceInfo'].get('priceType') in('FIXED','MIN_BID'))
    m['w_bid']=wshare(lambda l:l['priceInfo'].get('priceType') in('FAST_BID','MIN_BID'))
    m['w_fastbid']=wshare(lambda l:l['priceInfo'].get('priceType')=='FAST_BID')
    m['w_free']=wshare(lambda l:l['priceInfo'].get('priceType') in('FREE',))
    m['w_seedesc']=wshare(lambda l:l['priceInfo'].get('priceType') in('SEE_DESCRIPTION','NOTK','ON_REQUEST','RESERVED','EXCHANGE'))
    m['w_brand']=wshare(lambda l:any(a['key'] in('brand','model') and 'Overige' not in a.get('value','') for a in l.get('extendedAttributes',[])+l.get('attributes',[])))
    m['w_topper_l2']=sum(1 for f in [0] )
    pr=sorted((l['priceInfo']['priceCents']/100,w) for l,w in pool if l['priceInfo'].get('priceType') in('FIXED','MIN_BID') and l['priceInfo'].get('priceCents'))
    def wq(q):
        tw=sum(w for _,w in pr); acc=0
        for v,w in pr:
            acc+=w
            if acc>=q*tw: return v
    m['w_p25'],m['w_med'],m['w_p75']=(wq(.25),wq(.5),wq(.75)) if pr else (None,None,None)
    m['pt_all']=dict(collections.Counter(l['priceInfo'].get('priceType') for l,_ in pool))
    if not m['has_dl'] and st_: m['ship']=sv/st_; m['ship_from_l2']=True
def conv(o):
    if isinstance(o,collections.Counter): return dict(o)
    raise TypeError
json.dump(out,open(os.path.join(S,'metrics.json'),'w'),default=conv,ensure_ascii=False,indent=0)
print(len(out['l1']),len(out['l2']))
