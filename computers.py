"""Fietscomputers: welk model staat er te koop, wat kan het, en is het een
upgrade of een koopje om door te verkopen.

Twee maten, bewust apart (de eigenaar koos "beide, apart getoond"):

- **Upgrade**: de functiescore (0-100) van het model min die van de eigen
  Wahoo ELEMNT ROAM v1, en wat dat per €100 kost. Alleen wat het apparaat kan
  telt mee, niet de prijs.
- **Flipmarge**: wat andere advertenties voor hetzelfde model vragen (mediaan,
  maal de onderhandelingsfactor) min wat deze kost. Alleen als er genoeg
  vergelijkingsmateriaal is.

Geen van beide is `Listing.deal_score` of de waardescore; ze staan in een
eigen tab. De modelgegevens komen uit `reference_bike_computers.csv` (één rij
per model, met bron); de gewichten uit `computer_scoring.json`.

Alleen de titel wordt tegen de patronen gehouden. Een fiets "met Garmin Edge
530" is geen computer die te koop staat — daarvoor is `has_computer` in de
spec-extractie.
"""
from __future__ import annotations

import argparse
import csv
import html as html_lib
import json
import re
import sqlite3
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
CATALOG_PATH = HERE / "reference_bike_computers.csv"
CONFIG_PATH = HERE / "computer_scoring.json"

# Wat een veld mag bevatten. Leeg = niet nagezocht. Een andere waarde is een
# tikfout in de CSV en stopt het inlezen met een melding, in plaats van
# stilletjes als "onbekend" te scoren.
VOCABULARY = {
    "bediening": {"knoppen", "touch+knoppen", "touch"},
    "gps": {"ja", "nee", "via_telefoon"},
    "kaarten": {"routeerbaar", "los_te_koop", "basiskaart", "nee"},
    "route_sync": {"ja", "nee"},
    "rerouting": {"ja", "via_telefoon", "nee"},
    "planning_op_apparaat": {"volledig", "beperkt", "nee"},
    "ant_plus": {"ja", "nee"},
    "bluetooth_sensoren": {"ja", "nee"},
    "wifi": {"ja", "nee"},
    "schakel_integratie": {"ja", "nee"},
    "workouts": {"ja", "nee"},
    "klimfunctie": {"ja", "nee"},
    "ondersteund": {"ja", "beperkt", "nee"},
}
NUMERIC = ("introductiejaar", "nieuwprijs_eur", "schermgrootte_inch", "batterijduur_uur", "gewicht_g")

# --- Wat staat er te koop? ---------------------------------------------------
#
# Een titel met een modelnaam is nog geen computer. In de volledige crawl van
# de categorie (28-09-2026, 361 advertenties) stonden er ook houders, hoesjes,
# losse schermen, reparatiediensten en zoekadvertenties tussen, allemaal met
# "Garmin Edge 1030" of "Wahoo Roam" in de titel. classify_title() deelt elke
# titel in één soort in, met de reden erbij; alleen `computer` telt mee voor
# flips, upgrades en vergelijkingsprijzen. De rest is zichtbaar in de tab
# Uitgefilterd, zodat je kunt nakijken dat er geen echte computer bij zit.
#
# Het patroon uit die crawl: een echte computer noemt een apparaatwoord
# ("fietscomputer", "GPS", "navigatie") of een koppelwoord ("met", "incl.",
# "+", "&") vóór de houder of hoes — "Garmin Edge 530 + stuurmount",
# "Garmin Edge Explore fietscomputer met houder en doos". Een los accessoire
# heeft het accessoirewoord vóór de modelnaam ("Hoesje voor Garmin 1000",
# "K-Edge ... Bolt ... mount") of er direct achter zonder koppelwoord
# ("Hammerhead Karoo 3 houder nieuw", "Wahoo Roam I stuurhouder"). Dat
# laatste geval is `twijfel`: de prijs beslist (apply_computer_signals()).

KINDS_EXCLUDED = ("accessoire", "onderdeel", "defect", "gevraagd", "e-bike")

