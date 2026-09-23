"""Sensa road bikes from Wayback captures of sensabikes.com/bikes/road/<id>/<slug>.

The pages carry name, EUR price and a spec list, but no model year: the capture
date is recorded instead (seen_date), never turned into a model year.
"""
import json, re
import wb

OUT = "sensa.json"
LABELS = ["frame", "front fork", "group", "groupset", "wheels", "tires", "seatpost", "handlebar", "stem", "saddle",
          "front hub", "rear hub", "weight", "available sizes", "available colors", "brakes", "crankset", "cassette"]


def parse(h):
    x = wb.text(h)
    rec = {}
    t = re.search(r"<title[^>]*>(.*?)</title>", h, re.S | re.I)
    rec["title"] = re.sub(r"\s+", " ", t.group(1)).strip() if t else x.split("\n")[0].strip()
    rec["name"] = rec["title"].split("|")[0].strip()
    m = re.search(r"Article successfully added\.\s*\n\s*([^\n]+)", x)
    if m:
        rec["name"] = m.group(1).strip()
    m = re.search(re.escape(rec["name"]) + r"\s*\n\s*(?:Configure[\s\S]{0,400}?)?€\s?([\d,]+\.\d\d)", x)
    if not m:
        m = re.search(r"€\s?([\d,]+\.\d\d)", x)
    rec["price"] = float(m.group(1).replace(",", "")) if m else None
    i = x.find("03. Specs", x.find("03. Specs") + 1)
    if i < 0:
        i = x.find("03. Specs")
    j = x.find("04. Tech lab", i)
    lines = [l.strip() for l in x[i:j].split("\n") if l.strip()]
    specs = []
    for a, b in zip(lines, lines[1:]):
        if a.lower() in LABELS and b.lower() not in LABELS:
            specs.append([a, b.lstrip("* ").strip()])
    rec["specs"] = specs
    return rec


def main():
    try:
        out = json.load(open(OUT))
    except Exception:
        out = {}
    rows = [l.split() for l in open("sensa_road.txt") if len(l.split()) == 2]
    jobs = {}
    for ts, u in rows:
        base = u.split("?")[0]
        m = re.search(r"/bikes/road/(\d+)/([a-z0-9\-]+)$", base)
        if not m or m.group(2) == "gtm.js":
            continue
        # first capture of each product page; later captures can show a changed price
        jobs.setdefault(base, ts)
    print("jobs", len(jobs), flush=True)
    for n, (u, ts) in enumerate(sorted(jobs.items())):
        if u in out:
            continue
        h = wb.wb(ts, u)
        if not h:
            out[u] = {"error": "fetch"}
            continue
        rec = parse(h)
        rec.update(url=u, ts=ts, source_url=f"https://web.archive.org/web/{ts}/{u}")
        out[u] = rec
        if n % 20 == 0:
            json.dump(out, open(OUT, "w"), ensure_ascii=False)
            print(n, rec["name"], rec["price"], len(rec["specs"]), flush=True)
    json.dump(out, open(OUT, "w"), ensure_ascii=False)
    print("done", len(out))


if __name__ == "__main__":
    main()
