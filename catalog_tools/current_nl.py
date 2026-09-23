"""Step 2c: Cube and Sensa road bikes on sale in the Netherlands today.

Neither site states a model year on the product page, so these rows get a
seen_date (today) instead. Output: cube_current.json, sensa_current.json
"""
import html, json, re
import wb

CUBE_SERIES = ["road/road-race/agree", "road/road-race/attain", "road/road-race/litening",
               "road/cyclocross/cross-race", "road/triathlon-time-trial/aerium", "gravel/nuroad"]


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def cube_specs(h):
    x = wb.text(h)
    # Dutch spec block: lowercase label line followed by its value line
    labels = ["frame", "maat", "starre vork", "achterderailleur", "remmen", "voorderailleur", "trapaslagers", "cranks",
              "cassette", "ketting", "balhoofdlagers", "stuurpen", "stuur", "stuurlint", "zadelpen", "zadel",
              "wielset", "voorwiel", "achterwiel", "banden", "voorband", "achterband", "gewicht", "schakel-/remgreep",
              "shifters", "naaf voor", "naaf achter", "velgen"]
    lines = [l.strip() for l in x.split("\n") if l.strip()]
    specs, seen = [], set()
    for a, b in zip(lines, lines[1:]):
        if a.lower() in labels and a.lower() not in seen and b.lower() not in labels and len(b) < 300:
            specs.append([a, b])
            seen.add(a.lower())
    return specs


def cube():
    items = {}
    for s in CUBE_SERIES:
        for p in range(1, 6):
            u = f"https://www.cube.eu/nl-nl/bikes/{s}?p={p}"
            h = wb.get(u, delay=1.0) or ""
            found = re.findall(r'"item_name":"([^"]+)","item_id":"(\d+)","price":([\d.]+)', h)
            new = [f for f in found if f[1] not in items]
            for name, iid, price in found:
                name = json.loads(f'"{name}"')
                link = re.search(r'href="(https://www.cube.eu/nl-nl/[a-z0-9\-]+/' + iid + r')"', h)
                items.setdefault(iid, {"name": name, "id": iid, "price": float(price), "series": s, "listing_url": u,
                                       "url": link.group(1) if link else None})
            if not new:
                break
    for it in items.values():
        if it["url"]:
            h = wb.get(it["url"], delay=1.0)
            it["specs"] = cube_specs(h) if h else []
    json.dump(items, open("cube_current.json", "w"), ensure_ascii=False, indent=0)
    print("cube", len(items))


def sensa():
    out = {}
    for listing in ("https://www.sensabikes.com/fietsen/racefietsen/",):
        h = wb.get(listing) or ""
        for u, title in re.findall(r'<a href="(https://www.sensabikes.com/[^"]+)"\s+class="product-name"\s+title="([^"]+)"', h):
            if u in out:
                continue
            p = wb.get(u, delay=1.0) or ""
            m = re.search(r'<meta property="product:price:amount" content="([\d.]+)"', p) or \
                re.search(r"€\s*([\d.]+,\d\d)", wb.text(p))
            price = None
            if m:
                v = m.group(1)
                price = float(v.replace(".", "").replace(",", ".")) if "," in v else float(v)
            specs = [[clean(k), clean(v)] for k, v in re.findall(
                r'<th class="properties-label">(.*?)</th>\s*<td class="properties-value">(.*?)</td>', p, re.S)]
            out[u] = {"name": html.unescape(title), "url": u, "price": price, "specs": specs, "listing_url": listing}
    json.dump(out, open("sensa_current.json", "w"), ensure_ascii=False, indent=0)
    print("sensa", len(out))


if __name__ == "__main__":
    cube()
    sensa()