# Staat een van deze woorden vóór de modelnaam, dan gaat de titel over een
# fiets (of een trainer) die toevallig een computer noemt: "Racefiets Cube +
# Garmin Edge 130 Plus". Erna is het een omschrijving van de computer zelf:
# "Garmin Edge 800 fiets Navigatie", "Garmin Edge 130 MTB fietscomputer".
# \b houdt "fietscomputer" erbuiten.
NOT_A_COMPUTER_RE = re.compile(
    r"\b(?:racefiets\w*|fiets|fietsen|mountainbike|mtb|gravel\s?bike|gravelfiets|e-?bike"
    r"|tijdritfiets|kickr|trainer|fietstrainer)\b",
    re.I,
)
# "ik zoek een kapotte garmin edge 1030" (zelfde crawl): iemand die koopt.
WANTED_RE = re.compile(r"\b(?:zoek|zoeke|gezocht|gevraagd|wanted|wie\s+heeft)\b", re.I)
# Een reparatiedienst ("Garmin Edge 830 scherm vervangen") of een defect
# toestel: de prijs zegt niets over wat een werkend exemplaar opbrengt.
REPAIR_RE = re.compile(
    r"\b(?:scherm\s?vervang\w*|reparatie\w*|repar(?:eer|eren)\w*|defect\w*|kapot\w*"
    r"|voor\s+onderdelen|werkt\s+niet|(?:accu|batterij)\s?vervang\w*)\b",
    re.I,
)
# Losse onderdelen ("Garmin LCD scherm Edge 830", "Karoo 2 custom color kit",
# "veiligheidskoord voor Roam"). Waar ook in de titel: nooit een hele computer.
PART_RE = re.compile(
    r"\b(?:lcd|colou?r\s?kit|kleur\s?kit|\w*koor[dt]|tether|onderdel\w*|reserveonderdel\w*)\b",
    re.I,
)
# Accessoires die ook los verkocht worden. \w* vooraan, want Marktplaats-
# verkopers plakken: "fietscomputerhouder", "stuurmount", "siliconenhoes".
# Geen "doos": "nieuw in doos" is een staat, geen los artikel; alleen
# "doosje" en "lege doos" zijn dat.
ACCESSORY_WORD_RE = re.compile(
    r"\b\w*(?:houders?|mounts?|beugel|steun|hoesjes?|hoes|case|cover|bumper|sleeve"
    r"|folie|protector|tasje|oplaadkabel|kabel|oplader|lader|adapter"
    r"|sensors?|sensoren|hartslag\w*|borstband|tickr|doosje|verpakking|handleiding)\b"
    r"|\blege\s+doos\b",
    re.I,
)
# Merken die alleen houders maken. Vóór de modelnaam is het dus een houder.
ACCESSORY_BRAND_RE = re.compile(r"\b(?:k-?edge|rec-?mounts?|barfly|quad\s?lock|sp\s?connect)\b", re.I)
# Tussen modelnaam en accessoire: dit maakt er een bundel van.
BUNDLE_RE = re.compile(
    r"\bmet\b|\bincl\w*|\binclusief\b|\binc\b|\+|&|\ben\b|\bplus\b|\bwith\b|\band\b|,",
    re.I,
)
# Of: het apparaat wordt zelf genoemd, of de titel zegt dat het een set is.
DEVICE_RE = re.compile(
    r"\b(?:fiets)?computer\b|\bgps\b|\b(?:fiets)?navigatie\b|\bbundel\b|\bbundle\b|\bset\b"
    r"|\bcompleet\b|\bcombo\b|\bpakket\b",
    re.I,
)
# E-bike-displays en -bediening: de hele categorie fietscomputers (2800
# advertenties op 28-09-2026) begint met Bosch Nyon, Kiox en Intuvia. Ze horen
# bij een e-bike-systeem en passen niet op een racefiets.
EBIKE_RE = re.compile(
    r"\b(?:bosch|intuvia|kiox|nyon|purion|smartphone\s?hub|shimano\s+steps|steps\s+[a-z]?\d|yamaha|bafang"
    r"|brose|panasonic|giant\s+ride\s?control|ridecontrol|e-?bike\w*|ebike\w*|elektrische\s+fiets\w*)\b",
    re.I,
)
# Geen computer, wel in dezelfde categorie: radar en verlichting.
NOT_A_COMPUTER_ITEM_RE = re.compile(r"\b(?:varia|radar|rtl\s?\d+|\w*lamp|\w*licht|verlichting)\b", re.I)
# In de beschrijving: de computer zelf zit er níet bij. "Wahoo ELEMNT ROAM GPS
# Doos met nieuwe accessoires" (€200, 28-09-2026) is volgens de titel een
# computer; de beschrijving zegt "accessoires zonder de fietscomputer. Mijn
# fiets en wahoo zijn gestolen". Het enige signaal dat op de beschrijving let:
# de titel blijft verder leidend (zie de docstring bovenaan).
WITHOUT_DEVICE_RE = re.compile(
    r"\bzonder\s+(?:de\s+|het\s+|een\s+)?(?:gps-?)?(?:fiets)?(?:computer|navigatie|garmin|wahoo"
    r"|hammerhead|karoo|bryton|edge|roam|bolt)\b",
    re.I,
)
# "Houder voor ...": een accessoire, ook als er een koppelwoord tussen staat.
FOR_RE = re.compile(r"\b(?:voor|for|geschikt|past|fits|compatible)\b", re.I)


class CatalogError(ValueError):
    """Het CSV-bestand heeft een waarde die de score niet kent."""


@dataclass(frozen=True)
class ComputerModel:
    merk: str
    model: str
    pattern: re.Pattern
    fields: dict = field(hash=False, compare=False)

    @property
    def label(self) -> str:
        return f"{self.merk} {self.model}"

    def get(self, key: str) -> str:
        return (self.fields.get(key) or "").strip()

    def number(self, key: str) -> Optional[float]:
        value = self.get(key)
        return float(value) if value else None


