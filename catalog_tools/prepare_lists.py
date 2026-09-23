"""Step 1: collect the URL/id lists the harvesters work from.

Writes, in the working directory:
  cdx_giant-bicycles.com_*.txt   Wayback captures of Giant NL pages
  giant_tiles.json               Giant NL archive (/nl/archive?keyword=...) tiles
  trek_archive.json              Trek NL archived road bikes per model year
  trek_current_listing.json      Trek NL road bikes on sale today, with price
  trek_current_ids.json
  sensa_road.txt                 Wayback captures of sensabikes.com/bikes/road/*
"""
import json, re
import wb

GIANT_CDX = ["giant-bicycles.com/nl/tcr*", "giant-bicycles.com/nl/defy*", "giant-bicycles.com/nl/propel*",
             "giant-bicycles.com/nl/contend*", "giant-bicycles.com/nl/trinity*", "giant-bicycles.com/nl/scr*",
             "giant-bicycles.com/nl/bikes-*", "giant-bicycles.com/nl-nl/bikes/model/*",
             "giant-bicycles.com/nl-nl/bikes/road/*"]
GIANT_KEYWORDS = ["tcr", "defy", "propel", "contend", "trinity", "tcx", "advanced", "advanced sl", "advanced pro",
                  "composite", "aluxx", "disc", "frameset", "road", "racefiets", "tcr advanced", "defy advanced",
                  "propel advanced", "contend sl", "contend ar", "defy 2", "liv"]
TREK_ROAD = re.compile(r"(?i)^(madone|domane|[ée]monda|[12]\.\d|lexa|silque|speed concept|cronus|boone|crockett|"
                       r"crossrip|checkpoint|checkmate|alpha|pilot|equinox)")


def cdx_to_file(pattern):
    name = "cdx_" + pattern.replace("/", "_").replace("*", "_") + ".txt"
    with open(name, "w") as f:
        for r in wb.cdx(pattern, fl="timestamp,original", collapse="urlkey", limit=20000):
            f.write(f"{r['timestamp']} {r['original']}\n")


def giant():
    for p in GIANT_CDX:
        cdx_to_file(p)
    tiles = {}
    pat = re.compile(r'<div class="tile [^"]*?\bbike-summary ([^"]*)" data-pricemin=(\d+) data-pricemax=(\d+) '
                     r'id=(\d+)[^>]*>.*?<a href=(/nl/[^ >]+).*?<div class=h3>([^<]+)</div><div class=h4>(\d{4})</div>',
                     re.S)
    for kw in GIANT_KEYWORDS:
        h = wb.get("https://www.giant-bicycles.com/nl/archive?keyword=" + kw.replace(" ", "+")) or ""
        for cls, _, _, id_, href, name, yr in pat.findall(h):
            tiles[href] = dict(cls=cls, id=id_, href=href, name=name.strip(), year=yr)
    json.dump(tiles, open("giant_tiles.json", "w"), indent=0)


def trek():
    out = []
    for y in range(2010, 2028):
        t = wb.get(f"https://www.trekbikes.com/nl/nl_NL/product/archived?modelYear={y}&type=Bikes")
        try:
            results = json.loads(t)["data"]["results"]
        except Exception:
            continue
        for r in results:
            u, n = r["productUrl"], r["displayName"]
            road = ("/racefietsen/" in u and "kinderen" not in u) or ("/c/" in u and TREK_ROAD.match(n))
            if road and "elektrisch" not in u:
                r["year"] = y
                out.append(r)
    json.dump(out, open("trek_archive.json", "w"), indent=0)
    seen = {}
    for page in range(0, 20):
        u = f"https://www.trekbikes.com/nl/nl_NL/fietsen/racefietsen/c/B200/?pageSize=72&page={page}&q=%3Arelevance"
        h = wb.get(u) or ""
        imp = re.findall(r'"id":\s*"(\d+)",\s*"name":\s*"([^"]+)",\s*"price":\s*"([\d.]+)"', h)
        new = [i for i in imp if i[0] not in seen]
        for i, n, p in imp:
            seen[i] = {"name": n, "price": float(p), "listing_url": u}
        if not new:
            break
    json.dump(seen, open("trek_current_listing.json", "w"), ensure_ascii=False, indent=0)
    json.dump(sorted(seen), open("trek_current_ids.json", "w"))


def sensa():
    with open("sensa_road.txt", "w") as f:
        for r in wb.cdx("sensabikes.com/bikes/road*", fl="timestamp,original", collapse="urlkey", limit=5000):
            f.write(f"{r['timestamp']} {r['original']}\n")


if __name__ == "__main__":
    giant()
    trek()
    sensa()
