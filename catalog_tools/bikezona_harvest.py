"""bikezona.com catalogue: road bikes (tipo=1) of Cube/Giant/Trek per model year.

Spanish catalogue, prices in EUR (Spanish market list price). Output: bikezona.json
"""
import json, re, html
import wb

BRANDS = {"Cube": 776, "Giant": 94, "Trek": 221, "Specialized": 204, "Cannondale": 3, "Scott": 194, "Canyon": 832,
          "BMC": 829, "Bianchi": 49, "Merida": 138, "Orbea": 155, "Ridley": 854, "Cervélo": 833, "Pinarello": 343,
          "Focus": 840, "Lapierre": 504, "Rose": 471, "Stevens": 558, "KTM": 430, "Koga": 503, "Felt": 608,
          "Wilier": 235, "Colnago": 242, "De Rosa": 462, "Kuota": 277, "Time": 344, "BH": 257, "Fuji": 472,
          "GT": 22, "Btwin": 828}
OUT = "bikezona.json"


def fix(s):
    # requests decodes these UTF-8 pages as latin-1 (no charset header)
    try:
        return s.encode("latin-1").decode("utf-8")
    except Exception:
        return s


def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def parse_bike(h):
    h = fix(h)
    x = wb.text(h)
    rec = {}
    t = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S)
    rec["h1"] = clean(t.group(1)) if t else ""
    m = re.search(r"([A-Z0-9][^\n]*?)\s*\((20\d\d)\)", x)
    if m:
        rec["name"], rec["year"] = m.group(1).strip(), int(m.group(2))
    m = re.search(r"Precio:\s*([\d.]+)\s*€", x)
    rec["price"] = float(m.group(1).replace(".", "")) if m else None
    m = re.search(r"Peso:\s*([\d,\.]+)\s*kg", x)
    rec["weight"] = m.group(1) if m else None
    specs = []
    i = x.find("Montaje de la bicicleta")
    j = x.find("La revista digital")
    for line in x[i:j].split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            if k.strip() and v.strip() and len(k) < 30:
                specs.append([k.strip(), v.strip()])
    rec["specs"] = specs
    return rec


def main():
    try:
        out = json.load(open(OUT))
    except Exception:
        out = {}
    links = {}
    for brand, bid in BRANDS.items():
        for year in range(2010, 2025):
            for pag in range(1, 30):
                u = f"https://www.bikezona.com/bicicletas/todobici-busqueda.asp?marca={bid}&anio={year}&tipo=1&pag={pag}"
                h = wb.get(u, delay=1.5) or ""
                # only this brand's bikes: the sidebars link to other bikes on every page,
                # which would otherwise look like new results forever
                slug = re.sub(r"[^a-z0-9]+", "-", brand.lower().replace("é", "e")).strip("-")
                found = re.findall(r'href="(https://www.bikezona.com/bicicletas/' + slug + r'-[a-z0-9\-]+/\d+)"', h)
                new = [f for f in dict.fromkeys(found) if f not in links]
                for f in new:
                    links[f] = (brand, year)
                if not new:
                    break
            print(brand, year, len(links), flush=True)
    for n, (u, (brand, year)) in enumerate(links.items()):
        if u in out:
            continue
        h = wb.get(u, delay=1.5)
        if not h:
            out[u] = {"error": "fetch"}
            continue
        rec = parse_bike(h)
        rec.update(brand=brand, search_year=year, url=u)
        out[u] = rec
        if n % 25 == 0:
            json.dump(out, open(OUT, "w"), ensure_ascii=False)
            print(n, rec.get("name"), rec.get("year"), rec.get("price"), flush=True)
    json.dump(out, open(OUT, "w"), ensure_ascii=False)
    print("done", len(out))


if __name__ == "__main__":
    main()
