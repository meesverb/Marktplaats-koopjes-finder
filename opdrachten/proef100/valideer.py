"""Controleer Claude-uitkomsten tegen de manifests: python valideer.py haiku"""
import json, re, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
B = HERE.parent / "blind100"
prefix = sys.argv[1]
ok = 0
for n in range(1, 21):
    want = re.findall(r"^(adv\d{3}):", (B / f"batch{n:02d}.txt").read_text(), re.M)
    f = HERE / "claude" / f"{prefix}_b{n:02d}.json"
    if not f.exists():
        print(f"b{n:02d}: ontbreekt"); continue
    try:
        d = json.loads(f.read_text())
    except Exception as e:
        print(f"b{n:02d}: kapot {e}"); continue
    got = sorted(d) if isinstance(d, dict) else sorted(x.get("advertentie", "?") for x in d)
    if got != sorted(want):
        print(f"b{n:02d}: verwacht {want}, kreeg {got}")
    else:
        ok += 1
print(prefix, ok, "van 20 in orde")