def load_catalog(path: Path = CATALOG_PATH) -> list[ComputerModel]:
    """Alle modellen in bestandsvolgorde — die volgorde is de matchvolgorde,
    dus "Edge 1030 Plus" staat vóór "Edge 1030"."""
    models = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            where = f"{Path(path).name} regel {line} ({row.get('merk')} {row.get('model')})"
            for key, allowed in VOCABULARY.items():
                value = (row.get(key) or "").strip()
                if value and value not in allowed:
                    raise CatalogError(
                        f"{where}: {key}={value!r} is geen bekende waarde "
                        f"(mag leeg zijn of een van: {', '.join(sorted(allowed))})"
                    )
            for key in NUMERIC:
                value = (row.get(key) or "").strip()
                if value:
                    try:
                        float(value)
                    except ValueError:
                        raise CatalogError(f"{where}: {key}={value!r} is geen getal (punt als decimaalteken)") from None
            try:
                pattern = re.compile(row["pattern"], re.I)
            except (re.error, KeyError) as exc:
                raise CatalogError(f"{where}: patroon klopt niet: {exc}") from None
            models.append(ComputerModel(row["merk"].strip(), row["model"].strip(), pattern, row))
    return models


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=None)
def _default_catalog() -> tuple[ComputerModel, ...]:
    return tuple(load_catalog())


@lru_cache(maxsize=None)
def _default_config() -> str:
    # Als string gecachet: een dict is niet hashbaar en een gedeelde
    # veranderlijke config tussen aanroepen is vragen om ellende.
    return json.dumps(load_config())


def default_config() -> dict:
    return json.loads(_default_config())


@dataclass(frozen=True)
class TitleVerdict:
    model: ComputerModel
    kind: str  # computer | twijfel | accessoire | onderdeel | defect | gevraagd | fiets
    reason: str


def classify_title(title: str, catalog: Sequence[ComputerModel]) -> Optional[TitleVerdict]:
    """Welk model de titel noemt en wat voor advertentie het is, of None als
    er geen bekend model in staat. Zie het blok boven NOT_A_COMPUTER_RE."""
    title = title or ""
    for model in catalog:
        match = model.pattern.search(title)
        if match:
            break
    else:
        return None
    before, after = title[: match.start()], title[match.end():]

    def verdict(kind: str, reason: str = "") -> TitleVerdict:
        return TitleVerdict(model, kind, reason)

    if WANTED_RE.search(title):
        return verdict("gevraagd", f"zoekadvertentie ('{WANTED_RE.search(title).group(0)}')")
    if NOT_A_COMPUTER_RE.search(before):
        return verdict("fiets", f"'{NOT_A_COMPUTER_RE.search(before).group(0)}' vóór de modelnaam")
    if REPAIR_RE.search(title):
        return verdict("defect", f"reparatie of defect ('{REPAIR_RE.search(title).group(0)}')")
    if PART_RE.search(title):
        return verdict("onderdeel", f"los onderdeel ('{PART_RE.search(title).group(0)}')")

    brand = ACCESSORY_BRAND_RE.search(before)
    if brand:
        return verdict("accessoire", f"houdermerk '{brand.group(0)}' vóór de modelnaam")
    word = ACCESSORY_WORD_RE.search(before)
    if word:
        between = before[word.end():]
        if BUNDLE_RE.search(between) and not FOR_RE.search(between):
            return verdict("twijfel", f"'{word.group(0)}' vóór de modelnaam, met '+'/'en' ertussen")
        return verdict("accessoire", f"'{word.group(0)}' vóór de modelnaam")

    word = ACCESSORY_WORD_RE.search(after)
    if word:
        between = after[: word.start()]
        if BUNDLE_RE.search(between) or DEVICE_RE.search(between) or DEVICE_RE.search(after):
            return verdict("computer", f"met accessoires ('{word.group(0)}')")
        return verdict("twijfel", f"'{word.group(0)}' direct na de modelnaam")
    return verdict("computer")


def classify_unknown(title: str, description: str = "") -> tuple[str, str]:
    """(soort, reden) voor een titel zonder bekend model. "computer" betekent
    hier: model onbekend, maar het lijkt een computer (Van Rysel GPS 500,
    Sigma BC 509, "Wahoo zeer complete set!" — zelfde crawl). Die blijven
    zichtbaar, zonder score of winst; de eigenaar wilde geen computer kwijt."""
    title = title or ""
    for kind, regex in (("gevraagd", WANTED_RE), ("e-bike", EBIKE_RE), ("defect", REPAIR_RE), ("onderdeel", PART_RE)):
        found = regex.search(title)
        if found:
            label = {"gevraagd": "zoekadvertentie", "e-bike": "e-bike-display of -bediening",
                     "defect": "reparatie of defect", "onderdeel": "los onderdeel"}[kind]
            return kind, f"{label} ('{found.group(0)}')"
    found = NOT_A_COMPUTER_ITEM_RE.search(title) or ACCESSORY_BRAND_RE.search(title)
    if found:
        return "accessoire", f"geen computer ('{found.group(0)}')"
    word = ACCESSORY_WORD_RE.search(title)
    if word:
        device = DEVICE_RE.search(title[: word.start()])
        if not (device and BUNDLE_RE.search(title[device.end(): word.start()])):
            return "accessoire", f"'{word.group(0)}' zonder bekend model"
    without = WITHOUT_DEVICE_RE.search(description or "")
    if without:
        return "accessoire", f"beschrijving: '{without.group(0)}'"
    if word:
        return "computer", f"model onbekend, met accessoires ('{word.group(0)}')"
    return "computer", "model onbekend"


def match_model(title: str, catalog: Sequence[ComputerModel]) -> Optional[ComputerModel]:
    """Het model als de titel over een computer lijkt te gaan (ook bij twijfel,
    dan beslist de prijs later), anders None."""
    found = classify_title(title, catalog)
    return found.model if found and found.kind in ("computer", "twijfel") else None


