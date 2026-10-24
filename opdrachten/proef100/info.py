"""Tekst van advertenties voor de antwoordsleutel: python info.py 1 5 (adv001-adv005)."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ads = json.loads((HERE / "advertenties.json").read_text())
mapping = json.loads((HERE / "blind100_map.json").read_text())
lo, hi = int(sys.argv[1]), int(sys.argv[2])
for k in range(lo, hi + 1):
    adv = f"adv{k:03d}"
    a = ads[mapping[adv]]
    sheets = sorted(p.name for p in (HERE / "bladen").glob(f"{mapping[adv]}_blad*.jpg"))
    desc = " ".join((a.get("description") or "").split())
    print(f"== {adv} {mapping[adv]} €{a['price']} | {a['title']}")
    print(f"   kenmerken: {a.get('kenmerken')}")
    print(f"   omschrijving: {desc[:700]}")
    print(f"   {len(a['photos'])} foto's, bladen: {' '.join(sheets)}")
