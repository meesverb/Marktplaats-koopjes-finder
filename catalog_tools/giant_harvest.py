"""Harvest Giant NL road bikes: model year, EUR price and specs.

Sources (all giant-bicycles.com NL, EUR):
  - Wayback captures of old-style model pages  /nl-nl/bikes/model/<slug>/<id>/<id>/   (~2010-2016)
  - Wayback captures of new-style model pages  /nl/<slug>[-<year>]                    (~2016-2025)
  - Wayback captures of series overview pages  /nl/bikes-<series>[-<year>]  (tiles: name, year, price)
  - Live archive pages /nl/<slug>-<year> (specs only, no price)
Output: giant_pages.json (one record per parsed page/tile).
"""
import json, re, html, os, sys
import wb

ROAD = re.compile(r"(?i)(^|/)(tcr|defy|propel|scr|trinity|tcx|ocr|contend|avail|envie|langma|fcr)")
NOT_ROAD = re.compile(r"(?i)eplus|e\+|road-e|fastroad|escape|attend|entour|explore|toughroad|revolt|anyroad|frame(set)?\b|geometry|zoom")
OUT = "giant_pages.json"


def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def spec_table(h):
    specs = []
    for k, v in re.findall(r"<th>([^<]{1,40})</th>\s*<td>(.*?)</td>", h, re.S):
        specs.append([clean(k), clean(v)])
    if not specs:  # minified new-style: <tr><th>Label<td>value
        for k, v in re.findall(r"<tr><th>([^<]{1,40})<td>(.*?)(?=<tr>|</tbody>|</table>)", h, re.S):
            specs.append([clean(k), clean(v)])
    if not specs:  # live archive: <div class=label>..</div><div class=value>..</div>
        for k, v in re.findall(r"<div class=label>([^<]{1,40})</div><div class=value>(.*?)</div>", h, re.S):
            specs.append([clean(k), clean(v)])
    return [s for s in specs if s[0] and s[1] and s[0] not in ("Prijs",)]


def eur(s):
    m = re.search(r"€\s*([\d.]+)(?:,(\d\d|-))?", s)
    if not m:
        return None
    return float(m.group(1).replace(".", ""))


def parse_model(h):
    rec = {}
    t = re.search(r"<title>(.*?)</title>", h, re.S)
    title = clean(t.group(1)) if t else ""
    rec["title"] = title
    y = re.search(r"class=\"?modelyear[^>]*>\s*(20\d\d)", h) or re.search(r"\((20\d\d)\)", title)
    rec["year"] = int(y.group(1)) if y else None
    n = re.search(r'<h1 class="ridelife[^"]*">(.*?)</h1>', h, re.S) or re.search(r"<h1>(.*?)</h1>", h, re.S)
    rec["name"] = clean(n.group(1)) if n else re.sub(r"\s*\(20\d\d\).*", "", title).strip()
    price = None
    m = re.search(r'product:price:amount content="\s*([\d.]+)"', h)
    cur = re.search(r"product:price:currency content=\"?(\w+)", h)
    if m:
        price = float(m.group(1))
        rec["currency"] = cur.group(1) if cur else None
    else:
        m = re.search(r'<h2 class="price ?[^"]*">(.*?)</h2>', h, re.S) or re.search(r"<div class=price><p>([^<]*)", h)
        if m:
            price = eur(clean(m.group(1)))
            rec["currency"] = "EUR" if price else None
    rec["price"] = price
    # A struck-through original price means the shown price is a sale price.
    old = re.search(r"class=\"?(?:oldprice|price-old|original-price)[^>]*>([^<]*€[^<]*)<", h)
    rec["old_price"] = eur(old.group(1)) if old else None
    rec["specs"] = spec_table(h)
    return rec


def parse_tiles(h):
    out = []
    # new style (2019+): <h3>Name</h3><h4>2020</h4><p class=prices><span class=price>€ 2.499</span>
    for name, yr, price in re.findall(r"<h3>([^<]+)</h3><h4>(20\d\d)</h4><p class=prices>(.*?)</div>", h, re.S):
        out.append({"name": clean(name), "year": int(yr), "price": eur(clean(price)), "tile_price_text": clean(price)})
    return out


def load():
    try:
        return json.load(open(OUT))
    except Exception:
        return {}


def save(d):
    json.dump(d, open(OUT, "w"), ensure_ascii=False)


def lines(path):
    out = []
    for l in open(path):
        p = l.split()
        if len(p) == 2:
            out.append(p)
    return out


def main():
    done = load()
    jobs = []
    # old style model pages
    for f in ("cdx_giant-bicycles.com_nl-nl_bikes_model__.txt", "cdx_giant-bicycles.com_nl-nl_bikes_road__.txt"):
        for ts, url in lines(f):
            path = url.split("giant-bicycles.com", 1)[1].split("?")[0].lower()
            if "/model/" not in path and not re.search(r"/bikes/road/\d+/\d+/?$", path):
                continue
            slug = path.split("/model/")[1] if "/model/" in path else path
            if "/model/" in path and not ROAD.search(slug):
                continue
            if NOT_ROAD.search(path):
                continue
            jobs.append(("model", ts, url))
    # new style model pages: every year a capture exists
    seen = set()
    for fam in ("tcr", "defy", "propel", "contend", "trinity"):
        for ts, url in lines(f"cdx_giant-bicycles.com_nl_{fam}_.txt"):
            base = url.split("?")[0]
            if base in seen or NOT_ROAD.search(base.split("/nl/")[1]):
                continue
            seen.add(base)
            if re.search(r"-20\d\d$", base):
                jobs.append(("model", ts, base))
            else:
                for r in wb.cdx(base.split("://", 1)[1], fl="timestamp,original", collapse="timestamp:4"):
                    jobs.append(("model", r["timestamp"], r["original"]))
    # series pages: tiles with name/year/price
    for ts, url in lines("cdx_giant-bicycles.com_nl_bikes-_.txt"):
        base = url.split("?")[0]
        s = base.split("/nl/")[1]
        if not ROAD.search(s.replace("bikes-", "")) or NOT_ROAD.search(s.replace("bikes-", "")):
            continue
        if re.search(r"-20\d\d$", base):
            jobs.append(("series", ts, base))
        else:
            for r in wb.cdx(base.split("://", 1)[1], fl="timestamp,original", collapse="timestamp:4"):
                jobs.append(("series", r["timestamp"], r["original"]))
    print("jobs", len(jobs), flush=True)
    for i, (kind, ts, url) in enumerate(jobs):
        key = f"{ts}|{url}"
        if key in done:
            continue
        h = wb.wb(ts, url)
        if not h:
            done[key] = {"kind": kind, "error": "fetch"}
            continue
        wburl = f"https://web.archive.org/web/{ts}/{url}"
        if kind == "model":
            rec = parse_model(h)
            rec.update(kind="model", ts=ts, url=url, source_url=wburl)
            # new-style pages also carry the series tiles
            rec["tiles"] = parse_tiles(h)
            done[key] = rec
        else:
            done[key] = {"kind": "series", "ts": ts, "url": url, "source_url": wburl, "tiles": parse_tiles(h)}
        if i % 20 == 0:
            save(done)
            print(i, len(done), kind, url, flush=True)
    save(done)
    print("done", len(done))


if __name__ == "__main__":
    main()
