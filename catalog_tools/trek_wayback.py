"""Historic Trek NL prices from the Wayback Machine.

- listing pages (…/fietsen/racefietsen/…/c/…): dataLayer impressions {id, name, price} in EUR
- product pages 2015-2017 (…/p/<id>): server-rendered "€ 1.999,00"
Output: trek_wayback.json {capture_key: {...}}
"""
import json, re, html
import wb

OUT = "trek_wayback.json"


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def impressions(h):
    return [
        {"id": i, "name": html.unescape(n), "price": float(p)}
        for i, n, p in re.findall(r'"id":\s*"(\d+)",\s*"name":\s*"([^"]+)",\s*"price":\s*"([\d.]+)"', h)
    ]


def product_price(h):
    # 2015-2017 server-rendered product page: the dataLayer 'detail' block names it
    m = re.search(r"'name':\s*'([^']+)',[^}]*?'price':\s*'(€\s*[\d.]+,\d\d)'", h, re.S)
    if m:
        p = float(m.group(2).replace("€", "").strip().replace(".", "").replace(",", "."))
        return html.unescape(m.group(1)), p, None
    m = re.search(r'<h1[^>]*>(.*?)</h1>', h, re.S)
    name = clean(m.group(1)) if m else None
    m = re.search(r'class="[^"]*(?:actual-price|price-current|pdp-price|price)[^"]*"[^>]*>\s*(€\s*[\d.]+,\d\d)', h)
    if not m:
        m = re.search(r'(€\s*[\d.]+,\d\d)', h)
    price = float(m.group(1).replace("€", "").strip().replace(".", "").replace(",", ".")) if m else None
    was = re.search(r'class="[^"]*(?:was-price|price-was|strike|old-price)[^"]*"[^>]*>\s*(€\s*[\d.]+,\d\d)', h)
    return name, price, (was.group(1) if was else None)


def main():
    try:
        out = json.load(open(OUT))
    except Exception:
        out = {}
    rows = wb.cdx("trekbikes.com/nl/nl_NL/fietsen/racefietsen/", matchType="prefix", fl="timestamp,original", limit=50000)
    print("captures", len(rows), flush=True)
    # one capture per URL per month is plenty
    seen, jobs = set(), []
    for r in rows:
        u = r["original"].split("#")[0]
        base = re.sub(r"\?.*", "", u)
        key = (base, r["timestamp"][:6])
        if key in seen:
            continue
        seen.add(key)
        kind = "product" if "/p/" in base else "listing"
        if kind == "product" and r["timestamp"][:4] > "2018":
            continue  # client-rendered price from 2019 on
        jobs.append((kind, r["timestamp"], u))
    print("jobs", len(jobs), flush=True)
    for n, (kind, ts, u) in enumerate(jobs):
        k = f"{ts}|{u}"
        if k in out:
            continue
        h = wb.wb(ts, u)
        if not h:
            out[k] = {"error": "fetch"}
            continue
        src = f"https://web.archive.org/web/{ts}/{u}"
        if kind == "listing":
            out[k] = {"kind": kind, "ts": ts, "url": u, "source_url": src, "items": impressions(h)}
        else:
            name, price, was = product_price(h)
            out[k] = {"kind": kind, "ts": ts, "url": u, "source_url": src, "name": name, "price": price, "was": was,
                      "impressions": impressions(h)}
        if n % 20 == 0:
            json.dump(out, open(OUT, "w"), ensure_ascii=False)
            print(n, kind, u[-70:], flush=True)
    json.dump(out, open(OUT, "w"), ensure_ascii=False)
    print("done", len(out))


if __name__ == "__main__":
    main()
