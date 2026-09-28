"""Sporthorloges: de tweede markt naast de fietscomputers, met dezelfde
flipberekening op de Garmin-horloges uit reference_sport_watches.csv.

    python watches.py                    # per model de markt, dan de flips (console)
    python dashboard.py --markt sporthorloges --open    # het dashboard

Gevuld door de zoekopdracht `sporthorloges` in schedule.json: "garmin" in de
categorieën sporthorloges, smartwatches en activity-trackers. Daar staan de
horloges zelf; bandjes en kabels staan grotendeels in telefoon- en
wearable-categorieën ("garmin", 28-09-2026: 991 in sporthorloges, 620 in
smartwatches, 129 in activity-trackers, 614 in autonavigatie, ...). In
activity-trackers staan ook Fenixen en Forerunners die de verkoper daar
neerzette: juist die zijn interessant.

Rekent zoals de fietscomputers (computers.apply_computer_signals()): de
vergelijkingsprijzen zijn vraagprijzen van hetzelfde model uit deze
categorieën, verwachte verkoopprijs = mediaan × negotiation_factor, min
costs_eur, allemaal uit computer_scoring.json. Varianten delen een rij in het
referentiebestand (5/5S, Solar, Sapphire, Music, 43/47/51 mm): de mediaan
mengt ze, en een winst op een basismodel tegen een mediaan met
Sapphire-uitvoeringen valt te hoog uit. Kijk dus naar de titel.

Dit bestand kent de horloges: de categorieën en wat een titel zonder bekend
model is (classify_unknown()). Het dashboard zelf staat in dashboard.py, de
markten naast elkaar in markets.py.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

import computers as pc

HERE = Path(__file__).resolve().parent
CATALOG_PATH = HERE / "reference_sport_watches.csv"
# De categoriesleutels zoals ze in de advertentie-URL staan
# (/v/<hoofdcategorie>/<categorie>/<id>-...), dezelfde als --category.
CATEGORIES = ("sporthorloges", "smartwatches", "activity-trackers")
# Drempels voor de samenvatting in de console: hoeveel flips boven deze winst.
PROFIT_STEPS = (0, 25, 50)

# --- Titels zonder bekend model ------------------------------------------------
#
# Uit de volledige crawl van 28-09-2026 (1707 advertenties, 444 zonder model
# uit het referentiebestand): vooral losse bandjes ("Garmin QuickFit 22 Watch
# Band", "25122d Originele Garmin Quickfit horlogeband"), laadkabels, andere
# merken die Garmin in de tekst noemen ("Apple watch 10 ... ivm aanschaf
# garmin") en Garmin-modellen zonder bron in het referentiebestand (Tactix,
# Quatix, Approach S70). Een titel als "Te koop Garmin horloge" of "Garmin
# smartwatch - Werkt naar behoren" is een horloge met onbekend model: die
# blijven zichtbaar in Alle horloges, want juist daar kan een slaper tussen
# zitten.

# Bandjes en dergelijke die het accessoirewoord van computers.py niet heeft.
WATCH_ACCESSORY_RE = re.compile(
    r"\b(?:quick\s?fit|quick\s?release|ultrafit|pluggen|laadclip|veerstaaf\w*|screen\s?protector"
    r"|beschermglas|glasplaatje|horlogeband\w*|polsband\w*|bandje\w*|straps?|\w*kabel|\w*lader|oplaad\w*"
    r"|clip|mount|houder\w*|lege\s+doos)\b",
    re.I,
)
# Andere merken. Staat er geen "Garmin" in de titel, dan is het ook geen
# Garmin-horloge met een onbekend model.
OTHER_BRAND_RE = re.compile(
    r"\b(?:apple|iwatch|samsung|galaxy|fitbit|oura|huawei|amazfit|xiaomi|mi\s?band|polar|suunto|coros"
    r"|withings|fossil|pebble|gard\s?pro|festina|tomtom|casio|g-?shock|honor|oneplus|pixel\s?watch"
    r"|whoop|wahoo|circular|tag\s?heuer|seiko|swatch)\b",
    re.I,
)
# Garmin-producten die geen horloge zijn maar in deze categorieën belanden.
NOT_A_WATCH_RE = re.compile(
    r"\b(?:index|slaapmonitor|sleep\s?monitor|hrm[-\s]?\w*|hartslagband|edge|varia|inreach|foretrex"
    r"|etrex|gpsmap|dash\s?cam|zumo|dezl|nuvi|drive\w*|echomap|livescope|approach\s?z\d+|fietshouder"
    r"|stuurhouder|bike\s?mount|weegschaal)\b",
    re.I,
)
WATCH_WORD_RE = re.compile(r"\b(?:\w*horloge\w*|smartwatch\w*|watch|tracker|activity\s?tracker)\b", re.I)
GARMIN_RE = re.compile(r"\bgarmin\b", re.I)
# "Horlogebandje voor GARMIN (22mm)", "nieuw voor garmin": gemaakt vóór een
# Garmin, dus geen Garmin.
FOR_GARMIN_RE = re.compile(r"\b(?:voor|for|geschikt\s+voor|compatible\s+with|past\s+op)\s+(?:een\s+)?garmin\b", re.I)


def classify_unknown(title: str, description: str = "") -> tuple[str, str]:
    """(soort, reden) voor een titel zonder bekend model. "horloge" betekent:
    een Garmin-horloge waarvan het model niet in het referentiebestand staat
    (of niet in de titel), zichtbaar in Alle horloges zonder winst; al het
    andere is uitgefilterd, met de reden."""
    title = title or ""
    for kind, regex, label in (("gevraagd", pc.WANTED_RE, "zoekadvertentie"),
                               ("defect", pc.REPAIR_RE, "reparatie of defect"),
                               ("onderdeel", pc.PART_RE, "los onderdeel")):
        found = regex.search(title)
        if found:
            return kind, f"{label} ('{found.group(0)}')"
    aimed = FOR_GARMIN_RE.search(title)
    if aimed:
        return "accessoire", f"'{aimed.group(0)}'"
    other = OTHER_BRAND_RE.search(title)
    if other and not GARMIN_RE.search(title[: other.start()]):
        return "overig", f"ander merk ('{other.group(0)}')"
    not_watch = NOT_A_WATCH_RE.search(title)
    if not_watch:
        return "overig", f"geen horloge ('{not_watch.group(0)}')"
    word = WATCH_ACCESSORY_RE.search(title) or pc.ACCESSORY_WORD_RE.search(title)
    if word:
        device = WATCH_WORD_RE.search(title[: word.start()])
        if not (device and pc.BUNDLE_RE.search(title[device.end(): word.start()])):
            return "accessoire", f"'{word.group(0)}' zonder bekend model"
    if GARMIN_RE.search(title) or WATCH_WORD_RE.search(title):
        if not GARMIN_RE.search(title):
            return "overig", "horloge zonder merk of model in de titel"
        return "horloge", "model onbekend"
    return "overig", "geen Garmin-horloge in de titel"


# --- Console ------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    import dashboard  # hier, want dashboard.py leest markets.py en dat leest dit bestand
    import markets
    import sleepers  # price_text()

    parser = argparse.ArgumentParser(
        description="Sporthorloges (Garmin) uit koopjes.db: markt per model en flips, "
                    "met dezelfde berekening als de fietscomputers."
    )
    parser.add_argument("--db", default="koopjes.db")
    parser.add_argument("--flips", type=int, default=20, help="hoeveel flips tonen (standaard 20)")
    args = parser.parse_args(argv)

    if not Path(args.db).exists():
        print(f"{args.db} bestaat niet. Draai eerst de nachtronde (python koopjes.py run nacht) "
              "of de zoekopdracht sporthorloges.", file=sys.stderr)
        return 1
    try:
        d = dashboard.load_dashboard(args.db, market=markets.WATCHES)
    except (OSError, pc.CatalogError) as exc:
        print(f"Kan {CATALOG_PATH.name} niet lezen: {exc}", file=sys.stderr)
        return 1
    if not d.listings:
        print(f"Geen advertenties uit {', '.join(CATEGORIES)} in {args.db}. "
              "Staat de zoekopdracht sporthorloges in schedule.json en heeft de nachtronde gedraaid?")
        return 0

    print(f"Sporthorloges in {args.db}, laatste ronde {dashboard.local_time(d.newest_seen)}: "
          f"{len(d.listings)} actief, {len(d.items)} met bekend model, {len(d.unknown_items)} model onbekend, "
          f"{len(d.excluded)} uitgefilterd (bandjes, andere merken, defect, gezocht).")
    resale = dashboard.model_resale(d)
    print(f"\n{'Model':<24} {'Actief':>6} {'Mediaan':>8}  Verwachte verkoop")
    for label, items, median in dashboard.market_rows(d):
        sale = pc._euro(resale.get(label)) if label in resale else "te weinig vergelijkingsmateriaal"
        print(f"{label[:24]:<24} {len(items):>6} {pc._euro(median):>8}  {sale}")

    found = d.flips
    steps = ", ".join(f"{sum(1 for l in found if l.computer.profit_eur > step)} boven €{step}"
                      for step in PROFIT_STEPS)
    print(f"\nFlips (winst = verwachte verkoopprijs − prijs − verzendkosten): {steps}.")
    for l in found[:args.flips]:
        c = l.computer
        print(f"  {pc._signed(c.profit_eur):>5} ({pc._euro(c.profit_low_eur)} tot {pc._euro(c.profit_high_eur)}) "
              f"{sleepers.price_text(l)[:22]:<22} {c.model.label[:22]:<22} (n={c.comp_count}) {l.title[:50]}")
        print(f"        {l.url}")
    if d.open_bids:
        print(f"\nZonder prijs, bied maximaal (quitte bij de lage verkoopschatting): {len(d.open_bids)}")
        for l in d.open_bids[:args.flips]:
            print(f"  {pc._euro(l.computer.max_bid_eur):>6}  {l.computer.model.label[:22]:<22} {l.title[:50]}")
    print("\nLet op: de 0,875 is dezelfde heuristiek als bij de fietscomputers, geen meting; varianten "
          "(S/X, Solar, Sapphire, Music) delen een rij, dus de mediaan mengt ze.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