# --- Functiescore -----------------------------------------------------------


@dataclass(frozen=True)
class FeatureScore:
    score: float
    parts: dict  # onderdeel -> punten (van het gewicht)
    unknown: tuple  # velden die leeg waren
    reasons: tuple  # korte Nederlandse zinnetjes, sterkste eerst

    @property
    def summary(self) -> str:
        text = " · ".join(self.reasons)
        if self.unknown:
            text += f" · onbekend: {', '.join(self.unknown)}"
        return text


def _credit(model: ComputerModel, key: str, values: dict, config: dict, unknown: list) -> float:
    value = model.get(key)
    if not value:
        unknown.append(key)
        return config["unknown_credit"]
    return values[value]


def feature_score(model: ComputerModel, config: Optional[dict] = None) -> FeatureScore:
    config = config or default_config()
    w = config["weights"]
    unknown: list[str] = []
    parts: dict[str, float] = {}

    nav = config["navigatie"]
    parts["navigatie"] = w["navigatie"] * sum(
        spec["share"] * _credit(model, key, spec["values"], config, unknown) for key, spec in nav.items()
    )
    parts["planning"] = w["planning"] * _credit(
        model, "planning_op_apparaat", config["planning_op_apparaat"], config, unknown
    )
    parts["training"] = w["training"] * sum(
        share * _credit(model, key, {"ja": 1.0, "nee": 0.0}, config, unknown)
        for key, share in config["training"].items()
    )
    parts["bediening"] = w["bediening"] * _credit(model, "bediening", config["bediening"], config, unknown)

    hours = model.number("batterijduur_uur")
    if hours is None:
        unknown.append("batterijduur_uur")
        parts["batterij"] = w["batterij"] * config["unknown_credit"]
    else:
        low, high = config["batterij"]["min_uur"], config["batterij"]["max_uur"]
        parts["batterij"] = w["batterij"] * min(1.0, max(0.0, (hours - low) / (high - low)))

    score = sum(parts.values())
    penalty = config["support_penalty"].get(model.get("ondersteund"), 0)
    score = max(0.0, score - penalty)

    reasons = []
    rerouting = model.get("rerouting")
    if rerouting == "ja":
        reasons.append("rerouting")
    elif rerouting == "via_telefoon":
        reasons.append("rerouting alleen via telefoon")
    elif rerouting == "nee":
        reasons.append("geen rerouting")
    planning = model.get("planning_op_apparaat")
    if planning:
        reasons.append({"volledig": "plannen op apparaat", "beperkt": "beperkt plannen op apparaat",
                        "nee": "niet plannen op apparaat"}[planning])
    if model.get("ant_plus") == "nee":
        reasons.append("geen ANT+")
    if model.get("schakel_integratie") == "ja":
        reasons.append("Di2/AXS")
    if model.get("bediening"):
        reasons.append(model.get("bediening"))
    if hours is not None:
        reasons.append(f"{hours:g} u accu")
    if penalty:
        reasons.append({"nee": "geen updates meer", "beperkt": "merk gestopt, support loopt nog"}.get(
            model.get("ondersteund"), "") + f" (−{penalty})")
    return FeatureScore(round(score, 1), parts, tuple(unknown), tuple(reasons))


def find_model(catalog: Sequence[ComputerModel], merk: str, model: str) -> Optional[ComputerModel]:
    for m in catalog:
        if m.merk.lower() == merk.lower() and m.model.lower() == model.lower():
            return m
    return None


# --- Per advertentie --------------------------------------------------------


def listing_category(url: str) -> Optional[str]:
    """De categorie uit een Marktplaats-URL (/v/<hoofdcategorie>/<categorie>/
    <id>-...), of None als de URL die vorm niet heeft."""
    parts = urlsplit(url or "").path.strip("/").split("/")
    if len(parts) >= 4 and parts[0] == "v":
        return parts[2]
    return None


def in_bike_category(url: str) -> bool:
    """Een advertentie in een fietscategorie ("fietsen-racefietsen", ...) is
    een fiets, ook als de titel een computer noemt: "Giant Defy met Garmin
    Edge 530" heeft geen fietswoord vóór de modelnaam maar is geen losse
    computer, en zou anders als vergelijkingsprijs van €900 meetellen."""
    category = listing_category(url)
    return bool(category and category.startswith("fietsen-"))


