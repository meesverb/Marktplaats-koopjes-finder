"""Stap 5: de tabellen voor MARKTONDERZOEK.md en marktonderzoek_subcategorieen.csv."""
import json, os, csv, statistics as st, collections, datetime
S=os.getcwd()
m=json.load(open(os.path.join(S,'metrics.json'))); rows=json.load(open(os.path.join(S,'l2_scored.json')))
vip=json.load(open(os.path.join(S,'vip.json'))) if os.path.exists(os.path.join(S,'vip.json')) else {}
def pct(x): return '–' if x is None else f"{100*x:.0f}%"
def eur(x):
    if x is None: return '–'
    return f"€{x:,.0f}".replace(',', '.') if x>=10 else f"€{x:.2f}".replace('.',',')
def nm(x): return x.replace(' | ',' › ')
def num(x): return f"{x:,.0f}".replace(',', '.')
# VIP aggregates per L1
va={}
now=datetime.datetime.now(datetime.timezone.utc)
for l1 in m['l1']:
    xs=[v for v in vip.values() if v['l1']==l1]
    if not xs: continue
    ok=[v for v in xs if v['code']==200]
    gone=sum(1 for v in xs if v['code'] in (404,410))
    vpd=[]
    for v in ok:
        if v.get('since') and v.get('views') is not None:
            t=datetime.datetime.fromisoformat(v['since'].replace('Z','+00:00')); h=max((now-t).total_seconds()/3600,1)
            if h>=6: vpd.append(v['views']/h*24)
    va[l1]=dict(n=len(xs), gone=gone/len(xs), age=st.median(v['age_h'] for v in xs),
        biz=(sum(1 for v in ok if v.get('seller_type') and v['seller_type']!='CONSUMER')/len(ok)) if ok else None,
        vpd=st.median(vpd) if vpd else None, favs=st.mean(v.get('favs') or 0 for v in ok) if ok else None,
        bp=(sum(1 for v in ok if v.get('buyer_prot')=='1')/len(ok)) if ok else None,
        bids=(sum(1 for v in ok if (v.get('nbids') or 0)>0)/len(ok)) if ok else None)
json.dump(va,open(os.path.join(S,'vip_agg.json'),'w'),indent=1)
L=sorted(m['l1'].items(),key=lambda x:-x[1]['total'])
out=[]
out.append('| Hoofdcategorie | Aanbod | Nieuw/dag | Looptijd (d) | Verzendbaar | Direct Kopen | Mediane prijs [p25–p75] | Met prijs | Bieden zonder prijs | Nieuw | Merk/model ingevuld | Bedrijf* | Weergaven/dag* |')
out.append('|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|')
for l1,v in L:
    a=va.get(l1,{})
    subs=[r for r in rows if str(r['id']) in {str(c[0]) for c in v['l2']}]
    bf=[ (mm['brand_fill'] or 0, mm['total']) for cid,mm in m['l2'].items() if mm['l1']==int(l1)]
    tb=sum(t for _,t in bf) or 1; brandfill=sum(b*t for b,t in bf)/tb
    shipcell=pct(v['ship']) if v['name']!="Auto's" else 'n.v.t.'
    out.append(f"| {nm(v['name'])} | {num(v['total'])} | {num(v['per_day'])} | {v['life_days']:.0f} | {shipcell} | {pct(v['bin'])} | {eur(v['w_med'])} [{eur(v['w_p25'])}–{eur(v['w_p75'])}] | {pct(v['w_numeric'])} | {pct(v['w_fastbid'])} | {pct(v['cond_new'])} | {pct(brandfill)} | {pct(a.get('biz'))} | {('%.0f'%a['vpd']) if a.get('vpd') is not None else '–'} |")
open(os.path.join(S,'tbl_l1.md'),'w').write('\n'.join(out))
# top L2
out=['| # | Subcategorie | Hoofdcategorie | Score | Nieuw/dag | Aanbod | Verzendbaar | Looptijd (d) | Mediane prijs | Met prijs | Merk/model ingevuld | Grootste merken |','|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
for i,r in enumerate(rows[:50]):
    bt=', '.join(b for b,_ in r['brand_top'][:3])
    out.append(f"| {i+1} | {nm(r['l2'])} | {nm(r['l1'])} | {r['score']:.0f} | {num(r['per_day'])} | {num(r['total'])} | {pct(r['ship'] if r['ship']!='' else None)} | {r['life']} | {eur(r['med'])} | {pct(r['numeric'])} | {pct(r['brand'] if r['brand']!='' else None)} | {bt} |")
open(os.path.join(S,'tbl_l2.md'),'w').write('\n'.join(out))
# CSV all L2
with open(os.path.join(S,'marktonderzoek_subcategorieen.csv'),'w',newline='') as f:
    w=csv.writer(f); w.writerow(['rang','hoofdcategorie','subcategorie','l2_id','score','aanbod','nieuw_per_dag','looptijd_dagen','verzendbaar','mediane_prijs','p25','p75','aandeel_met_prijs','aandeel_bieden_zonder_prijs','merk_veld','merk_ingevuld','aantal_merken','grootste_merken','nieuw','gebruikt','niet_werkend','filters'])
    for i,r in enumerate(rows):
        w.writerow([i+1,r['l1'],r['l2'],r['id'],r['score'],r['total'],r['per_day'],r['life'],r['ship'],r['med'],r['p25'],r['p75'],r['numeric'],r['fast_bid'],r['brand_key'],r['brand'],r['brand_n'],'; '.join(b for b,_ in r['brand_top'][:5]),r['new'],r['used'],r['broken'],r['facets']])
print('ok',len(va))
