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

# Staat een van deze woorden vóór de modelnaam, dan gaat de titel over een
# fiets (of een trainer) die toevallig een computer noemt: "Racefiets Cube +
# Garmin Edge 130 Plus". Erna is het een omschrijving van de computer zelf:
# "Garmin Edge 800 fiets Navigatie", "Garmin Edge 130 MTB fietscomputer" —
# die vielen in de volledige crawl van 28-09-2026 eerst ten onrechte weg.
# \b houdt "fietscomputer" erbuiten.
NOT_A_COMPUTER_RE = re.compile(
    r"\b(?:racefiets\w*|fiets|fietsen|mountainbike|mtb|gravel\s?bike|gravelfiets|e-?bike"
    r"|tijdritfiets|kickr|trainer|fietstrainer)\b",
    re.I,
)
# Een accessoire vóór de modelnaam ("Houder voor Garmin Edge 530") is een
# accessoire; erna ("Garmin Edge 530 met houder") is een computer met extra's.
ACCESSORY_RE = re.compile(
    r"\b(?:houder|houders|mount|stuurhouder|hoes|hoesje|case|cover|folie|screen\s?protector"
    r"|protector|beschermfolie|beugel|adapter|kabel|oplader|lader|siliconen)\b",
    re.I,
)


# Een reparatiedienst ("Garmin Edge 830 scherm vervangen" — twee keer in de
# eerste echte crawl, 28-09-2026) of een defect toestel. Wordt wel getoond,
# maar is geen upgrade, geen flip en geen vergelijkingsprijs: de prijs zegt
# niets over wat een werkend exemplaar opbrengt.
REPAIR_RE = re.compile(
    r"\b(?:scherm\s?vervang\w*|reparatie\w*|repar(?:eer|eren)\w*|defect\w*|kapot\w*"
    r"|voor\s+onderdelen|werkt\s+niet|accu\s?vervang\w*)\b",
    re.I,
)


# Losse onderdelen met een modelnaam in de titel ("Garmin LCD scherm Edge
# 830", "Hammerhead Karoo 2 custom color kit", "veiligheidskoord voor Roam")
# — gezien in de volledige crawl van de categorie, 28-09-2026. Waar ook in de
# titel: dit zijn nooit hele computers.
PART_RE = re.compile(
    r"\b(?:lcd|colou?r\s?kit|kleur\s?kit|\w*koord|tether|onderdel\w*|reserveonderdel\w*)\b",
    re.I,
)
# Een houder of hoes kan ook ná de modelnaam staan ("Wahoo Roam I
# stuurhouder", "Bolt 2.0 aero race mount"), maar "Garmin Edge 530 +
# stuurmount" voor €170 is gewoon een computer. Zo'n woord ergens in de titel
# maakt een advertentie alleen verdacht; de prijs beslist (ACCESSORY_MAX_SHARE).
# Geen \b vooraan: "fietscomputerhouder" en "stuurmount" moeten ook meetellen.
ACCESSORY_ANYWHERE_RE = re.compile(
    r"(?:houders?|mount|hoes|hoesje|beugel|cover|folie|protector|steun)\b", re.I
)
# Onder dit deel van de mediaan van hetzelfde model is een verdachte titel een
# accessoire. Een werkende Edge 530 voor 40% van de mediaan zou een koopje
# zijn dat je mist; dat risico is kleiner dan een houder van €15 bovenaan de
# flipmarge.
ACCESSORY_MAX_SHARE = 0.4


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


def match_model(title: str, catalog: Sequence[ComputerModel]) -> Optional[ComputerModel]:
    """Het eerste model waarvan het patroon in de titel staat, of None als er
    een fiets- of accessoirewoord vóór de modelnaam staat."""
    title = title or ""
    for model in catalog:
        match = model.pattern.search(title)
        if match:
            for other in (NOT_A_COMPUTER_RE, ACCESSORY_RE):
                found = other.search(title)
                if found and found.start() < match.start():
                    return None
            return model
    return None


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


