"""Stap 4: subcategorieën scoren en sorteren (l2_scored.json). De gewichten
staan in MARKTONDERZOEK.md §5."""
import json,math,csv,os
S=os.getcwd()
m=json.load(open(os.path.join(S,'metrics.json')))
EXCL={167,378,1098,1032,856,1984}  # geen tweedehands spullen
def ramp(x,a,b):
    if x is None: return 0
    return max(0,min(1,(x-a)/(b-a)))
rows=[]
for cid,v in m['l2'].items():
    if v['l1'] in EXCL: continue
    med=v['med']
    s_vol=ramp(math.log10(max(v['per_day'],0.1)),math.log10(3),math.log10(60))
    s_ship=ramp(v['ship'],0.3,0.9) if v['ship'] is not None else 0.3
    s_price=0 if med is None else (ramp(med,8,40) if med<1500 else max(0,1-ramp(med,1500,10000)))
    s_data=ramp(v['numeric'],0.4,0.9)
    bfill=v['brand_fill'] or 0
    nf=sum(1 for k,x in v['fill'].items() if x>=0.3)
    s_struct=0.65*ramp(bfill,0.1,0.7)+0.35*min(1,nf/3)
    s_liq=1-ramp(v['life_days'],25,75) if v['life_days'] else 0
    score=100*(.2*s_vol+.2*s_ship+.2*s_price+.15*s_data+.15*s_struct+.1*s_liq)
    rows.append(dict(l1=v['l1name'],l2=v['name'],id=cid,score=round(score,1),total=v['total'],per_day=round(v['per_day'],1),
        ship=round(v['ship'],2) if v['ship'] is not None else '',life=round(v['life_days']) if v['life_days'] else '',
        med=med,p25=v['p25'],p75=v['p75'],numeric=round(v['numeric'],2),fast_bid=round(v['fast_bid'],2),
        brand=round(v['brand_fill'],2) if v['brand_fill'] is not None else '',brand_key=v['brand_key'] or '',brand_n=v['brand_n'],brand_top=v['brand_top'],facets=' '.join(v['facets'][:8]),used=round(v['cond_used'],2) if v['cond_used'] is not None else '',
        new=round(v['cond_new'],2) if v['cond_new'] is not None else '', broken=round(v['cond_broken'],3) if v['cond_broken'] is not None else '',
        s=(round(s_vol,2),round(s_ship,2),round(s_price,2),round(s_data,2),round(s_struct,2),round(s_liq,2))))
rows.sort(key=lambda r:-r['score'])
json.dump(rows,open(os.path.join(S,'l2_scored.json'),'w'),ensure_ascii=False)
if __name__=='__main__':
    for r in rows[:70]: print('%5.1f %-26s %-34s %6d/d ship %-4s life %-3s med %-7s num %.2f fb %.2f br %-4s %s'%(r['score'],r['l1'][:26],r['l2'][:34],r['per_day'],r['ship'],r['life'],r['med'],r['numeric'],r['fast_bid'],r['brand'],r['facets'][:50]))