@dataclass
class ComputerSignal:
    model: ComputerModel
    features: FeatureScore
    kind: str  # computer | accessoire | onderdeel | defect | gevraagd
    reason: str  # waarom deze soort; bij een computer een opmerking of ""
    price_eur: Optional[float]
    upgrade_delta: Optional[float] = None  # punten t.o.v. de eigen computer
    upgrade_per_100: Optional[float] = None  # punten per €100 van de prijs
    comp_count: int = 0
    comp_note: str = ""
    # Verwachte verkoopprijs (mediaan) en de band eromheen (kwartielen), alle
    # drie al na onderhandelingsruimte.
    resale_eur: Optional[float] = None
    resale_low_eur: Optional[float] = None
    resale_high_eur: Optional[float] = None
    costs_eur: float = 0.0
    own_resale_eur: Optional[float] = None  # wat de eigen computer zou opbrengen

    @property
    def is_computer(self) -> bool:
        return self.kind == "computer"

    @property
    def excluded(self) -> str:
        """De reden waarom dit geen upgrade, flip of vergelijkingsprijs is, of
        "" als het gewoon een computer is."""
        return "" if self.is_computer else self.reason

    def _profit(self, resale: Optional[float]) -> Optional[float]:
        if not self.is_computer or resale is None or self.price_eur is None:
            return None
        return round(resale - self.price_eur - self.costs_eur, 2)

    @property
    def profit_eur(self) -> Optional[float]:
        return self._profit(self.resale_eur)

    @property
    def profit_low_eur(self) -> Optional[float]:
        return self._profit(self.resale_low_eur)

    @property
    def profit_high_eur(self) -> Optional[float]:
        return self._profit(self.resale_high_eur)

    # Oude naam, van vóór de kosten en de band; zelfde getal als profit_eur.
    flip_margin_eur = profit_eur

    @property
    def max_bid_eur(self) -> Optional[float]:
        """Het hoogste bedrag waarbij je bij de lage verkoopschatting nog
        quitte speelt — voor een advertentie zonder prijs."""
        if not self.is_computer or self.resale_low_eur is None:
            return None
        return round(self.resale_low_eur - self.costs_eur, 2)

    @property
    def is_upgrade(self) -> bool:
        return self.is_computer and self.upgrade_delta is not None and self.upgrade_delta > 0

    @property
    def net_upgrade_cost_eur(self) -> Optional[float]:
        """Wat de upgrade echt kost: de prijs min wat de eigen computer oplevert."""
        if self.price_eur is None or self.own_resale_eur is None:
            return None
        return round(self.price_eur - self.own_resale_eur, 2)


def _comparable_price(listing) -> Optional[float]:
    """Wat een andere advertentie vraagt, als vergelijkingsprijs. Een lopend
    bod (FAST_BID met biedingen) is geen vraagprijs en telt niet mee."""
    if getattr(listing, "reserved", False) or not listing.price_is_asking:
        return None
    return listing.price_eur


