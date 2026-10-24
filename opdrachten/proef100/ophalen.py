"""Advertentiepagina's en alle foto's (XXL) van de testselectie ophalen.
Eén verzoek tegelijk: 2 s tussen pagina's, 1,5 s tussen foto's."""
import json
import sys
import time
from pathlib import Path

REPO = Path("/home/user/Marktplaats-koopjes-finder")
sys.path.insert(0, str(REPO))
import requests  # noqa: E402

import dossier  # noqa: E402
import racefiets_jev as mp  # noqa: E402

HERE = Path(__file__).resolve().parent
FOTOS = HERE / "fotos"
FOTOS.mkdir(exist_ok=True)
sel = json.loads((HERE / "selectie.json").read_text())
items = sel["test"] + sel["reserve"]
out_path = HERE / "advertenties.json"
done = json.loads(out_path.read_text()) if out_path.exists() else {}

session = requests.Session()
session.headers.update({"User-Agent": mp.USER_AGENT, "Accept-Language": "nl-NL,nl;q=0.9"})
last = [0.0]


def wait(gap):
    left = gap - (time.monotonic() - last[0])
    if left > 0:
        time.sleep(left)
    last[0] = time.monotonic()


for n, item in enumerate(items, 1):
    iid = item["item_id"]
    if iid in done:
        continue
    wait(2.0)
    rec = dict(item)
    try:
        html = mp.fetch_listing_page(session, item["url"])
        page = mp.listing_page_data(html)
        parsed = mp.parse_listing_page(html)
        rec["description"], rec["kenmerken"] = (parsed if parsed else ("", {}))
        rec["photo_urls"] = dossier.page_photos(page)
        rec["status"] = "ok"
    except requests.HTTPError as exc:
        rec["status"] = f"HTTP {exc.response.status_code}"
        rec["photo_urls"] = []
    except Exception as exc:  # pagina veranderd of netwerk: melden, doorgaan
        rec["status"] = f"{type(exc).__name__}: {exc}"[:200]
        rec["photo_urls"] = []
    files = []
    for i, url in enumerate(rec["photo_urls"]):
        dest = FOTOS / f"{iid}_{i:02d}.jpg"
        if not dest.exists():
            wait(1.5)
            try:
                r = session.get(url, timeout=20)
                if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/"):
                    dest.write_bytes(r.content)
                else:
                    continue
            except Exception:
                continue
        files.append(dest.name)
    rec["photos"] = files
    done[iid] = rec
    out_path.write_text(json.dumps(done, indent=1, ensure_ascii=False))
    print(f"{n}/{len(items)} {iid} {rec['status']} {len(files)} foto's", flush=True)
print("KLAAR")
