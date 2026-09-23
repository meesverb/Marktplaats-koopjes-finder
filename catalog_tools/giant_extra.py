"""Step 2b: Giant pages that are not in the Wayback Machine.

- giant_live.json:    live archive pages (/nl/<model>-<year>) — specs, no price
- giant_current.json: the current NL line-up — specs and today's price. Where the
  site shows a webshop discount, the "Reguliere prijs" is kept alongside.
"""
import json, re
import wb
import giant_harvest as g


def live_archive():
    tiles = json.load(open("giant_tiles.json"))
    out = {}
    for href, t in tiles.items():
        cls = t["cls"].split()
        if not (("surface-road-bikes" in cls or "on-road" in cls) and "surface-e-bikes" not in cls):
            continue
        u = "https://www.giant-bicycles.com" + href
        h = wb.get(u, delay=0.8)
        if h:
            r = g.parse_model(h)
            r.update(url=u, cls=t["cls"])
            out[href] = r
    json.dump(out, open("giant_live.json", "w"), ensure_ascii=False)


def current():
    h = wb.get("https://www.giant-bicycles.com/nl/fietsen/racefietsen") or ""
    series = sorted(set(re.findall(r'href="?(/nl/bikes-[a-z0-9\-]+)', h)))
    models = set()
    for s in series:
        if re.search(r"frame|eplus|e-plus", s):
            continue
        hs = wb.get("https://www.giant-bicycles.com" + s, delay=0.8) or ""
        models.update(l for l in re.findall(r'href="?(/nl/[a-z0-9\-]+-20\d\d)\b', hs) if "bikes-" not in l)
    out = {}
    for m in sorted(models):
        if re.search(r"frame|eplus", m):
            continue
        hm = wb.get("https://www.giant-bicycles.com" + m, delay=0.8)
        if not hm:
            continue
        r = g.parse_model(hm)
        reg = re.search(r"Reguliere prijs:\s*€\s*([\d.]+)", wb.text(hm))
        r["regular_price"] = float(reg.group(1).replace(".", "")) if reg else None
        r["url"] = "https://www.giant-bicycles.com" + m
        out[m] = r
    json.dump(out, open("giant_current.json", "w"), ensure_ascii=False)


if __name__ == "__main__":
    live_archive()
    current()
