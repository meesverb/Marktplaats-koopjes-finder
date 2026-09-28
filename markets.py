"""De markten met een eigen dashboard: fietscomputers en sporthorloges.

Beide rekenen met dezelfde flipberekening (computers.apply_computer_signals())
en dezelfde instellingen (computer_scoring.json: afdingfactor, verzendkosten,
vergelijkingsperiode). Wat verschilt, staat hier: in welke
Marktplaats-categorieën ze staan, welk referentiebestand de modellen kent, hoe
een titel zonder bekend model wordt ingedeeld, welk HTML-bestand het dashboard
wordt en welke tabbladen erbij horen. Upgrades (t.o.v. de eigen Roam) en
Vinted horen alleen bij de fietscomputers.

De sleutel (`key`) staat ook bij de eigen aan- en verkopen (trade.market,
migratie 10), zodat Mijn flips per dashboard alleen de eigen markt toont.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import computers as pc
import watches


@dataclass(frozen=True)
class Market:
    key: str  # in trade.market en in --markt
    title: str  # kop van het dashboard
    short: str  # tabbladtitel, links
    item: str  # enkelvoud: "computer", "horloge"
    items: str  # meervoud
    categories: tuple  # categoriesleutels uit de advertentie-URL
    # Waar de vergelijkingsprijzen vandaan mogen komen. None: overal behalve
    # een fietscategorie (zo rekenen de fietscomputers al sinds het begin).
    comp_categories: Optional[tuple]
    catalog_path: Path
    dashboard_file: str  # standaardbestand van `python dashboard.py --markt ...`
    serve_path: str  # waar `python dashboard.py --serve` het toont
    classify_unknown: Callable[[str, str], tuple]
    has_upgrades: bool
    has_vinted: bool
    has_score: bool  # functiescore uit computer_scoring.json
    example_title: str  # voorbeeld bij "Zelf toevoegen"

    def catalog(self) -> tuple:
        return _catalog(str(self.catalog_path))

    def labels(self) -> set:
        return {m.label for m in self.catalog()}


@lru_cache(maxsize=None)
def _catalog(path: str) -> tuple:
    return tuple(pc.load_catalog(Path(path)))


COMPUTERS = Market(
    key="fietscomputers",
    title="Fietscomputers op Marktplaats",
    short="Fietscomputers",
    item="computer",
    items="computers",
    categories=("fietsaccessoires-fietscomputers",),
    comp_categories=None,
    catalog_path=pc.CATALOG_PATH,
    dashboard_file="dashboard.html",
    serve_path="/",
    classify_unknown=pc.classify_unknown,
    has_upgrades=True,
    has_vinted=True,
    has_score=True,
    example_title="bijv. Wahoo Roam, vlek rechtsonder",
)

WATCHES = Market(
    key="sporthorloges",
    title="Sporthorloges op Marktplaats",
    short="Sporthorloges",
    item="horloge",
    items="horloges",
    categories=watches.CATEGORIES,
    comp_categories=watches.CATEGORIES,
    catalog_path=watches.CATALOG_PATH,
    dashboard_file="dashboard_horloges.html",
    serve_path="/horloges",
    classify_unknown=watches.classify_unknown,
    has_upgrades=False,
    has_vinted=False,
    has_score=False,
    example_title="bijv. Garmin Fenix 6 Pro, kras op de bezel",
)

MARKETS = {m.key: m for m in (COMPUTERS, WATCHES)}


def by_key(key: Optional[str]) -> Market:
    """De markt bij een sleutel; onbekend of leeg is de fietscomputermarkt,
    de enige die er was vóór migratie 10."""
    return MARKETS.get(key or "", COMPUTERS)


def trade_market(trade) -> Market:
    """Bij welke markt een eigen aankoop hoort. Rijen van vóór migratie 10
    hebben geen markt; die horen bij het model, en zonder model bij de
    fietscomputers."""
    if getattr(trade, "market", None):
        return by_key(trade.market)
    for market in MARKETS.values():
        if trade.model and trade.model in market.labels():
            return market
    return COMPUTERS


def for_search(filters: dict) -> Optional[Market]:
    """De markt van een zoekopdracht uit schedule.json, aan de categorie; of
    None als die bij geen dashboard hoort."""
    wanted = {c.strip() for c in str(filters.get("category") or "").split(",") if c.strip()}
    for market in MARKETS.values():
        if wanted & set(market.categories):
            return market
    return None
