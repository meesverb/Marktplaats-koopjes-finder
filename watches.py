"""Sporthorloges: dezelfde flipberekening als de fietscomputers, op de
Garmin-horloges uit reference_sport_watches.csv. Bedoeld om te zien of dit
een tweede markt is, voordat er een tab in het dashboard komt.

    python watches.py                    # per model de markt, dan de flips
    python watches.py --db koopjes.db --flips 25

Leest koopjes.db (alleen lezen), gevuld door de zoekopdracht `sporthorloges`
in schedule.json (nachtronde). Alleen advertenties uit de categorieën
sporthorloges en smartwatches: daar staan de horloges zelf. Bandjes en kabels
staan in telefoon- en wearable-categorieën ("garmin fenix", 28-09-2026: 359
in sporthorloges, 111 in smartwatches, de rest verspreid over 33 activity
trackers, 19 telefoontoebehoren, ...).

Rekent zoals de tab Flips (computers.apply_computer_signals()): de
vergelijkingsprijzen zijn vraagprijzen van hetzelfde model uit die twee
categorieën, verwachte verkoopprijs = mediaan × negotiation_factor, min
costs_eur, allemaal uit computer_scoring.json. Dat is dezelfde heuristiek
(0,875), geen meting voor horloges. Varianten delen een rij in het
referentiebestand (5/5S, Solar, Sapphire, Music): de mediaan mengt ze, en een
winst op een basismodel tegen een mediaan met Sapphire-uitvoeringen is te
hoog. Kijk dus naar de titel.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence

import computers as pc
import dashboard

HERE = Path(__file__).resolve().parent
CATALOG_PATH = HERE / "reference_sport_watches.csv"
# De categoriesleutels zoals ze in de advertentie-URL staan
# (/v/<hoofdcategorie>/<categorie>/<id>-...), zelfde als --category.
CATEGORIES = ("sporthorloges", "smartwatches")
# Drempels voor de samenvatting "is dit een markt": hoeveel flips er zijn
# boven deze winst.
PROFIT_STEPS = (0, 25, 50)


@lru_cache(maxsize=None)
def _catalog(path: str) -> tuple:
    return tuple(pc.load_catalog(Path(path)))


def load_watches(db_path, config: Optional[dict] = None, catalog: Optional[Sequence] = None):
    """(advertenties met `.computer` gezet, nieuwste waarneming of None). De
    signalen heten `.computer` omdat ze uit computers.py komen; de functiescore
    en de upgrade t.o.v. de eigen Roam zeggen voor een horloge niets en blijven
    leeg of worden genegeerd."""
    config = config or pc.default_config()
    catalog = catalog if catalog is not None else _catalog(str(CATALOG_PATH))
    listings, newest, _ = dashboard.load_active_listings(db_path, CATEGORIES, config["dashboard"])
    pc.apply_computer_signals(listings, db_path=db_path, catalog=catalog, config=config,
                              comp_categories=CATEGORIES)
    return listings, newest


def model_resale(db_path, config: Optional[dict] = None, catalog: Optional[Sequence] = None) -> dict[str, float]:
    """{modellabel: verwachte verkoopprijs} over alle vergelijkingsprijzen van
    het model, met dezelfde regels als de flipwinst. Per advertentie rekent
    apply_computer_signals() zonder die advertentie zelf; voor de tabel per
    model is dat niet de bedoeling."""
    config = config or pc.default_config()
    catalog = catalog if catalog is not None else _catalog(str(CATALOG_PATH))
    flip = config["flip"]
    comps = pc.db_comparables(db_path, catalog, flip["comp_window_days"], CATEGORIES)
    return {label: pc._resale_band(list(prices.values()), flip["negotiation_factor"])[1]
            for label, prices in comps.items() if len(prices) >= flip["min_comps"]}


def _available(listing) -> bool:
    return not listing.reserved


def market_rows(listings) -> list[tuple[str, int, int, Optional[float]]]:
    """Per model: (label, horloges actief, met vraagprijs, mediaan vraagprijs),
    meeste advertenties eerst."""
    by_model: dict[str, list] = {}
    for listing in pc.active_computers(listings):
        by_model.setdefault(listing.computer.model.label, []).append(listing)
    rows = []
    for label, items in by_model.items():
        asking = [l.price_eur for l in items if l.price_eur is not None and l.price_is_asking and not l.reserved]
        rows.append((label, len(items), len(asking), statistics.median(asking) if asking else None))
    return sorted(rows, key=lambda r: (-r[1], r[0]))


def flips(listings) -> list:
    """Horloges met winst, niet gereserveerd, grootste winst eerst."""
    return [l for l in pc.flips(listings) if l.computer.profit_eur > 0 and _available(l)]


def main(argv: Optional[list[str]] = None) -> int:
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
        listings, newest = load_watches(args.db)
    except (OSError, pc.CatalogError) as exc:
        print(f"Kan {CATALOG_PATH.name} niet lezen: {exc}", file=sys.stderr)
        return 1
    if newest is None:
        print(f"Geen advertenties uit {' of '.join(CATEGORIES)} in {args.db}. "
              "Staat de zoekopdracht sporthorloges in schedule.json en heeft de nachtronde gedraaid?")
        return 0

    import sleepers  # price_text()

    known = pc.active_computers(listings)
    excluded = pc.filtered_out(listings)
    unknown = len(listings) - len(known) - len(excluded)
    print(f"Sporthorloges in {args.db}, stand {newest.isoformat(timespec='minutes')}: "
          f"{len(listings)} actief, {len(known)} met bekend model, {len(excluded)} uitgefilterd "
          f"(bandjes, defect, gezocht), {unknown} model niet in {CATALOG_PATH.name}.")

    print(f"\n{'Model':<22} {'Actief':>6} {'Prijs':>6} {'Mediaan':>8}  Verwachte verkoop")
    resale = model_resale(args.db)
    for label, count, priced, median in market_rows(listings):
        sale = pc._euro(resale.get(label)) if label in resale else "te weinig vergelijkingsmateriaal"
        print(f"{label[:22]:<22} {count:>6} {priced:>6} {pc._euro(median):>8}  {sale}")

    found = flips(listings)
    steps = ", ".join(f"{sum(1 for l in found if l.computer.profit_eur > step)} boven €{step}"
                      for step in PROFIT_STEPS)
    print(f"\nFlips (winst = verwachte verkoopprijs − prijs − verzendkosten): {steps}.")
    for l in found[:args.flips]:
        c = l.computer
        print(f"  {pc._signed(c.profit_eur):>5} ({pc._euro(c.profit_low_eur)} tot {pc._euro(c.profit_high_eur)}) "
              f"{sleepers.price_text(l)[:22]:<22} {c.model.label[:20]:<20} (n={c.comp_count}) {l.title[:50]}")
        print(f"        {l.url}")
    bids = [l for l in pc.open_bids(listings) if _available(l)]
    if bids:
        print(f"\nZonder prijs, bied maximaal (quitte bij de lage verkoopschatting): {len(bids)}")
        for l in bids[:args.flips]:
            print(f"  {pc._euro(l.computer.max_bid_eur):>6}  {l.computer.model.label[:20]:<20} {l.title[:50]}")
    print("\nLet op: de 0,875 is dezelfde heuristiek als bij de fietscomputers, geen meting; varianten "
          "(S/X, Solar, Sapphire, Music) delen een rij, dus de mediaan mengt ze.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
