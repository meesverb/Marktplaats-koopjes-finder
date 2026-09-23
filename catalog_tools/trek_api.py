"""Trek NL product API: specs, marketing model year and (for current bikes) EUR price."""
import json, re, sys
import wb

OUT = "trek_api.json"
BASE = "https://www.trekbikes.com/nl/nl_NL/v1/api/product/{id}/full/"


def fetch(pid):
    for suffix in ("", "?type=archive"):
        t = wb.get(BASE.format(id=pid) + suffix, delay=1.0, tries=3)
        if not t:
            continue
        try:
            d = json.loads(t).get("data") or {}
        except ValueError:
            continue
        if d.get("name"):
            return d, BASE.format(id=pid) + suffix
    return None, None


def slim(d):
    specs = {k: v for k, v in (d.get("specs") or {}).items() if isinstance(v, str) and v}
    prices = d.get("prices") or {}
    cp = (prices.get("consumerPrice") or {})
    price = ((cp.get("price") or {}).get("low") or {}).get("value")
    was = (((cp.get("wasPrice") or {}).get("low")) or {}).get("value")
    return {
        "code": d.get("code"), "name": d.get("name"), "category": d.get("defaultCategory"),
        "url": d.get("url"), "marketingModelYear": d.get("marketingModelYear"),
        "modelYearIntroAndCurrent": d.get("modelYearIntroAndCurrent"), "isArchived": d.get("isArchived"),
        "price": price, "wasPrice": was, "specs": specs,
    }


def main():
    ids = sys.argv[1:]
    if not ids:
        ids = sorted({r["id"] for r in json.load(open("trek_archive.json"))})
        try:
            ids += [i for i in json.load(open("trek_current_ids.json")) if i not in ids]
        except Exception:
            pass
    try:
        out = json.load(open(OUT))
    except Exception:
        out = {}
    for n, pid in enumerate(ids):
        if pid in out:
            continue
        d, src = fetch(pid)
        out[pid] = dict(slim(d), api_url=src) if d else {"error": "fetch"}
        if n % 25 == 0:
            json.dump(out, open(OUT, "w"), ensure_ascii=False)
            print(n, pid, out[pid].get("name"), out[pid].get("marketingModelYear"), out[pid].get("price"), flush=True)
    json.dump(out, open(OUT, "w"), ensure_ascii=False)
    print("done", len(out))


if __name__ == "__main__":
    main()
