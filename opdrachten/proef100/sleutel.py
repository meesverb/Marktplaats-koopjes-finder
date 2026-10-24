"""Antwoordsleutel bijwerken. Per advertentie één regel, gescheiden door ';':
    adv001|raleigh|1|rim|steel|shallow||0|zadel kapot, lakschade
velden: adv | merk (leeg = onbekend) | merk leesbaar op een foto (1/0) | rem |
materiaal | wielprofiel | groep (leeg = onbekend) | groep leesbaar (1/0) | notitie
    python sleutel.py "regel; regel; ..."
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
path = HERE / "sleutel.json"
key = json.loads(path.read_text()) if path.exists() else {}
for line in sys.argv[1].split(";"):
    line = line.strip()
    if not line:
        continue
    adv, merk, leesbaar, rem, mat, wiel, groep, groep_l, *notitie = [x.strip() for x in line.split("|")]
    assert rem in ("rim", "disc", "unknown"), line
    assert mat in ("carbon", "aluminium", "steel", "titanium", "unknown"), line
    assert wiel in ("deep", "shallow", "unknown"), line
    key[adv] = {"merk": merk.lower(), "merk_leesbaar": leesbaar == "1", "rem": rem, "materiaal": mat,
                "wielprofiel": wiel, "groep": groep.lower(), "groep_leesbaar": groep_l == "1",
                "notitie": "|".join(notitie)}
path.write_text(json.dumps(key, indent=1, ensure_ascii=False))
print(len(key), "in sleutel")