@dataclass
class ComputerSignal:
    model: ComputerModel
    features: FeatureScore
    upgrade_delta: Optional[float]  # punten t.o.v. de eigen computer
    upgrade_per_100: Optional[float]  # punten per €100 van de prijs
    resale_eur: Optional[float]  # verwachte verkoopprijs, na onderhandeling
    flip_margin_eur: Optional[float]
    comp_count: int
    comp_note: str
    # Waarom deze advertentie geen upgrade, flip of vergelijkingsprijs is,
    # of "" als hij gewoon meetelt: reparatie/defect, onderdeel, of een
    # houder/hoes die te goedkoop is om een computer te zijn.
    excluded: str = ""

    @property
    def is_upgrade(self) -> bool:
        return not self.excluded and self.upgrade_delta is not None and self.upgrade_delta > 0


def _comparable_price(listing) -> Optional[float]:
    """Wat een andere advertentie vraagt, als vergelijkingsprijs. Een lopend
    bod (FAST_BID met biedingen) is geen vraagprijs en telt niet mee."""
    if getattr(listing, "reserved", False) or not listing.price_is_asking:
        return None
    return listing.price_eur


def db_comparables(db_path, catalog: Sequence[ComputerModel], window_days: int) -> dict[str, dict[str, float]]:
    """{modellabel: {item_id: prijs}} uit eerdere runs in koopjes.db. Alleen
    vraagprijzen (`price_is_asking`, migratie 3; bij oudere rijen waar die
    NULL is beslist `is_bid`, zoals db.py dat ook doet), en alleen
    advertenties die de afgelopen `window_days` nog gezien zijn. Opent de
    database alleen-lezen; een ontbrekende database is geen fout."""
    if not db_path or not Path(db_path).exists():
        return {}
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat(timespec="seconds")
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute(
            "SELECT item_id, title, price_eur FROM listing "
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
    for item_id, title, price in rows:
        model = match_model(title, catalog)
        if model and not _title_exclusion(title) and not ACCESSORY_ANYWHERE_RE.search(title or ""):
            found.setdefault(model.label, {})[item_id] = price
    return found


def _title_exclusion(title: str) -> str:
    """De reden als de titel alleen al zegt dat dit geen werkende computer is."""
    if REPAIR_RE.search(title or ""):
        return "reparatie of defect in de titel"
    if PART_RE.search(title or ""):
        return "los onderdeel of accessoire"
    return ""


def apply_computer_signals(
    listings,
    *,
    db_path=None,
    catalog: Optional[Sequence[ComputerModel]] = None,
    config: Optional[dict] = None,
) -> int:
    """Zet `listing.computer` voor elke advertentie waarvan de titel een
    bekend model noemt. Geeft het aantal terug. De rest blijft None."""
    catalog = catalog if catalog is not None else _default_catalog()
    config = config or default_config()
    base = config["baseline"]
    baseline = find_model(catalog, base["merk"], base["model"])
    baseline_score = feature_score(baseline, config).score if baseline else None
    flip = config["flip"]

    matched = []
    for listing in listings:
        listing.computer = None
        model = match_model(listing.title, catalog)
        if model:
            matched.append((listing, model))
    if not matched:
        return 0

    excluded = {listing.item_id: _title_exclusion(listing.title) for listing, _ in matched}

    # Eerst de schone prijzen (geen houder- of hoeswoord), om te zien wat
    # een model normaal kost; daarmee valt een verdachte titel met een
    # lage prijs af als accessoire.
    comps = db_comparables(db_path, catalog, flip["comp_window_days"])
    suspect = []
    for listing, model in matched:
        if excluded[listing.item_id]:
            continue
        price = _comparable_price(listing)
        if ACCESSORY_ANYWHERE_RE.search(listing.title or ""):
            suspect.append((listing, model, price))
        elif price is not None:
            comps.setdefault(model.label, {})[listing.item_id] = price
    for listing, model, price in suspect:
        clean = list(comps.get(model.label, {}).values())
        if listing.price_eur is not None and len(clean) >= flip["min_comps"]:
            median = statistics.median(clean)
            if listing.price_eur < ACCESSORY_MAX_SHARE * median:
                excluded[listing.item_id] = (
                    f"houder/hoes in de titel en €{listing.price_eur:.0f} is "
                    f"{listing.price_eur / median:.0%} van de mediaan (€{median:.0f}) — vermoedelijk accessoire"
                )
                continue
        if price is not None:
            comps.setdefault(model.label, {})[listing.item_id] = price

    for listing, model in matched:
        features = feature_score(model, config)
        delta = per_100 = None
        if baseline_score is not None:
            delta = round(features.score - baseline_score, 1)
            if listing.price_eur and listing.price_eur > 0:
                per_100 = round(delta / listing.price_eur * 100, 1)

        others = [p for item_id, p in comps.get(model.label, {}).items() if item_id != listing.item_id]
        reason = excluded[listing.item_id]
        resale = margin = None
        if reason:
            note = f"{reason} — geen flipmarge"
        elif len(others) >= flip["min_comps"]:
            resale = round(statistics.median(others) * flip["negotiation_factor"], 2)
            note = (f"mediaan van {len(others)} andere advertenties × "
                    f"{flip['negotiation_factor']:g} (onderhandelingsruimte, heuristiek)")
            if listing.price_eur is not None:
                margin = round(resale - listing.price_eur, 2)
        else:
            note = f"te weinig vergelijkingsmateriaal ({len(others)} andere, minimaal {flip['min_comps']})"
        listing.computer = ComputerSignal(model, features, delta, per_100, resale, margin, len(others), note, reason)
    return len(matched)


def computer_listings(listings) -> list:
    return [l for l in listings if getattr(l, "computer", None) is not None]


# --- Uitvoer ----------------------------------------------------------------


def _euro(amount: Optional[float]) -> str:
    return "—" if amount is None else f"€{amount:,.0f}".replace(",", ".")


def _signed(value: Optional[float], suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:+.0f}{suffix}"


def upgrades(listings) -> list:
    """Advertenties die meer kunnen dan de eigen computer, meeste punten per
    euro eerst."""
    found = [l for l in computer_listings(listings) if l.computer.is_upgrade and l.price_eur]
    return sorted(found, key=lambda l: (-(l.computer.upgrade_per_100 or 0), -l.computer.upgrade_delta))


def flips(listings) -> list:
    """Advertenties met een bekende flipmarge, grootste marge eerst."""
    found = [l for l in computer_listings(listings) if l.computer.flip_margin_eur is not None]
    return sorted(found, key=lambda l: -l.computer.flip_margin_eur)


def print_computers(listings, limit: int = 10) -> None:
    """Na de slapers: alleen als deze run fietscomputers bevat."""
    found = computer_listings(listings)
    if not found:
        return
    import sleepers  # price_text(); hier geïmporteerd zodat dit bestand los te draaien is

    print(f"\n=== Fietscomputers: {len(found)} herkend ===")
    ups = upgrades(listings)[:limit]
    if ups:
        print("Upgrade t.o.v. eigen computer (punten per €100):")
        for l in ups:
            c = l.computer
            print(f"  {_signed(c.upgrade_delta):>4} ({c.upgrade_per_100:+.1f}/€100) "
                  f"{sleepers.price_text(l)[:22]:<22} {c.model.label[:26]:<26} {l.url}")
    fl = flips(listings)[:limit]
    if fl:
        print("Flipmarge (verwachte verkoopprijs − prijs):")
        for l in fl:
            c = l.computer
            print(f"  {_signed(c.flip_margin_eur):>5} {sleepers.price_text(l)[:22]:<22} "
                  f"{c.model.label[:26]:<26} (n={c.comp_count}) {l.url}")
    if not ups and not fl:
        print("Geen upgrade en geen bekende flipmarge in deze run.")


def render_panel(listings, config: Optional[dict] = None) -> tuple[int, str]:
    """(aantal, html) voor de tab Fietscomputers."""
    import sleepers

    config = config or default_config()
    found = computer_listings(listings)
    esc = html_lib.escape
    base = config["baseline"]
    parts = [
        "<h2>Fietscomputers</h2>",
        "<p class='muted'>Herkend op de titel tegen <code>reference_bike_computers.csv</code>. "
        f"<strong>Upgrade</strong> = functiescore min die van de eigen {esc(base['merk'])} "
        f"{esc(base['model'])} (rerouting, plannen op het apparaat en training wegen het zwaarst, "
        "knoppen gaan voor touch, geen updates kost punten). <strong>Flipmarge</strong> = wat andere "
        "advertenties voor hetzelfde model vragen, na onderhandelingsruimte, min de prijs. Twee aparte "
        "maten, en geen van beide is de dealscore.</p>",
    ]
    if not found:
        parts.append("<p class='muted'>Geen fietscomputers herkend in deze run.</p>")
        return 0, "\n".join(parts)

    def row(l, first: str) -> str:
        c = l.computer
        return (
            "<tr>"
            f"<td class='num'><strong>{first}</strong></td>"
            f"<td class='num'>{esc(sleepers.price_text(l))}</td>"
            f"<td class='num' title='{esc(c.features.summary, quote=True)}'>{c.features.score:.0f}"
            f"{'<div class=muted>' + str(len(c.features.unknown)) + ' onbekend</div>' if c.features.unknown else ''}</td>"
            f"<td>{esc(c.model.label)}<div class='muted'>{esc(c.features.summary)}</div>"
            f"{'<div class=muted><strong>' + esc(c.comp_note) + '</strong></div>' if c.excluded else ''}</td>"
            f"<td><a href='{esc(l.url, quote=True)}' target='_blank' rel='noopener'>{esc(l.title)}</a></td>"
            "</tr>"
        )

    head = ("<div class='table-wrap'><table><thead><tr><th>{}</th><th>Prijs</th><th>Functiescore</th>"
            "<th>Model</th><th>Titel</th></tr></thead><tbody>{}</tbody></table></div>")

    ups = upgrades(listings)
    parts.append(f"<h3>Upgrade voor mij ({len(ups)})</h3>")
    if ups:
        body = "".join(
            row(l, f"{_signed(l.computer.upgrade_delta)} <span class='muted'>"
                   f"({l.computer.upgrade_per_100:+.1f}/€100)</span>")
            for l in ups
        )
        parts.append(head.format("Upgrade", body))
    else:
        parts.append("<p class='muted'>Geen herkende computer die meer kan dan de eigen.</p>")

    fl = flips(listings)
    parts.append(f"<h3>Doorverkopen ({len(fl)})</h3>")
    if fl:
        body = "".join(
            row(l, f"{_signed(l.computer.flip_margin_eur)} <span class='muted' title='{esc(l.computer.comp_note, quote=True)}'>"
                   f"(n={l.computer.comp_count}, verkoop ±{_euro(l.computer.resale_eur)})</span>")
            for l in fl
        )
        parts.append(head.format("Flipmarge", body))
    else:
        parts.append(f"<p class='muted'>Voor geen enkel model genoeg vergelijkingsmateriaal "
                     f"(minimaal {config['flip']['min_comps']} andere advertenties).</p>")

    rest = [l for l in found if l not in ups and l not in fl]
    if rest:
        parts.append(f"<h3>Overige herkende computers ({len(rest)})</h3>")
        body = "".join(row(l, _signed(l.computer.upgrade_delta)) for l in rest)
        parts.append(head.format("Upgrade", body))
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