def db_comparables(db_path, catalog: Sequence[ComputerModel], window_days: int) -> dict[str, dict[str, float]]:
    """{modellabel: {item_id: prijs}} uit eerdere runs in koopjes.db. Alleen
    vraagprijzen (`price_is_asking`, migratie 3; bij oudere rijen waar die
    NULL is beslist `is_bid`, zoals db.py dat ook doet), alleen titels die
    zonder twijfel een computer zijn, niet uit een fietscategorie, en alleen
    advertenties die de afgelopen `window_days` nog gezien zijn — verkochte
    (verdwenen) tellen dus mee. Opent de database alleen-lezen; een
    ontbrekende database is geen fout."""
    if not db_path or not Path(db_path).exists():
        return {}
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat(timespec="seconds")
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute(
            "SELECT item_id, title, price_eur, url, description FROM listing "
            "WHERE price_eur IS NOT NULL "
            "AND COALESCE(price_is_asking, is_bid = 0) = 1 "
            "AND (last_seen IS NULL OR last_seen >= ?)",
            (since,),
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    found: dict[str, dict[str, float]] = {}
    for item_id, title, price, url, description in rows:
        if in_bike_category(url) or WITHOUT_DEVICE_RE.search(description or ""):
            continue
        verdict = classify_title(title, catalog)
        if verdict and verdict.kind == "computer":
            found.setdefault(verdict.model.label, {})[item_id] = price
    return found


def _resolve_doubt(listing, model: ComputerModel, clean: list, reason: str, config: dict) -> tuple[str, str]:
    """Een titel met een houder- of hoeswoord direct na de modelnaam: is het
    een computer of een accessoire? De prijs beslist, tegen (1) de mediaan van
    hetzelfde model, anders (2) de nieuwprijs, anders (3) een vaste ondergrens.
    Liever een houder die als computer doorglipt (die zie je aan de foto) dan
    een echte computer die in Uitgefilterd verdwijnt."""
    rules = config["filter"]
    price = listing.price_eur
    if price is None:
        return "computer", f"{reason}; geen prijs — kijk op de foto"
    if len(clean) >= config["flip"]["min_comps"]:
        median = statistics.median(clean)
        if price < rules["max_share_of_median"] * median:
            return "accessoire", (f"{reason}, en €{price:.0f} is {price / median:.0%} van de mediaan "
                                  f"(€{median:.0f}) — vermoedelijk accessoire")
        return "computer", f"{reason}, maar €{price:.0f} past bij een computer (mediaan €{median:.0f})"
    new = model.number("nieuwprijs_eur")
    if new:
        if price < rules["max_share_of_new"] * new:
            return "accessoire", (f"{reason}, en €{price:.0f} is {price / new:.0%} van de nieuwprijs "
                                  f"(€{new:.0f}) — vermoedelijk accessoire")
        return "computer", f"{reason}, maar €{price:.0f} past bij een computer (nieuwprijs €{new:.0f})"
    if price < rules["floor_eur"]:
        return "accessoire", f"{reason}, en €{price:.0f} is minder dan €{rules['floor_eur']:.0f} — vermoedelijk accessoire"
    return "computer", f"{reason}, maar €{price:.0f} past bij een computer"


def _resale_band(prices: list, factor: float) -> tuple[float, float, float]:
    """(laag, midden, hoog): kwartielen en mediaan van de vraagprijzen, maal de
    onderhandelingsfactor."""
    median = statistics.median(prices)
    low, _, high = statistics.quantiles(prices, n=4, method="inclusive")
    return round(low * factor, 2), round(median * factor, 2), round(high * factor, 2)


def market_resale(db_path, catalog: Optional[Sequence[ComputerModel]] = None,
                  config: Optional[dict] = None, exclude: frozenset = frozenset()) -> dict[str, float]:
    """{modellabel: verwachte verkoopprijs nu} uit koopjes.db, met dezelfde
    regels als de flipwinst (mediaan × onderhandelingsfactor, minimaal
    min_comps advertenties). Voor de voorraad in "Mijn flips". `exclude`:
    de advertenties waar de eigenaar zelf kocht — zijn eigen koopje zou de
    schatting van wat hij ervoor terugkrijgt anders omlaag trekken."""
    catalog = catalog if catalog is not None else _default_catalog()
    flip = (config or default_config())["flip"]
    comps = db_comparables(db_path, catalog, flip["comp_window_days"])
    result = {}
    for label, prices in comps.items():
        kept = [p for item_id, p in prices.items() if item_id not in exclude]
        if len(kept) >= flip["min_comps"]:
            result[label] = _resale_band(kept, flip["negotiation_factor"])[1]
    return result


def apply_computer_signals(
    listings,
    *,
    db_path=None,
    catalog: Optional[Sequence[ComputerModel]] = None,
    config: Optional[dict] = None,
) -> int:
    """Zet `listing.computer` voor elke advertentie waarvan de titel een
    bekend model noemt en die geen fiets is — ook voor accessoires, onderdelen
    en dergelijke, met de reden, zodat ze in Uitgefilterd te zien zijn. Geeft
    het aantal echte computers terug. De rest blijft None."""
    catalog = catalog if catalog is not None else _default_catalog()
    config = config or default_config()
    base = config["baseline"]
    baseline = find_model(catalog, base["merk"], base["model"])
    baseline_score = feature_score(baseline, config).score if baseline else None
    flip = config["flip"]
    factor = flip["negotiation_factor"]

    found = []  # [listing, model, kind, reason]
    for listing in listings:
        listing.computer = None
        if in_bike_category(listing.url):
            continue
        verdict = classify_title(listing.title, catalog)
        if verdict is None or verdict.kind == "fiets":
            continue
        kind, reason = verdict.kind, verdict.reason
        without = WITHOUT_DEVICE_RE.search(listing.description or "")
        if kind in ("computer", "twijfel") and without:
            kind, reason = "accessoire", f"beschrijving: '{without.group(0)}'"
        found.append([listing, verdict.model, kind, reason])
    if not found:
        return 0

    # Eerst de zekere computers als vergelijkingsprijs; daartegen worden de
    # twijfelgevallen beslist, en wat dan een computer blijkt telt ook mee.
    comps = db_comparables(db_path, catalog, flip["comp_window_days"])
    for listing, model, kind, _ in found:
        price = _comparable_price(listing) if kind == "computer" else None
        if price is not None:
            comps.setdefault(model.label, {})[listing.item_id] = price
    for item in found:
        listing, model, kind, reason = item
        if kind != "twijfel":
            continue
        clean = [p for i, p in comps.get(model.label, {}).items() if i != listing.item_id]
        item[2], item[3] = _resolve_doubt(listing, model, clean, reason, config)
        price = _comparable_price(listing) if item[2] == "computer" else None
        if price is not None:
            comps.setdefault(model.label, {})[listing.item_id] = price

    own_resale = base.get("eigen_verkoopprijs_eur")
    if own_resale is None:
        own = list(comps.get(baseline.label, {}).values()) if baseline else []
        own_resale = _resale_band(own, factor)[1] if len(own) >= flip["min_comps"] else None

    count = 0
    for listing, model, kind, reason in found:
        features = feature_score(model, config)
        signal = ComputerSignal(model, features, kind, reason, listing.price_eur,
                                costs_eur=flip.get("costs_eur", 0.0), own_resale_eur=own_resale)
        listing.computer = signal
        if not signal.is_computer:
            signal.comp_note = f"{reason} — geen flip"
            continue
        count += 1
        if baseline_score is not None:
            signal.upgrade_delta = round(features.score - baseline_score, 1)
            if listing.price_eur and listing.price_eur > 0:
                signal.upgrade_per_100 = round(signal.upgrade_delta / listing.price_eur * 100, 1)
        others = [p for item_id, p in comps.get(model.label, {}).items() if item_id != listing.item_id]
        signal.comp_count = len(others)
        if len(others) >= flip["min_comps"]:
            signal.resale_low_eur, signal.resale_eur, signal.resale_high_eur = _resale_band(others, factor)
            signal.comp_note = (f"mediaan van {len(others)} andere advertenties × {factor:g} "
                                "(onderhandelingsruimte, heuristiek); de band is het middelste kwart-tot-driekwart")
        else:
            signal.comp_note = f"te weinig vergelijkingsmateriaal ({len(others)} andere, minimaal {flip['min_comps']})"
    return count


def computer_listings(listings) -> list:
    """Alles met een signaal, ook de uitgefilterde."""
    return [l for l in listings if getattr(l, "computer", None) is not None]


def active_computers(listings) -> list:
    """Alleen de echte computers."""
    return [l for l in computer_listings(listings) if l.computer.is_computer]


def filtered_out(listings) -> list:
    return [l for l in computer_listings(listings) if not l.computer.is_computer]


# --- Wat je erbij krijgt ----------------------------------------------------

# Volgorde van slecht naar goed per veld; een onbekende waarde aan een van
# beide kanten zegt niets en wordt overgeslagen.
_RANKS = {
    "rerouting": ["nee", "via_telefoon", "ja"],
    "kaarten": ["nee", "basiskaart", "los_te_koop", "routeerbaar"],
    "planning_op_apparaat": ["nee", "beperkt", "volledig"],
    "route_sync": ["nee", "ja"],
    "schakel_integratie": ["nee", "ja"],
    "workouts": ["nee", "ja"],
    "klimfunctie": ["nee", "ja"],
    "ant_plus": ["nee", "ja"],
    "ondersteund": ["nee", "beperkt", "ja"],
}
_LABELS = {
    "rerouting": "rerouting", "kaarten": "kaarten", "planning_op_apparaat": "plannen op het apparaat",
    "route_sync": "route-sync", "schakel_integratie": "Di2/AXS", "workouts": "workouts",
    "klimfunctie": "klimfunctie", "ant_plus": "ANT+", "ondersteund": "updates",
}


def feature_changes(model: ComputerModel, baseline: Optional[ComputerModel], config: Optional[dict] = None) -> tuple[list, list]:
    """(wat je erbij krijgt, wat je inlevert) t.o.v. de eigen computer, als
    korte Nederlandse zinnetjes."""
    if baseline is None:
        return [], []
    config = config or default_config()
    gains, losses = [], []
    for key, order in _RANKS.items():
        new, old = model.get(key), baseline.get(key)
        if not new or not old or new == old:
            continue
        text = f"{_LABELS[key]}: {new.replace('_', ' ')} i.p.v. {old.replace('_', ' ')}"
        (gains if order.index(new) > order.index(old) else losses).append(text)
    new, old = model.get("bediening"), baseline.get("bediening")
    if new and old and new != old:
        values = config["bediening"]
        (gains if values[new] > values[old] else losses).append(f"{new} i.p.v. {old}")
    new, old = model.number("batterijduur_uur"), baseline.number("batterijduur_uur")
    if new is not None and old is not None and abs(new - old) >= 3:
        (gains if new > old else losses).append(f"{new:g} u accu i.p.v. {old:g} u")
    return gains, losses


def baseline_model(catalog: Optional[Sequence[ComputerModel]] = None, config: Optional[dict] = None) -> Optional[ComputerModel]:
    catalog = catalog if catalog is not None else _default_catalog()
    base = (config or default_config())["baseline"]
    return find_model(catalog, base["merk"], base["model"])


# --- Uitvoer ----------------------------------------------------------------


def _euro(amount: Optional[float]) -> str:
    return "—" if amount is None else f"€{amount:,.0f}".replace(",", ".")


def _signed(value: Optional[float], suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:+.0f}{suffix}"


def price_kind(listing) -> str:
    """Wat voor prijs er staat — dat bepaalt hoe hard de winst is."""
    if listing.price_eur is None:
        return "bieden, geen prijs" if listing.price_is_bid else "geen prijs genoemd"
    if listing.price_type == "MIN_BID":
        return "vraagprijs, bieden kan"
    if listing.price_is_bid and not listing.price_is_asking:
        return "huidig bod, loopt nog op"
    if listing.price_type == "FAST_BID":
        return "minimumbod"
    return "vaste prijs"


def upgrades(listings) -> list:
    """Advertenties die meer kunnen dan de eigen computer, meeste punten per
    euro eerst."""
    found = [l for l in active_computers(listings) if l.computer.is_upgrade and l.price_eur]
    return sorted(found, key=lambda l: (-(l.computer.upgrade_per_100 or 0), -l.computer.upgrade_delta))


def flips(listings) -> list:
    """Computers met een bekende winst, grootste winst eerst (ook negatief)."""
    found = [l for l in active_computers(listings) if l.computer.profit_eur is not None]
    return sorted(found, key=lambda l: -l.computer.profit_eur)


def open_bids(listings) -> list:
    """Computers zonder prijs waarvoor wel een maximaal bod te geven is."""
    found = [l for l in active_computers(listings)
             if l.price_eur is None and l.computer.max_bid_eur is not None]
    return sorted(found, key=lambda l: -l.computer.max_bid_eur)


def print_computers(listings, limit: int = 10) -> None:
    """Na de slapers: alleen als deze run fietscomputers bevat."""
    found = active_computers(listings)
    if not found:
        return
    import sleepers  # price_text(); hier geïmporteerd zodat dit bestand los te draaien is

    skipped = len(filtered_out(listings))
    print(f"\n=== Fietscomputers: {len(found)} herkend"
          f"{f', {skipped} uitgefilterd (houders, onderdelen, defect)' if skipped else ''} ===")
    fl = [l for l in flips(listings) if l.computer.profit_eur > 0][:limit]
    if fl:
        print("Flips (winst = verwachte verkoopprijs − prijs − verzendkosten):")
        for l in fl:
            c = l.computer
            print(f"  {_signed(c.profit_eur):>5} ({_euro(c.profit_low_eur)} tot {_euro(c.profit_high_eur)}) "
                  f"{sleepers.price_text(l)[:22]:<22} {c.model.label[:26]:<26} (n={c.comp_count}) {l.url}")
    ups = upgrades(listings)[:limit]
    if ups:
        print("Upgrade t.o.v. eigen computer (punten per €100):")
        for l in ups:
            c = l.computer
            print(f"  {_signed(c.upgrade_delta):>4} ({c.upgrade_per_100:+.1f}/€100) "
                  f"{sleepers.price_text(l)[:22]:<22} {c.model.label[:26]:<26} {l.url}")
    if not ups and not fl:
        print("Geen upgrade en geen flip met winst in deze run.")


def render_panel(listings, config: Optional[dict] = None) -> tuple[int, str]:
    """(aantal, html) voor de tab Fietscomputers in het gewone rapport. Het
    volledige overzicht staat in dashboard.html (dashboard.py)."""
    import sleepers

    config = config or default_config()
    found = active_computers(listings)
    esc = html_lib.escape
    base = config["baseline"]
    parts = [
        "<h2>Fietscomputers</h2>",
        "<p class='muted'>Het complete overzicht, over alle zoekopdrachten heen, staat in "
        "<code>dashboard.html</code> (<code>python dashboard.py</code>). "
        f"<strong>Winst</strong> = wat andere advertenties voor hetzelfde model vragen, na "
        f"onderhandelingsruimte, min prijs en verzendkosten. <strong>Upgrade</strong> = functiescore min die "
        f"van de eigen {esc(base['merk'])} {esc(base['model'])}. Geen van beide is de dealscore.</p>",
    ]
    if not found and not filtered_out(listings):
        parts.append("<p class='muted'>Geen fietscomputers herkend in deze run.</p>")
        return 0, "\n".join(parts)

    def row(l, first: str) -> str:
        c = l.computer
        return (
            "<tr>"
            f"<td class='num'><strong>{first}</strong></td>"
            f"<td class='num'>{esc(sleepers.price_text(l))}</td>"
            f"<td>{esc(c.model.label)}<div class='muted'>{esc(c.reason or c.features.summary)}</div></td>"
            f"<td><a href='{esc(l.url, quote=True)}' target='_blank' rel='noopener'>{esc(l.title)}</a></td>"
            "</tr>"
        )

    head = ("<div class='table-wrap'><table><thead><tr><th>{}</th><th>Prijs</th>"
            "<th>Model</th><th>Titel</th></tr></thead><tbody>{}</tbody></table></div>")

    fl = [l for l in flips(listings) if l.computer.profit_eur > 0]
    parts.append(f"<h3>Flips met winst ({len(fl)})</h3>")
    if fl:
        parts.append(head.format("Winst", "".join(
            row(l, f"{_signed(l.computer.profit_eur)} <span class='muted' title='{esc(l.computer.comp_note, quote=True)}'>"
                   f"({_euro(l.computer.profit_low_eur)} tot {_euro(l.computer.profit_high_eur)}, n={l.computer.comp_count})</span>")
            for l in fl)))
    else:
        parts.append("<p class='muted'>Geen computer die onder de verwachte verkoopprijs staat.</p>")

    ups = upgrades(listings)
    parts.append(f"<h3>Upgrade voor mij ({len(ups)})</h3>")
    if ups:
        parts.append(head.format("Upgrade", "".join(
            row(l, f"{_signed(l.computer.upgrade_delta)} <span class='muted'>"
                   f"({l.computer.upgrade_per_100:+.1f}/€100)</span>")
            for l in ups)))
    else:
        parts.append("<p class='muted'>Geen herkende computer die meer kan dan de eigen.</p>")

    out = filtered_out(listings)
    if out:
        parts.append(f"<h3>Uitgefilterd ({len(out)})</h3>")
        parts.append(head.format("Soort", "".join(row(l, esc(l.computer.kind)) for l in out)))
    return len(found), "\n".join(parts)


# --- Losse CLI: de score per model ------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Functiescore per fietscomputermodel uit reference_bike_computers.csv, "
                    "met het verschil t.o.v. de eigen computer."
    )
    parser.add_argument("--catalog", default=str(CATALOG_PATH))
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--merk", help="alleen dit merk")
    args = parser.parse_args(argv)
    try:
        catalog = load_catalog(Path(args.catalog))
    except (OSError, CatalogError) as exc:
        print(f"Kan de catalogus niet lezen: {exc}", file=sys.stderr)
        return 1
    config = load_config(Path(args.config))
    base = config["baseline"]
    baseline = find_model(catalog, base["merk"], base["model"])
    base_score = feature_score(baseline, config).score if baseline else None
    rows = [(m, feature_score(m, config)) for m in catalog
            if not args.merk or m.merk.lower() == args.merk.lower()]
    rows.sort(key=lambda r: -r[1].score)
    print(f"{'Score':>5} {'Δ eigen':>7}  {'Model':<30} {'Nieuw':>7}  Onderbouwing")
    for m, f in rows:
        delta = f"{f.score - base_score:+.0f}" if base_score is not None else ""
        price = _euro(m.number("nieuwprijs_eur"))
        marker = " ← eigen" if m is baseline else ""
        print(f"{f.score:>5.0f} {delta:>7}  {m.label[:30]:<30} {price:>7}  {f.summary}{marker}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
