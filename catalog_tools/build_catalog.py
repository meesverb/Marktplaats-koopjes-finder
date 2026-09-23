"""Merge the harvested sources into reference_bike_catalog.csv.

Every row keeps the page it came from. Derived columns (frame material,
groupset, brake type, speeds) are read from that page's own spec text and left
empty when the text does not say; nothing is filled in from memory.
"""
import csv, json, re, sys, datetime
from collections import defaultdict

TODAY = datetime.date.today().isoformat()
COLUMNS = ["brand", "model", "model_year", "seen_date", "category", "frame_material", "groupset", "electronic",
           "speeds", "brake_type", "weight_kg", "new_price", "currency", "market", "price_basis", "specs",
           "source_url", "spec_source_url"]

GROUPSETS = [
    ("Shimano Dura-Ace", r"dura[\s-]?ace"), ("Shimano Ultegra", r"ultegra"), ("Shimano 105", r"\b105\b"),
    ("Shimano Tiagra", r"tiagra"), ("Shimano Sora", r"\bsora\b"), ("Shimano Claris", r"claris"),
    ("Shimano GRX", r"\bgrx\b"), ("Shimano Cues", r"\bcues\b"), ("Shimano 2300", r"\b2300\b"),
    ("Shimano Tourney", r"tourney"),
    ("SRAM Red", r"sram\s+red|\bred\s+(?:etap|axs|22)\b"), ("SRAM Force", r"sram\s+force|\bforce\s+(?:etap|axs|22|1)\b"),
    ("SRAM Rival", r"sram\s+rival|\brival\s+(?:etap|axs|22|1)\b"), ("SRAM Apex", r"sram\s+apex|\bapex\b"),
    ("Campagnolo Super Record", r"super\s*record"), ("Campagnolo Record", r"campagnolo\s+record|\brecord\s+(?:eps|12|11)\b"),
    ("Campagnolo Chorus", r"chorus"), ("Campagnolo Potenza", r"potenza"), ("Campagnolo Athena", r"athena"),
    ("Campagnolo Centaur", r"centaur"), ("Campagnolo Veloce", r"veloce"), ("Campagnolo Ekar", r"\bekar\b"),
    ("FSA K-Force WE", r"k-force we"),
]
DRIVE_KEYS = ("rear derailleur", "achterderailleur", "derailleur", "shifters", "schakel", "group", "cambio",
              "schaltwerk", "mandos", "shortspecreardderailleur", "specreardderailleur", "specshifters")


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def spec_text(specs):
    return "; ".join(f"{k}: {v}" for k, v in specs if v)


def pick(specs, *keys):
    out = []
    for k, v in specs:
        kl = k.lower()
        if any(key in kl for key in keys):
            out.append(v)
    return " | ".join(out)


def groupset(specs):
    # Derailleur/shifters first, then crank/cassette/brakes, then anything: a
    # "Shimano 105 hub" on an Ultegra bike must not decide the groupset.
    tiers = [
        pick(specs, "achterderailleur", "rear derailleur", "reardera", "shifters", "shifter", "group", "cambio",
             "schaltwerk", "mandos", "schalt", "voorderailleur", "desviador"),
        pick(specs, "crank", "kurbel", "bielas", "cassette", "kassette", "piñón", "rem", "brake", "bremse",
             "freno"),
        spec_text(specs),
    ]
    for text in tiers:
        for name, pat in GROUPSETS:
            if text and re.search(pat, text, re.I):
                return name
    return ""


def electronic(specs):
    t = pick(specs, "derailleur", "shifter", "group", "cambio", "schalt", "mandos", "reardera")
    return "ja" if re.search(r"di2|etap|\baxs\b|\beps\b", t, re.I) else ""


def speeds(specs):
    t = spec_text(specs)
    m = re.search(r"\b(\d{1,2})[-\s]?(?:speed|speeds|sp\b|s\b|v\b|velocidades|fach|versnellingen|-gang)", t, re.I)
    if m and 7 <= int(m.group(1)) <= 13:
        return m.group(1)
    m = re.search(r"\b[12]x(\d{1,2})\b", t, re.I)
    if m and 7 <= int(m.group(1)) <= 13:
        return m.group(1)
    m = re.search(r"\b(\d{2})\s*versnellingen", t, re.I)  # "22 versnellingen" = 2x11
    if m and int(m.group(1)) in (16, 18, 20, 22, 24):
        return str(int(m.group(1)) // 2)
    return ""


def brake(specs):
    # Sensa lists the brakes inside the groupset line ("... 105 hydraulic disc brakes")
    line = pick(specs, "remmen", "rem ", "remsysteem", "remset", "brake", "freno", "bremse", "bremsanlage", "groepset", "group")
    if re.search(r"disc|schijf|disco|scheibe|hydraul|hidr[aá]ulic|hydr\.", line, re.I):
        return "schijfrem"
    # rim brakes only from the brake line itself: elsewhere "velg" is the wheel's rim
    if re.search(r"caliper|dual[\s-]?pivot|velgrem|direct mount|\brim\b|felgen|herradura|v-brake|cantilever", line, re.I):
        return "velgrem"
    # the brake line only names the model; a frame or fork built for disc mounts settles it
    if re.search(r"disc|schijf", pick(specs, "frame", "vork", "fork", "rahmen", "gabel", "cuadro", "horquilla"), re.I):
        return "schijfrem"
    return ""


def material(specs):
    t = pick(specs, "frame", "rahmen", "cuadro") or ""
    t = t.split("|")[0]
    if re.search(r"carbon|composite|oclv|c:6|c:5|hpc|gtc|\bcarbono\b", t, re.I):
        return "carbon"
    if re.search(r"alu|aluxx|alloy|alpha|6061|7005|6066|superlite|aleaci[oó]n", t, re.I):
        return "aluminium"
    if re.search(r"titan", t, re.I):
        return "titanium"
    if re.search(r"steel|staal|stahl|acero|cromo|chromoly|columbus|reynolds", t, re.I):
        return "staal"
    return ""


def weight(specs, extra=None):
    t = extra or pick(specs, "gewicht", "weight", "peso")
    m = re.search(r"(\d{1,2}[.,]\d{1,2})\s*kg", t or "", re.I)
    if not m and extra:
        m = re.search(r"(\d{1,2}[.,]\d{1,2})", extra)
    return m.group(1).replace(",", ".") if m else ""


def row(brand, model, year, specs, price, currency, market, basis, src, spec_src="", seen="", category="",
        weight_text=None):
    return {
        "brand": brand, "model": model.strip(), "model_year": year or "", "seen_date": seen, "category": category,
        "frame_material": material(specs), "groupset": groupset(specs), "electronic": electronic(specs),
        "speeds": speeds(specs),
        # "Disc" in the model name is the manufacturer saying so; it beats a spec list that doesn't mention it
        "brake_type": "schijfrem" if re.search(r"(?i)\bdisc\b", model) else brake(specs), "weight_kg": weight(specs, weight_text),
        "new_price": (f"{price:.2f}" if price else ""), "currency": currency if price else "",
        "market": market if price else "", "price_basis": basis if price else "",
        "specs": spec_text(specs), "source_url": src, "spec_source_url": spec_src if spec_src != src else "",
    }


def wb_date(ts):
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"


# --------------------------------------------------------------------- Giant
GIANT_ROAD = re.compile(r"(?i)^(tcr|defy|propel|scr|trinity|tcx|ocr|contend|avail)\b")
GIANT_SKIP = re.compile(r"(?i)frame|\bFF\b|e\+|eplus|road-e")


def giant_rows():
    pages = json.load(open("giant_pages.json"))
    live = json.load(open("giant_live.json"))
    current = json.load(open("giant_current.json"))
    live_by = {(norm(v["name"]), v["year"]): v for v in live.values() if v.get("year")}
    best = {}  # (model, year) -> candidate; the earliest capture wins, later ones may show a sale price

    def offer(name, year, price, src, ts, specs, spec_src, basis):
        if not name or not year or not GIANT_ROAD.match(name) or GIANT_SKIP.search(name):
            return
        k = (norm(name), year)
        c = best.get(k)
        if c is None or (price and not c["price"]) or (price and c["price"] and ts < c["ts"]):
            prev_specs = c["specs"] if c else []
            best[k] = dict(name=name, year=year, price=price, src=src, ts=ts, specs=specs or prev_specs,
                           spec_src=spec_src if specs else (c["spec_src"] if c else ""), basis=basis)
        elif specs and not c["specs"]:
            c["specs"], c["spec_src"] = specs, spec_src

    for v in pages.values():
        if v.get("kind") == "model" and v.get("price") and (v.get("currency") in (None, "EUR")):
            offer(v["name"], v.get("year"), v["price"], v["source_url"], v["ts"], v.get("specs"), v["source_url"],
                  f"adviesprijs giant-bicycles.com/nl, archief {wb_date(v['ts'])}")
        for t in v.get("tiles", []):
            if v.get("source_url") and t.get("price"):
                offer(t["name"], t["year"], t["price"], v["source_url"], v["ts"], None, "",
                      f"prijs in serie-overzicht giant-bicycles.com/nl, archief {wb_date(v['ts'])}")
    for v in current.values():
        if not v.get("year") or not v.get("price"):
            continue
        price = v["price"]
        reg = v.get("regular_price")
        note = f"prijs giant-bicycles.com/nl op {TODAY}"
        if reg and price < reg <= 2 * price:
            price, note = reg, f"reguliere prijs giant-bicycles.com/nl op {TODAY} (webshopkorting niet meegeteld)"
        offer(v["name"], v["year"], price, v["url"], "99999999", v.get("specs"), v["url"], note)
    # live archive pages add specs where the capture had none, and models without any price
    for (n, y), v in live_by.items():
        k = (n, y)
        if k in best:
            if not best[k]["specs"] and v["specs"]:
                best[k]["specs"], best[k]["spec_src"] = v["specs"], v["url"]
        else:
            offer(v["name"], y, None, v["url"], "99999999", v["specs"], v["url"], "")
    out = []
    for c in best.values():
        out.append(row("Giant", c["name"], c["year"], c["specs"], c["price"], "EUR", "NL", c["basis"], c["src"],
                       c["spec_src"]))
    return out


# ---------------------------------------------------------------------- Trek
TREK_LABELS = {
    "specFrame": "Frame", "specFork": "Vork", "specFrameFit": "Framefit", "specWheels": "Wielen", "specTires": "Banden",
    "specShifters": "Shifters", "specFrontDerailleur": "Voorderailleur", "specRearDerailleur": "Achterderailleur",
    "specCrank": "Crankstel", "specBottomBracket": "Trapas", "specCassette": "Cassette", "specChain": "Ketting",
    "specBrakeset": "Remmen", "specHandlebar": "Stuur", "specStem": "Stuurpen", "specSaddle": "Zadel",
    "specSeatpost": "Zadelpen", "specSizes": "Maten", "specColors": "Kleuren", "specWeight": "Gewicht",
    "specGears": "Versnellingen",
}
TREK_SKIP = re.compile(r"(?i)frameset|frame set|\+|zektor|\bion\b|project one|^fx\b|^verve|^dual sport")


def trek_rows():
    arch = json.load(open("trek_archive.json"))
    api = json.load(open("trek_api.json"))
    try:
        html_specs = json.load(open("trek_specs.json"))
    except Exception:
        html_specs = {}
    try:
        wbk = json.load(open("trek_wayback.json"))
    except Exception:
        wbk = {}
    listing = json.load(open("trek_current_listing.json"))
    # price observations per product id: (date, price, source)
    obs = defaultdict(list)
    by_name_year = {}
    for v in wbk.values():
        if v.get("kind") == "listing":
            for it in v.get("items", []):
                obs[it["id"]].append((v["ts"], it["price"], v["source_url"]))
        elif v.get("kind") == "product" and v.get("price") and v.get("name"):
            m = re.search(r"/p/\d+-(20\d\d)", v["url"])
            if m:
                by_name_year.setdefault((norm(v["name"]), int(m.group(1))), (v["ts"], v["price"], v["source_url"]))
    rows = []
    ids_years = defaultdict(list)
    for r in arch:
        ids_years[r["id"]].append(r["year"])
    seen = set()
    for r in arch:
        pid, year, name = r["id"], r["year"], r["displayName"]
        if TREK_SKIP.search(name) or (pid, year) in seen:
            continue
        seen.add((pid, year))
        a = api.get(pid) or {}
        specs = [[TREK_LABELS[k], v] for k, v in (a.get("specs") or {}).items() if k in TREK_LABELS]
        spec_src = a.get("api_url", "")
        if not specs:
            hs = html_specs.get(f"{year}|{pid}") or {}
            specs = hs.get("specs") or []
            spec_src = hs.get("url", "")
        page = "https://www.trekbikes.com/nl/nl_NL" + r["productUrl"].replace("/p/", "/a/")
        price = src = basis = None
        # Trek launches model year X in the summer of X-1, so only a capture from
        # July X-1 to June X is that year's price; a later one can already be X+1's
        # for a product id that runs on, and an earlier one is X-1's.
        win = [(ts, p, s) for ts, p, s in obs.get(pid, []) if f"{year - 1}07" <= ts[:6] <= f"{year}06"]
        if win:
            ts, price, src = min(win)
            basis = f"prijs in overzicht trekbikes.com/nl, archief {wb_date(ts)}"
        elif (norm(name), year) in by_name_year:
            ts, price, src = by_name_year[(norm(name), year)]
            basis = f"prijs op productpagina trekbikes.com/nl, archief {wb_date(ts)}"
        elif pid in listing and year >= 2025 and a.get("price"):
            price = a.get("wasPrice") if (a.get("wasPrice") or 0) > (a.get("price") or 0) else a.get("price")
            src, basis = page.replace("/a/", "/p/"), f"prijs trekbikes.com/nl op {TODAY}"
        rows.append(row("Trek", name, year, specs, price, "EUR", "NL", basis, src or page, spec_src or page,
                        category=r["productUrl"].split("/")[3] if r["productUrl"].startswith("/fietsen/") else ""))
    # current bikes that are not in the archive list
    for pid, v in listing.items():
        if pid in ids_years or TREK_SKIP.search(v["name"]):
            continue
        a = api.get(pid) or {}
        specs = [[TREK_LABELS[k], x] for k, x in (a.get("specs") or {}).items() if k in TREK_LABELS]
        yr = (a.get("marketingModelYear") or "")[-4:]
        price = a.get("wasPrice") if (a.get("wasPrice") or 0) > (a.get("price") or 0) else (a.get("price") or v["price"])
        url = "https://www.trekbikes.com/nl/nl_NL" + (a.get("url") or "")
        rows.append(row("Trek", v["name"], int(yr) if yr.isdigit() else "", specs, price, "EUR", "NL",
                        f"prijs trekbikes.com/nl op {TODAY}", url if a.get("url") else v["listing_url"],
                        a.get("api_url", ""), seen=TODAY))
    return rows


# --------------------------------------------------------------------- Sensa
def sensa_rows():
    try:
        d = json.load(open("sensa.json"))
    except Exception:
        return []
    best = {}
    for v in d.values():
        if not v.get("name") or v.get("error"):
            continue
        k = (norm(v["name"]), v["price"])
        if k not in best or v["ts"] < best[k]["ts"]:
            best[k] = v
    out = []
    for v in best.values():
        if re.search(r"(?i)custom|frame|junior|prima|\b2[04]\b", v["name"]):
            continue  # custom-configurator pages have no fixed build; kids' bikes are out of scope
        out.append(row("Sensa", v["name"], "", v["specs"], v["price"], "EUR", "NL",
                       f"prijs sensabikes.com, archief {wb_date(v['ts'])} (geen modeljaar op de pagina)",
                       v["source_url"], seen=wb_date(v["ts"])))
    return out


# ------------------------------------------------ Cube / Sensa, on sale today
def cube_model(name):
    name = re.sub(r"(?i)^cube\s+", "", name).strip()
    # the colour is the last word, written like "blackpearl´n´switchwhite" or "glacier´n´black"
    return re.sub(r"\s+\S*(?:´n´|'n'|`n`|’n’)\S*$", "", name).strip()


def current_rows():
    out = []
    try:
        cube = json.load(open("cube_current.json"))
    except Exception:
        cube = {}
    seen = set()
    for v in cube.values():
        model = cube_model(v["name"])
        if not v.get("price") or (model.lower(), v["price"]) in seen or re.search(r"(?i)frame|hybrid", model):
            continue
        seen.add((model.lower(), v["price"]))
        out.append(row("Cube", model, "", v.get("specs") or [], v["price"], "EUR", "NL",
                       f"prijs cube.eu/nl-nl op {TODAY}", v.get("url") or v["listing_url"], seen=TODAY,
                       category=v["series"].split("/")[1]))
    try:
        sensa = json.load(open("sensa_current.json"))
    except Exception:
        sensa = {}
    for v in sensa.values():
        specs = v.get("specs") or []
        keys = [k for k, _ in specs]
        if "Frame" in keys:
            specs = specs[keys.index("Frame"):]  # the rows before "Frame" are marketing bullets, not specs
        if not v.get("price") or re.search(r"(?i)custom|frame", v["name"]):
            continue
        if any(k == "Groepset" and "configureer" in x.lower() for k, x in specs):
            continue  # a configurator starting price, not a bike with a fixed build
        specs = [list(p) for p in dict.fromkeys(tuple(p) for p in specs)]  # the page lists the table twice
        out.append(row("Sensa", v["name"], "", specs, v["price"], "EUR", "NL",
                       f"prijs sensabikes.com op {TODAY} (geen modeljaar op de pagina)", v["url"], seen=TODAY))
    return out


# ------------------------------------------------------------------ bikezona
BZ_SKIP = re.compile(r"(?i)\bFF\b|\bframe|cuadro|kit\b|e-?bike|\bebike|\+|electri|turbo|junior|\bkids?\b")


def bikezona_rows(have):
    try:
        d = json.load(open("bikezona.json"))
    except Exception:
        return []
    out = []
    for v in d.values():
        if v.get("error") or not v.get("name") or not v.get("year"):
            continue
        brand = v["brand"]
        name = re.sub(r"(?i)^" + re.escape(brand) + r"\s+", "", v["name"]).strip()
        name = re.sub(r"(?i)^cervelo\s+", "", name)
        if BZ_SKIP.search(name):
            continue
        if (brand.lower(), norm(name), v["year"]) in have:
            continue  # the brand's own Dutch page already covers this bike
        out.append(row(brand, name, v["year"], v.get("specs") or [], v.get("price"), "EUR", "ES",
                       "catalogusprijs bikezona.com (Spaanse markt)", v["url"], weight_text=v.get("weight")))
    return out


def main(path):
    rows = giant_rows() + trek_rows() + sensa_rows() + current_rows()
    # the Spanish catalogue only adds a row where the brand's own Dutch page gave no price
    have = {(r["brand"].lower(), norm(r["model"]), r["model_year"]) for r in rows if r["new_price"]}
    rows += bikezona_rows(have)
    # several product ids can carry the same bike (colour, UK/NL variant); keep the fullest row
    uniq = {}
    for r in rows:
        k = (r["brand"], r["model"].lower(), str(r["model_year"]), r["seen_date"], r["market"], r["new_price"])
        if k not in uniq or len(r["specs"]) > len(uniq[k]["specs"]):
            uniq[k] = r
    rows = list(uniq.values())
    rows.sort(key=lambda r: (r["brand"].lower(), str(r["model_year"]), r["model"].lower()))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print(len(rows), "rows")
    print(Counter(r["brand"] for r in rows).most_common())
    print("with price:", sum(1 for r in rows if r["new_price"]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "catalog_preview.csv")
