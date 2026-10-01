"""/racefietsen in `python dashboard.py --serve`: alle racefietsen uit
koopjes.db op één live pagina, om snel te beslissen of een fiets het waard
is, en hem weg te zetten, te bewaren of te noteren dat je erop bood.

Waarom een eigen pagina en niet het rapport: racefiets_report.html is per
ronde geschreven, zonder knoppen, en ziet alleen de fietsen van die ene
ronde. Hier staat alles wat de rondes vonden (racefietsen, giant-defy,
ultegra-6700; alleen de categorie racefietsen), met dezelfde markeringen als
bij de fietscomputers (marks.py, tabel listing_mark) en een paar redenen
meer om weg te zetten (marks.BIKE_REASONS). Het rapport blijft bestaan.

Per fiets twee oordelen naast elkaar, want de eigenaar koopt voor allebei
(29-09-2026):

- **flip**: geschatte verkoopprijs − wat hij kost. De verkoopprijs komt
  uit de fietsen van hetzelfde model (bike_identity.py: model + uitvoering,
  bouwjaar ±2, en trapsgewijs grover): de mediaan van wat daarvan snel
  verkocht werd (binnen FAST_DAYS weg), of zonder genoeg snelle verkopen de
  mediaan-vraagprijs maal de afdingfactor. Geen model, geen schatting.
  Geen kosten eraf: onderdelen en reizen zoekt de eigenaar per fiets uit,
  op /flips.
- **upgrade**: upgrade.find_upgrades() tegen de eigen fiets uit
  mijn_fiets.md, precies als het tabblad Upgrade van het rapport: beter
  dan de eigen fiets, binnen het budget, maat niet fout.

Plus de waardescore (upgrade.value_score(): waarde / prijs). Niet de
dealscore; die hoort bij het rapport (CLAUDE.md: twee scores, niet
vermengen).

Elke fiets hangt aan een fietsmodel; de eigenaar kan dat op de kaart
goedkeuren (klopt), een ander model kiezen of aanmaken, en het bouwjaar
invullen (bike_link/bike_model, migratie 19). De weergave Modellen is de
lijst met alle modellen. Zo'n correctie rekent alleen die ene fiets opnieuw
(relink()); de andere fietsen van het model volgen bij de volgende ronde.

Snel: het zware deel (vergelijkingsprijzen, upgrade-scores) rekent één keer
per ronde (LiveCache in dashboard.py). De pagina krijgt de fietsen als JSON
en tekent de kaarten zelf, 40 tegelijk, verder als je scrolt; een klik stuurt
alleen die ene fiets terug. Sneltoetsen staan onder de filters.

Actief is hier: niet verdwenen en gezien binnen ACTIVE_DAYS van de nieuwste
waarneming. Ruimer dan de 3 dagen van de computers, omdat overdag alleen de
nieuwste pagina's langskomen en een oudere racefiets alleen in de
zondagronde (week) weer gezien wordt.
"""
from __future__ import annotations

import heapq
import html
import json
import math
import sqlite3
import statistics
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import bike_identity as bi
import db
import distance as dm
import marks as mr
import own_bids as ob
import racefiets_jev as mp
import upgrade as up
import valuation as val
import views as vw

MARKET_KEY = "racefietsen"
PATH = "/racefietsen"
CATEGORY = mp.ROAD_BIKE_CATEGORY
ACTIVE_DAYS = 8
NEW_HOURS = 24
# Waar een geaccepteerd bod heen gaat: een fiets op /flips (flips.OWN_MARKETS).
FLIP_MARKET = "fietsen"
# Waar de pagina een eigen koppeling heen stuurt (dashboard.py).
MODEL_PATH = PATH + "/model"
# Snel verkocht: binnen zoveel dagen na de eerste keer gezien verdwenen, of
# gereserveerd en daarna verdwenen (de eigenaar, 01-10-2026). Verdwenen
# wordt pas na een complete crawl vastgesteld (de zondagronde), dus de
# eerste weken zijn het er weinig.
FAST_DAYS = 7
# Vanaf zoveel snel verkochte in een trede is hun mediaan de schatting.
MIN_FAST = 3
# Zoveel vergelijkingsfietsen (de goedkoopste) gaan mee naar de kaart; een
# trede op opbouw heeft er soms honderden.
COMPS_SHOWN = 12
# Een zelf ingevuld bouwjaar en een zelf gemaakte modelnaam.
YEAR_MIN = 1970
NAME_MIN, NAME_MAX = 3, 80

esc = html.escape


@dataclass
class Row:
    """Eén fiets met wat het zware deel uitrekende."""
    listing: mp.Listing
    frame: Optional[tuple]  # (laag, hoog) in cm, of None
    specs: str
    text: str  # de beschrijving: volledig als die opgehaald is, anders het fragment
    new: bool
    flip_margin: Optional[float] = None
    resale: Optional[float] = None
    flip_basis: str = ""
    flip_rough: bool = False
    value_ratio: Optional[float] = None
    upgrade_ok: bool = False
    upgrade_gain: Optional[float] = None
    upgrade_why: str = ""
    identity: Optional[bi.Identity] = None
    linked: int = 0  # advertenties (180 dagen) aan hetzelfde model
    median: Optional[float] = None  # mediaan-vraagprijs van de vergelijkingsfietsen
    level: str = ""  # welke trede van bike_identity.comparables() de schatting gaf
    few: bool = False  # de trede had er maar MIN_FEW in plaats van MIN_COMPS
    comps: list = field(default_factory=list)  # (titel, prijs, url, jaar, verdwenen, snel): COMPS_SHOWN, snel verkochte eerst
    comp_count: int = 0  # met hoeveel fietsen vergeleken
    fast: tuple = (0, None)  # (aantal, mediaan) snel verkocht in de trede
    for_sale: tuple = (0, None)  # (aantal, mediaan) nog te koop in de trede
    name: str = ""  # de naam van het model zoals de lijst Modellen hem toont


@dataclass
class Base:
    rows: list = field(default_factory=list)
    newest: str = ""
    owner_problem: str = ""
    baseline: Optional[float] = None
    target_cm: Optional[float] = None
    patterns: Optional[vw.ViewPatterns] = None
    # Voor relink(): de pool, de eigen fiets en de afdingfactor van deze
    # berekening, de eigen modellen ({sleutel: bike_model-rij}) en de naam
    # per model ({sleutel: (naam, bron)}).
    pool: bi.Pool = field(default_factory=lambda: bi.Pool([]))
    owner: object = None
    factor: float = val.NEGOTIATION_DEFAULT[1]
    own_models: dict = field(default_factory=dict)
    names: dict = field(default_factory=dict)
    # Een correctie werkt deze Base bij terwijl een ander verzoek hem kan
    # lezen of ook bijwerken: allebei met dit slot vast.
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _index: dict = field(default_factory=dict, repr=False)

    def position(self, item_id: str) -> Optional[int]:
        if len(self._index) != len(self.rows):
            self._index = {r.listing.item_id: i for i, r in enumerate(self.rows)}
        return self._index.get(item_id)

    def row(self, item_id: str) -> Optional[Row]:
        at = self.position(item_id)
        return self.rows[at] if at is not None else None


def _time(value) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


SELECT = (
    "SELECT item_id, title, description, price_eur, price_type, is_bid, price_is_asking, city, "
    "posted_date, condition, frame_height, url, first_seen, last_seen, image_urls, reserved_at, "
    "bid_count, bid_minimum, bid_high, bids_checked_at, checked_at, full_description, disappeared_at, "
    "days_online FROM listing WHERE url LIKE ?")
# Vergelijkingsfietsen: zo ver terug, ook verdwenen (vaak verkocht) — zelfde
# venster als de taxatie (valuation.DEFAULT_COMP_WINDOW_DAYS).
POOL_DAYS = val.DEFAULT_COMP_WINDOW_DAYS


def _listing(r, site: dict, places: dict) -> mp.Listing:
    title, detail = r["title"] or "", r["full_description"] or ""
    groupset, tier = mp.detect_groupset(f"{title} {detail or r['description'] or ''}")
    lat, lon, promotion, traits = places.get(r["item_id"], (None, None, "", ""))
    listing = mp.Listing(
        item_id=r["item_id"], title=title, description=r["description"] or "", price_eur=r["price_eur"],
        price_type=r["price_type"] or "", city=r["city"] or "", date=r["posted_date"] or "",
        condition=r["condition"] or "", frame_height=r["frame_height"] or "", groupset=groupset,
        groupset_tier=tier, url=r["url"] or "", price_is_bid=bool(r["is_bid"]),
        first_seen=r["first_seen"] or "", image_urls=r["image_urls"] or "",
        reserved=r["reserved_at"] is not None, site_specs=site.get(r["item_id"], {}), detail_text=detail,
        latitude=lat, longitude=lon, promotion=promotion or "", traits=traits or "")
    listing.bid_minimum, listing.bid_high = r["bid_minimum"], r["bid_high"]
    # Zelfde regel als dashboard.load_active_listings(): een bod boven de
    # vraagprijs geldt tot de volgende opvraging.
    if (listing.price_type == "MIN_BID" and listing.bid_high is not None and listing.price_eur is not None
            and listing.bid_high > listing.price_eur):
        listing.price_eur = listing.bid_high
    listing.bids_checked_at, listing.checked_at = r["bids_checked_at"], r["checked_at"]
    if r["bid_count"] is not None:
        listing.bid_count = r["bid_count"]
    elif r["is_bid"] and r["price_is_asking"] == 0:
        listing.bid_count = 1
    return listing


@dataclass
class Read:
    """Wat _read() in één keer uit de database haalt."""
    rows: list = field(default_factory=list)
    site: dict = field(default_factory=dict)
    places: dict = field(default_factory=dict)
    links: dict = field(default_factory=dict)  # item_id -> eigen koppeling (db.list_bike_links())
    models: list = field(default_factory=list)  # de eigen modellen (db.list_bike_models())


def _read(db_path) -> Read:
    if not Path(db_path).exists():
        return Read()
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(SELECT, (f"%/{CATEGORY}/%",)).fetchall()
        return Read(rows, db.read_listing_specs(conn, source=db.SITE_SPEC_SOURCE), db.list_places(conn),
                    db.list_bike_links(conn), db.list_bike_models(conn))
    except sqlite3.Error:
        return Read()
    finally:
        conn.close()


def read_links(db_path) -> tuple[dict, list]:
    """Alleen de eigen koppelingen en modellen: klein, voor één correctie."""
    if not Path(db_path).exists():
        return {}, []
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return db.list_bike_links(conn), db.list_bike_models(conn)
    except sqlite3.Error:
        return {}, []
    finally:
        conn.close()


def load_listings(db_path, active_days: int = ACTIVE_DAYS, _read_result=None) -> tuple[list, Optional[datetime], set]:
    """(advertenties, nieuwste waarneming, id's van de nieuwe) in de categorie
    racefietsen, met alles wat de database erover weet."""
    read = _read_result or _read(db_path)
    rows, site, places = read.rows, read.site, read.places
    rows = [r for r in rows if r["disappeared_at"] is None]
    seen = [t for t in (_time(r["last_seen"]) for r in rows) if t]
    if not seen:
        return [], None, set()
    newest = max(seen)
    since = newest - timedelta(days=active_days)
    new_since = newest - timedelta(hours=NEW_HOURS)
    out, new_ids = [], set()
    for r in rows:
        last = _time(r["last_seen"])
        if last is None or last < since:
            continue
        listing = _listing(r, site, places)
        first = _time(r["first_seen"])
        if first and first >= new_since:
            new_ids.add(listing.item_id)
        out.append(listing)
    if len(new_ids) == len(out):
        new_ids = set()  # de allereerste ronde: dan zegt "nieuw" niets
    return out, newest, new_ids


def sold_fast(r) -> bool:
    """Verdwenen binnen FAST_DAYS na de eerste keer gezien, of gereserveerd
    en daarna verdwenen: dan ging hij waarschijnlijk voor ongeveer die prijs
    weg. Verdwenen is geen bewijs van verkocht (patterns.py), maar snel weg
    is het beste wat de zoekresultaten erover zeggen."""
    gone = r["disappeared_at"]
    if not gone:
        return False
    if r["reserved_at"]:
        return True
    if r["days_online"] is not None:
        return r["days_online"] <= FAST_DAYS
    first, end = _time(r["first_seen"]), _time(gone)
    try:
        return bool(first and end and end - first <= timedelta(days=FAST_DAYS))
    except TypeError:  # de een met tijdzone, de ander zonder
        return False


def load_pool(db_path, _read_result=None) -> bi.Pool:
    """Alle racefietsen van de laatste POOL_DAYS met een vraagprijs, ook
    verdwenen, als (Identity, prijs, (item_id, titel, url, verdwenen, snel verkocht))."""
    read = _read_result or _read(db_path)
    rows, site, places = read.rows, read.site, read.places
    seen = [t for t in (_time(r["last_seen"]) for r in rows) if t]
    if not seen:
        return bi.Pool([])
    since = max(seen) - timedelta(days=POOL_DAYS)
    items = []
    for r in rows:
        last = _time(r["last_seen"])
        if last is None or last < since:
            continue
        listing = _listing(r, site, places)
        # Alleen een vraagprijs: een lopend bod zegt nog niet wat hij opbrengt.
        if not listing.price_is_asking or not listing.price_eur or listing.price_eur <= 0:
            continue
        gone = (r["disappeared_at"] or "")[:10]
        items.append((bi.identify(listing, read.links.get(listing.item_id)), listing.price_eur,
                      (listing.item_id, listing.title, listing.url, gone, sold_fast(r))))
    return bi.Pool(items)


@dataclass
class Estimate:
    """Wat estimate() over één fiets zegt."""
    resale: Optional[float] = None  # verwachte verkoopprijs
    basis: str = ""  # de onderbouwing, of waarom er geen schatting is
    level: str = ""  # trede van bike_identity.comparables()
    few: bool = False
    comps: list = field(default_factory=list)  # (titel, prijs, url, jaar, verdwenen, snel), de goedkoopste eerst
    median: Optional[float] = None  # mediaan-vraagprijs van de hele trede
    fast: tuple = (0, None)  # (aantal, mediaan) snel verkocht
    for_sale: tuple = (0, None)  # (aantal, mediaan) nog te koop
    count: int = 0  # met hoeveel fietsen vergeleken; comps is er een deel van


def _median(values: list) -> Optional[float]:
    return statistics.median(values) if values else None


def _era(ident: bi.Identity) -> str:
    return f"{'schijfrem' if ident.disc else 'velgrem'}{', elektronisch' if ident.electronic else ''}"


def estimate(listing: mp.Listing, ident: bi.Identity, pool: bi.Pool, factor: float) -> Estimate:
    """De verwachte verkoopprijs uit de vergelijkbare fietsen van de trede
    die bike_identity.comparables() kiest. Zijn er minstens MIN_FAST snel
    verkocht, dan de mediaan van hun laatste prijs, zonder afdingfactor: dat
    is ongeveer wat ervoor betaald is (de eigenaar, 01-10-2026: "vooral wat
    snel wegging"). Anders de mediaan van alle vraagprijzen maal de
    afdingfactor."""
    level, found, few = pool.comparables(ident, listing.item_id)
    if not found:
        return Estimate(basis="te weinig vergelijkbare fietsen van hetzelfde model en dezelfde jaren"
                        if ident.exact or ident.coarse else "model niet herkend in de titel")
    prices = [c[1] for c in found]
    fast = [c[1] for c in found if c[2][4]]
    for_sale = [c[1] for c in found if not c[2][3]]
    median = statistics.median(prices)
    years = sorted(c[0].year for c in found if c[0].year)
    span = (f" uit {years[0]}-{years[-1]}" if years and years[0] != years[-1]
            else f" uit {years[0]}" if years else "")
    what = {"model+jaar": ident.name, "model": ident.name, "familie+jaar": ident.coarse_name,
            "familie+tijdperk": f"{ident.coarse_name} ({_era(ident)})",
            "opbouw+jaar": f"{ident.material}, groepsettier {ident.tier}, {'schijfrem' if ident.disc else 'velgrem'}",
            "onzeker": ident.coarse_name}[level]
    label = bi.LEVEL_LABELS[level] + (" (weinig)" if few else "")
    if len(fast) >= MIN_FAST:
        resale = statistics.median(fast)
        how = (f"mediaan van de laatste vraagprijs van {len(fast)} snel verkochte (≤{FAST_DAYS} d): "
               f"€{resale:.0f} — wat er echt betaald is weet je niet")
    else:
        resale = median * factor
        how = (f"mediaan van {len(found)} vraagprijzen €{median:.0f} × {val.dutch(factor)} "
               f"({'nog geen snelle verkopen' if not fast else f'nog maar {len(fast)} snel verkocht'})")
    basis = f"{len(found)} × {what}{span} ({label}): {how}"
    if level in bi.UNCERTAIN_LEVELS:
        basis = (f"onzeker, bouwjaar en remtype onbekend — {len(found)} × {what} van €{min(prices):.0f} tot "
                 f"€{max(prices):.0f}: {how}; vraag het jaar na")
    # De snel verkochte eerst (daar rust de schatting op), dan de goedkoopste andere.
    shown = heapq.nsmallest(COMPS_SHOWN, (c for c in found if c[2][4]), key=lambda c: c[1])
    shown += heapq.nsmallest(COMPS_SHOWN - len(shown), (c for c in found if not c[2][4]), key=lambda c: c[1])
    comps = sorted(((c[2][1], c[1], c[2][2], c[0].year, c[2][3], c[2][4]) for c in shown), key=lambda c: c[1])
    return Estimate(resale, basis, level, few, comps, median, (len(fast), _median(fast)),
                    (len(for_sale), _median(for_sale)), len(found))


def specs_line(listing: mp.Listing, year: Optional[int] = None) -> str:
    specs, _ = up.listing_specs(listing, year)
    parts = []
    if listing.frame_height:
        parts.append(listing.frame_height if "cm" in listing.frame_height else f"{listing.frame_height} cm")
    if specs.get("frame_material"):
        parts.append(specs["frame_material"])
    if listing.groupset:
        parts.append(listing.groupset + (f" {specs['speeds']}-speed" if specs.get("speeds") else ""))
    if specs.get("brake_type"):
        parts.append(specs["brake_type"])
    if specs.get("model_year"):
        parts.append(specs["model_year"])
    if specs.get("wheel_type"):
        parts.append(specs["wheel_type"])
    if specs.get("weight_kg"):
        parts.append(f"{specs['weight_kg'].replace('.', ',')} kg")
    if listing.condition:
        parts.append(listing.condition.lower())
    return " · ".join(parts)


def _verdicts(base: Base, listings: list, years: dict) -> dict:
    """{item_id: (upgrade, winst, waarom)} van upgrade.find_upgrades() tegen
    de eigen fiets; leeg zonder eigen fiets (dan base.owner_problem)."""
    owner = base.owner
    if owner is None:
        return {}
    result = up.find_upgrades(
        listings, baseline=owner.quality.total, config=owner.config, budgets=owner.budgets,
        target_size_cm=owner.target_size_cm,
        owner_wheels=(owner.build.wheel_material, owner.build.wheel_branded),
        owner_already_has=owner.owner_has, years=years)
    verdicts = {}
    for c in result.candidates:
        verdicts[c.listing.item_id] = (
            True, c.gain,
            f"+{c.gain:.0f} punten ({c.quality.total:.0f} tegen {owner.quality.total:.0f}), "
            f"€{c.effective.amount:.0f} binnen {c.budget.route}budget €{c.budget.amount:.0f}")
    for r in result.rejected:
        verdicts[r.listing.item_id] = (False, None, r.reason)
    return verdicts


def _own_years(idents: dict) -> dict:
    return {item_id: ident.year for item_id, ident in idents.items() if ident.own_year}


def _make_row(base: Base, l: mp.Listing, ident: bi.Identity, new: bool, verdict: Optional[tuple]) -> Row:
    est = estimate(l, ident, base.pool, base.factor)
    entry = up.entry_price(l)
    margin = est.resale - entry.amount if est.resale is not None and entry.amount is not None else None
    price = up.effective_price(l, base.factor).amount
    ratio = est.resale / price if est.resale is not None and price else None
    ok, gain, why = verdict or (False, None, base.owner_problem)
    if ok and ident.year is None:
        # Zonder bouwjaar rekent de score de fiets als nieuw (geen
        # leeftijdsverval): een oude fiets met goede onderdelen leek dan
        # een upgrade (de eigenaar, 30-09-2026: "upgrade-oordeel raar").
        ok, why = False, f"bouwjaar onbekend — als hij nieuw zou zijn {why}; vraag het jaar na"
    name = base.names.get(ident.exact, (ident.name or "", ""))[0] if ident.exact else ""
    return Row(
        listing=l, frame=mp.frame_height_bounds(l.frame_height),
        specs=specs_line(l, ident.year if ident.own_year else None),
        text=l.detail_text or l.description, new=new,
        flip_margin=margin, resale=est.resale, flip_basis=est.basis, flip_rough=est.level in bi.UNCERTAIN_LEVELS,
        value_ratio=ratio, upgrade_ok=ok, upgrade_gain=gain, upgrade_why=why,
        identity=ident, level=est.level, few=est.few, comps=est.comps, comp_count=est.count,
        linked=base.pool.linked(ident),
        median=est.median, fast=est.fast, for_sale=est.for_sale, name=name)


def _names(base: Base, idents) -> dict:
    """{sleutel: (naam, bron)} per model: het eigen model als de eigenaar
    het aanmaakte, anders het referentiemodel, anders de vaakst herkende
    schrijfwijze ("SL6" en "SL 6" zijn hetzelfde model)."""
    spelled: dict = {}
    reference: dict = {}
    for ident in idents:
        key = ident.exact
        if not key:
            continue
        spelled.setdefault(key, Counter())[ident.name] += 1
        if ident.source == "referentie":
            reference.setdefault(key, ident.name)
    names = {}
    for key, counts in spelled.items():
        if key in base.own_models:
            names[key] = (base.own_models[key]["name"], "eigen")
        elif key in reference:
            names[key] = (reference[key], "referentie")
        else:
            names[key] = (counts.most_common(1)[0][0], "automatisch")
    for key, model in base.own_models.items():
        names.setdefault(key, (model["name"], "eigen"))
    return names


def _own_models(models: list) -> dict:
    return {bi.model_key(m["name"]): m for m in models if bi.model_key(m["name"])}


def build_base(db_path, intake_path, comps: Optional[list] = None) -> Base:
    """Het zware deel: per fiets flip, waardescore en upgrade. `comps`: de
    vergelijkingskandidaten voor de taxatie van de eigen fiets, als de
    aanroeper ze al heeft (LiveCache)."""
    import report

    read = _read(db_path)
    listings, newest, new_ids = load_listings(db_path, _read_result=read)
    base = Base(newest=newest.isoformat(timespec="minutes") if newest else "")
    base.patterns = vw.load_patterns(db_path, (CATEGORY,))
    base.own_models = _own_models(read.models)
    if not listings:
        base.names = _names(base, ())
        return base
    base.pool = load_pool(db_path, _read_result=read)

    owner, problem = report.load_owner_context(str(intake_path), str(db_path), comps=comps)
    if owner is None or owner.budgets is None or owner.target_size_cm is None:
        base.owner_problem = problem or (owner.valuation_problem if owner else "") or "geen eigen fiets"
    else:
        base.owner = owner
        base.baseline, base.target_cm = owner.quality.total, owner.target_size_cm

    idents = {l.item_id: base.pool.identity_of.get(l.item_id) or bi.identify(l, read.links.get(l.item_id))
              for l in listings}
    base.names = _names(base, list(base.pool.identity_of.values()) + list(idents.values()))
    verdicts = _verdicts(base, listings, _own_years(idents))
    for l in listings:
        base.rows.append(_make_row(base, l, idents[l.item_id], l.item_id in new_ids, verdicts.get(l.item_id)))
    return base


# --- Eigen koppeling: één fiets opnieuw ----------------------------------------------


class ModelError(ValueError):
    """Een koppeling die niet kan; de tekst gaat terug naar de pagina."""


def relink(base: Base, db_path, item_id: str) -> tuple[Optional[Row], set]:
    """Na een eigen koppeling: alleen deze fiets opnieuw herkennen, hem in de
    pool verplaatsen (bike_identity.Pool.replace()) en zijn eigen rij
    opnieuw uitrekenen. De andere fietsen van zijn oude en nieuwe model
    houden hun vergelijking tot de volgende ronde: alles opnieuw duurt met
    ~14.000 fietsen ~10 s, en de pagina moet snel blijven (de eigenaar).
    Geeft (nieuwe rij, sleutels van de modellen die veranderden)."""
    with base.lock:
        at = base.position(item_id)
        if at is None:
            return None, set()
        links, models = read_links(db_path)
        base.own_models = _own_models(models)
        row = base.rows[at]
        ident = bi.identify(row.listing, links.get(item_id))
        old = base.pool.replace(item_id, ident) or row.identity
        keys = {k for k in (old.exact if old else None, ident.exact) if k}
        for key in keys:
            members = [c[0] for c in base.pool.by_exact.get(key, ())]
            members += [r.identity for r in base.rows if r.identity and r.identity.exact == key and
                        r.listing.item_id != item_id] + [ident]
            fresh = _names(base, [m for m in members if m.exact == key])
            if key in fresh:
                base.names[key] = fresh[key]
            elif key not in base.own_models:
                base.names.pop(key, None)
        verdict = _verdicts(base, [row.listing], _own_years({item_id: ident})).get(item_id)
        new_row = _make_row(base, row.listing, ident, row.new, verdict)
        base.rows[at] = new_row
        return new_row, keys


def parse_year(value) -> Optional[int]:
    text = (value or "").strip()
    if not text:
        return None
    top = datetime.now().year + 1
    if not text.isdigit() or not YEAR_MIN <= int(text) <= top:
        raise ModelError(f"bouwjaar is een jaartal van {YEAR_MIN} tot {top}.")
    return int(text)


def check_name(value) -> str:
    name = " ".join((value or "").split())
    if not NAME_MIN <= len(name) <= NAME_MAX:
        raise ModelError(f"een modelnaam is {NAME_MIN} tot {NAME_MAX} tekens.")
    if len(name.split()) < 2:
        raise ModelError("een modelnaam is merk en minstens één woord, bv. 'Koga Kinsei Pro'.")
    return name


def _model_id(conn, name: str, brand=None, family=None, variant=None) -> tuple[int, str, bool]:
    """(id, naam, nieuw) van het eigen model met deze sleutel; aangemaakt
    als het er nog niet is. Op sleutel, niet op naam: "Trek Domane SL 6" is
    hetzelfde model als "Trek Domane SL6"."""
    key = bi.model_key(name)
    for model in db.list_bike_models(conn):
        if bi.model_key(model["name"]) == key:
            return model["id"], model["name"], False
    return db.add_bike_model(conn, name, brand, family, variant), name, True


LATER = " De vergelijking van de andere fietsen van dit model wordt na de volgende ronde bijgewerkt."


def apply_model(base: Base, db_path, form: dict) -> tuple[str, Optional[Row], set]:
    """Wat de pagina naar MODEL_PATH stuurt: `item_id` met `model` (een
    naam, bestaand of nieuw), `confirm=1` (klopt), `year` (leeg = weghalen)
    of `clear=1` (ontkoppelen); zonder item_id alleen een nieuw model
    aanmaken (de lijst Modellen). Geeft (melding, bijgewerkte rij, sleutels
    van de modellen die veranderden)."""
    item_id = (form.get("item_id") or "").strip()
    typed = (form.get("model") or "").strip()
    if not item_id:
        name, brand, family, variant = bi.split_name(check_name(typed))
        conn = db.connect(str(db_path))
        try:
            _, name, created = _model_id(conn, name, brand, family, variant)
        finally:
            conn.close()
        key = bi.model_key(name)
        with base.lock:
            known = key in base.names and base.names[key][1] != "eigen"
            base.own_models = _own_models(read_links(db_path)[1])
            base.names[key] = (base.own_models[key]["name"], "eigen") if key in base.own_models else (name, "eigen")
        message = (f"{name} is nu een eigen model." if created and known else
                   f"Model {name} toegevoegd." if created else f"{name} stond er al.")
        return message, None, {key}
    with base.lock:
        row = base.row(item_id)
        if row is None:
            raise ModelError("die fiets staat niet (meer) op de pagina.")
        conn = db.connect(str(db_path))
        try:
            current = db.list_bike_links(conn).get(item_id) or {}
            if form.get("clear") == "1":
                db.set_bike_link(conn, item_id)
                message = "Ontkoppeld: hij hangt weer aan wat de advertentie zegt"
            else:
                model_id, year = current.get("model_id"), current.get("year")
                confirmed = bool(current.get("confirmed"))
                message = ""
                if typed:
                    name, brand, family, variant = bi.split_name(check_name(typed))
                    # Een herkend model uit de lijst kiezen maakt er ook een
                    # eigen model van, maar nieuw is het dan niet.
                    known = bi.model_key(name) in base.names
                    model_id, name, created = _model_id(conn, name, brand, family, variant)
                    confirmed = True
                    message = (f"Nieuw model {name}; deze fiets hangt eraan." if created and not known
                               else f"Gekoppeld aan {name}.")
                elif form.get("confirm") == "1":
                    ident = row.identity
                    name = row.name or (ident.name if ident else None)
                    if not name:
                        raise ModelError("er is geen model herkend; kies 'ander model'.")
                    if ident.own_id is not None:
                        model_id = ident.own_id
                    else:
                        # Merk en familie zoals herkend; een referentiemodel
                        # zonder herkend merk of model ("Scott CR1"): uit de naam.
                        parts = ((ident.brand, ident.family, ident.variant) if ident.brand and ident.family
                                 else bi.split_name(name)[1:])
                        model_id, name, _ = _model_id(conn, name, *parts)
                    confirmed = True
                    message = f"Gecontroleerd: {name}."
                if "year" in form:
                    year = parse_year(form.get("year"))
                    message += (f" Bouwjaar {year}." if year else " Bouwjaar weggehaald.")
                if not message:
                    raise ModelError("er was niets te koppelen.")
                db.set_bike_link(conn, item_id, model_id=model_id, year=year, confirmed=confirmed)
        finally:
            conn.close()
        new_row, keys = relink(base, db_path, item_id)
        if form.get("clear") == "1":
            message += f" ({new_row.name or 'geen model'})."
        return message.strip() + LATER, new_row, keys


def model_entry(key: str, name: str, source: str, pool_items: list, active: list, own_id=None) -> dict:
    """Eén regel van de lijst Modellen; korte sleutels, het zijn er duizenden."""
    prices = [c[1] for c in pool_items]
    fast = [c[1] for c in pool_items if c[2][4]]
    for_sale = [p for p in active if p is not None]
    return {"k": key, "n": name, "s": source, "id": own_id, "a": len(active), "lk": len(pool_items),
            "f": len(fast), "fm": None if not fast else round(statistics.median(fast)),
            "m": None if not prices else round(statistics.median(prices)),
            "lo": None if not for_sale else round(min(for_sale))}


def model_list(base: Base, keys: Optional[set] = None) -> list:
    """De lijst Modellen: alle eigen modellen (ook zonder advertenties) en
    alle modellen die in de pool of op de pagina voorkomen, met te koop,
    gekoppeld (180 dagen), snel verkocht en de prijzen. `keys`: alleen deze."""
    with base.lock:
        active: dict = {}
        for r in base.rows:
            key = r.identity.exact if r.identity else None
            if key and (keys is None or key in keys):
                active.setdefault(key, []).append(r.listing.price_eur)
        wanted = set(base.names) | set(base.pool.by_exact) | set(active) | set(base.own_models)
        if keys is not None:
            wanted &= keys
        out = []
        for key in wanted:
            name, source = base.names.get(key, (key, "automatisch"))
            own = base.own_models.get(key)
            if own:
                name, source = own["name"], "eigen"
            out.append(model_entry(key, name, source, base.pool.by_exact.get(key, []), active.get(key, []),
                                   own["id"] if own else None))
        if keys is not None:
            # Een model zonder advertenties en zonder eigen model (ontkoppeld): leeg terug, zodat de pagina hem bijwerkt.
            out += [dict(model_entry(k, k, "automatisch", [], []), gone=True) for k in keys - wanted]
        out.sort(key=lambda m: (-m["lk"], -m["a"], m["n"].lower()))
        return out


# --- Wat per klik vers is -----------------------------------------------------------


@dataclass
class Fresh:
    """Wat een klik verandert: goedkoop, dus bij elk verzoek opnieuw."""
    marks: dict
    notes: dict
    bids: dict  # item_id -> own_bids.BidTrail
    stats: dict  # item_id -> views.Latest
    home: Optional[dm.Home]
    distances: dict
    bought: dict  # item_id -> datum


def load_fresh(db_path) -> Fresh:
    home, distances = dm.load(db_path)
    bought = {}
    if Path(db_path).exists():
        conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            bought = {t["item_id"]: t["bought_at"] or "" for t in db.list_trades(conn) if t.get("item_id")}
        finally:
            conn.close()
    return Fresh(mr.load_marks(db_path), mr.load_notes(db_path), ob.load(db_path), vw.load_latest(db_path),
                 home, distances, bought)


def price_kind(l: mp.Listing) -> str:
    import computers as pc
    return pc.price_kind(l)


def bike_json(r: Row, f: Fresh) -> dict:
    """Wat de pagina van één fiets nodig heeft; korte sleutels, want het
    zijn er duizenden."""
    l = r.listing
    ident = r.identity
    mark = f.marks.get(l.item_id)
    dismissed = mr.is_dismissed(mark, l)
    back = (mark is not None and mark.mark == mr.DISMISSED and not dismissed)
    trail = f.bids.get(l.item_id)
    stats = f.stats.get(l.item_id)
    dist = f.distances.get(l.item_id)
    bid_bits = []
    if l.bid_count is not None and getattr(l, "bids_checked_at", None):
        bid_bits.append(f"{l.bid_count} bieding{'en' if l.bid_count != 1 else ''}" if l.bid_count else "nog geen bod")
        if l.bid_count and l.bid_high is not None and l.bid_high != l.price_eur:
            bid_bits.append(f"hoogste €{l.bid_high:.0f}")
        if l.bid_minimum:
            bid_bits.append(f"min. €{l.bid_minimum:.0f}")
    return {
        "id": l.item_id, "t": l.title, "u": l.url, "p": l.price_eur, "pk": price_kind(l),
        "bi": " · ".join(bid_bits), "img": (l.image_urls or "").split()[:3], "c": l.city,
        "km": None if dist is None else round(dist.km, 1), "kma": bool(dist and dist.approx),
        # "60 cm of meer" is (60, inf); oneindig bestaat niet in JSON.
        "fr": [b if math.isfinite(b) else 999 for b in r.frame] if r.frame else None, "sp": r.specs, "d": r.text, "n": r.new,
        "res": l.reserved, "fs": l.first_seen,
        "fm": None if r.flip_margin is None else round(r.flip_margin), "rs": None if r.resale is None else round(r.resale),
        "fb": r.flip_basis, "fg": r.flip_rough,
        "vr": None if r.value_ratio is None else round(r.value_ratio, 2),
        "uo": r.upgrade_ok, "ug": None if r.upgrade_gain is None else round(r.upgrade_gain), "uw": r.upgrade_why,
        "m": (mr.FAVORITE if mark and mark.favorite else "weg" if dismissed else ""),
        "mr": mark.reason if mark and dismissed else "",
        "back": (f"Weer terug: de prijs zakte van €{mark.price_eur:.0f} naar €{l.price_eur:.0f} sinds je hem "
                 f"wegzette ({mark.reason or 'weg'})." if back and mark.price_eur is not None and l.price_eur is not None
                 else ""),
        "no": f.notes.get(l.item_id, ""),
        "b": [{"a": b.amount_eur, "at": b.bid_at[:10], "s": b.status} for b in trail.bids] if trail else [],
        "st": None if stats is None else {"v": stats.views, "f": stats.favorites, "df": stats.fav_delta,
                                          "at": stats.observed_at[:10]},
        "own": f.bought.get(l.item_id, "")[:10] if l.item_id in f.bought else "",
        "promo": l.promotion,
        "mdl": ident.label() if ident else "",
        "grp": (r.name or ident.name or "") if ident else "",
        "mk": (ident.exact or "") if ident else "",
        "src": ident.source if ident else "",
        "ref": bool(ident and ident.source == "referentie"),
        "ok": bool(ident and ident.confirmed), "lnk": bool(ident and ident.linked),
        "yr": ident.year if ident else None, "yo": bool(ident and ident.own_year),
        "lk": r.linked,
        "lv": (bi.LEVEL_LABELS.get(r.level, "") + (" (weinig)" if r.few else "")) if r.level else "",
        "sv": [r.fast[0], None if r.fast[1] is None else round(r.fast[1])],
        "tk": [r.for_sale[0], None if r.for_sale[1] is None else round(r.for_sale[1])],
        # Vraagprijs tegen de schatting (de mediaan van de snel verkochte als
        # die er genoeg zijn): -25 = 25% goedkoper.
        "pc": (round((l.price_eur / r.resale - 1) * 100) if r.resale and l.price_eur else None),
        "cmp": [[t, p, u, y, g, s] for t, p, u, y, g, s in r.comps[:COMPS_SHOWN]], "nc": r.comp_count,
        "ck": (getattr(l, "checked_at", None) or "")[:16],
    }


def gone_bids(base: Base, f: Fresh) -> list:
    """Eigen biedingen op fietsen die niet (meer) op de pagina staan: verdwenen
    of te lang niet gezien. Voor de weergave Mijn biedingen."""
    active = {r.listing.item_id for r in base.rows}
    out = []
    for trail in ob.ordered(f.bids):
        if trail.item_id in active or f"/{CATEGORY}/" not in (trail.url or ""):
            continue
        out.append({"id": trail.item_id, "t": trail.title, "u": trail.url,
                    "b": [{"a": b.amount_eur, "at": b.bid_at[:10], "s": b.status} for b in trail.bids],
                    "gone": trail.disappeared_at[:10] if trail.disappeared_at else "",
                    "last": trail.last_seen[:10]})
    return out


# --- HTML ---------------------------------------------------------------------------


CSS = """
.bar { position: sticky; top: 0; z-index: 5; background: var(--surface); padding: 8px 0 6px;
  border-bottom: 1px solid var(--line); margin-bottom: 12px; }
.views { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
.views button { background: none; color: var(--text-2); border: 1px solid var(--line); }
.views button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.filters label { font-size: .85rem; color: var(--text-2); display: inline-flex; gap: 4px; align-items: center; }
.filters input[type=number] { width: 4.2em; font: inherit; padding: 3px 5px; border: 1px solid var(--line);
  border-radius: 6px; background: var(--card); color: var(--text); }
.filters input[type=range] { width: 140px; }
.keys { font-size: .78rem; color: var(--muted); margin-top: 4px; }
.keys kbd { font: inherit; border: 1px solid var(--line); border-radius: 4px; padding: 0 4px; background: var(--card); }
.bike { display: grid; grid-template-columns: minmax(0, 420px) minmax(0, 1fr); gap: 12px; background: var(--card);
  border: 1px solid var(--line); border-radius: 10px; padding: 10px; margin-bottom: 10px; scroll-margin-top: 150px; }
.bike.cur { outline: 3px solid var(--accent); outline-offset: 1px; }
.bike.away { opacity: .6; }
.photos { display: grid; grid-template-columns: 2fr 1fr; grid-template-rows: 1fr 1fr; gap: 4px; height: 240px; }
.photos img, .photos .empty { width: 100%; height: 100%; object-fit: cover; border-radius: 6px; background: var(--line);
  display: block; min-height: 0; }
.photos a:first-child { grid-row: 1 / 3; }
.photos a { display: block; min-height: 0; }
.top { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: baseline; }
.price { font-size: 1.35rem; font-weight: 700; }
.km { font-weight: 600; }
.bike .title { font-weight: 600; font-size: 1.02rem; display: block; margin-top: 2px; }
.specs { margin-top: 4px; font-size: .9rem; }
.verdicts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.pill { font-size: .82rem; padding: 2px 8px; border-radius: 10px; background: var(--badge); }
.pill.good { background: #d8f5d8; color: #0b5d0b; }
.pill.bad { background: var(--line); color: var(--text-2); }
@media (prefers-color-scheme: dark) { .pill.good { background: #1d3d1d; color: #9fe59f; } }
.why { font-size: .78rem; color: var(--muted); margin-top: 3px; }
details.desc summary { cursor: pointer; font-size: .85rem; color: var(--text-2); margin-top: 6px; }
details.desc div { white-space: pre-wrap; font-size: .88rem; margin-top: 4px; max-height: 18em; overflow: auto; }
.row { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; margin-top: 7px; font-size: .85rem; }
.row button { font-size: .8rem; padding: 2px 8px; }
.row input { font: inherit; padding: 2px 6px; border: 1px solid var(--line); border-radius: 6px; background: var(--card);
  color: var(--text); }
.bids { font-size: .82rem; }
.link { font-size: .85rem; margin-top: 2px; }
.cheap { color: var(--good); }
.dear { color: var(--bad); }
.bids .st { font-weight: 600; }
#more { padding: 18px; text-align: center; color: var(--muted); }
.picker { margin-top: 6px; padding: 8px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); }
.picker input[name=mq] { width: 100%; box-sizing: border-box; font: inherit; padding: 3px 6px; border: 1px solid var(--line);
  border-radius: 6px; background: var(--card); color: var(--text); }
.plist { max-height: 240px; overflow: auto; margin: 6px 0; }
.plist button.pick { display: block; width: 100%; text-align: left; background: none; border: none; color: var(--text);
  padding: 3px 4px; font-size: .88rem; cursor: pointer; border-radius: 4px; }
.plist button.pick:hover, .plist button.pick:focus { background: var(--badge); }
#modellist th[data-sort] { cursor: pointer; user-select: none; }
#modellist .row input { font: inherit; padding: 3px 6px; border: 1px solid var(--line); border-radius: 6px;
  background: var(--card); color: var(--text); }
.fast { color: var(--good); font-weight: 600; }
#newmodel, .picker input[name=nieuw] { flex: 1 1 16em; min-width: 0; max-width: 30em; box-sizing: border-box; }
@media (max-width: 760px) { .bike { grid-template-columns: minmax(0, 1fr); } .photos { height: 200px; } }
"""

JS = r"""
window.addEventListener('error', e => {
  const box = document.getElementById('more');
  if (box) { box.hidden = false; box.textContent = 'De pagina kon de fietsen niet tonen: ' + e.message; }
});
const BIKES = JSON.parse(document.getElementById('bikes').textContent);
const MODELS = JSON.parse(document.getElementById('models').textContent);
const MODEL_PATH = '/racefietsen/model';
const GONE = JSON.parse(document.getElementById('gone').textContent);
const REASONS = JSON.parse(document.getElementById('reasons').textContent);
const STATUSES = JSON.parse(document.getElementById('statuses').textContent);
const HOME = document.getElementById('list').dataset.home === '1';
const list = document.getElementById('list');
const more = document.getElementById('more');
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const euro = v => v == null ? '—' : '€' + Math.round(v);
const signed = v => v == null ? '—' : (v >= 0 ? '+' : '−') + '€' + Math.abs(Math.round(v));
const BATCH = 40;
let view = 'open', shown = [], drawn = 0, cur = -1;
const byId = new Map(BIKES.map(b => [b.id, b]));
const modelByKey = new Map(MODELS.map(m => [m.k, m]));
// Zoeken zonder accenten en hoofdletters: "emonda" vindt "Émonda".
const fold = s => String(s == null ? '' : s).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

function state() {
  let s = {};
  try { s = JSON.parse(localStorage.getItem('racefietsen') || '{}'); } catch (_) {}
  return s;
}
function remember() {
  const s = {view, sort: $('sort').value, fmin: $('fmin').value, fmax: $('fmax').value, unk: $('unk').checked,
             pmax: $('pmax').value, km: $('km').value, nokm: $('nokm').checked, res: $('res').checked};
  try { localStorage.setItem('racefietsen', JSON.stringify(s)); } catch (_) {}
}
function restoreFilters() {
  const s = state();
  if (s.view) view = s.view;
  for (const k of ['sort', 'fmin', 'fmax', 'pmax', 'km']) if (s[k] != null && $(k)) $(k).value = s[k];
  for (const k of ['unk', 'nokm', 'res']) if (s[k] != null && $(k)) $(k).checked = s[k];
}

let modelFilter = '';
function inView(b) {
  if (modelFilter && b.mk !== modelFilter) return false;
  const bid = b.b.length > 0;
  if (view === 'open') return !b.m && !bid && !b.own && !b.res;
  if (view === 'fav') return b.m === 'favoriet';
  if (view === 'bids') return bid;
  if (view === 'away') return b.m === 'weg';
  if (view === 'all') return b.m !== 'weg';
  return true;
}
function passes(b) {
  if (view !== 'bids' && view !== 'fav' && b.res && !$('res').checked) return false;
  const q = $('q').value.trim().toLowerCase();
  if (q && !(b.t + ' ' + b.sp + ' ' + b.c + ' ' + b.no).toLowerCase().includes(q)) return false;
  const lo = parseFloat($('fmin').value), hi = parseFloat($('fmax').value);
  if (b.fr) { if ((!isNaN(lo) && b.fr[1] < lo) || (!isNaN(hi) && b.fr[0] > hi)) return false; }
  else if (!$('unk').checked) return false;
  const pmax = parseFloat($('pmax').value);
  if (!isNaN(pmax) && b.p != null && b.p > pmax) return false;
  if (HOME) {
    const km = parseFloat($('km').value);
    if (km < parseFloat($('km').max)) {
      if (b.km == null) { if (!$('nokm').checked) return false; }
      else if (b.km > km) return false;
    }
  }
  if ($('new').checked && !b.n) return false;
  return true;
}
const SORTS = {
  newest: (a, b) => (b.fs || '').localeCompare(a.fs || ''),
  flip: (a, b) => (b.fm ?? -1e9) - (a.fm ?? -1e9),
  value: (a, b) => (b.vr ?? -1) - (a.vr ?? -1),
  near: (a, b) => (a.km ?? 1e9) - (b.km ?? 1e9),
  upgrade: (a, b) => (b.uo - a.uo) || ((b.ug ?? -1e9) - (a.ug ?? -1e9)),
  cheap: (a, b) => (a.p ?? 1e9) - (b.p ?? 1e9),
};

const SOURCES = {eigen: 'eigen model', referentie: 'referentiemodel', automatisch: 'herkend uit de titel'};
function modelLine(b) {
  if (!b.grp) return '<span class="muted">aan geen model gekoppeld</span>';
  return `gekoppeld aan <a href="#" data-model="${esc(b.mk)}">${esc(b.grp)}</a> <span class="muted">(${esc(SOURCES[b.src] || b.src)})</span>`
    + (b.ok ? ' <span class="cheap">✓ gecontroleerd</span>' : '')
    + ` · ${b.lk} advertentie${b.lk === 1 ? '' : 's'}`;
}
// "6 snel verkocht (≤7 d), mediaan €620 · 14 te koop, mediaan €690 — deze €480 (−23%)"
function compareLine(b) {
  if (!b.lv) return '';
  const parts = [];
  if (b.sv[0]) parts.push(`<span class="fast">${b.sv[0]} snel verkocht</span> (≤7 d), mediaan ${euro(b.sv[1])}`);
  if (b.tk[0]) parts.push(`${b.tk[0]} te koop, mediaan ${euro(b.tk[1])}`);
  const cls = b.fg ? '' : b.pc <= -10 ? 'cheap' : b.pc >= 10 ? 'dear' : '';
  const pc = b.pc == null ? '' : ` — deze ${euro(b.p)} (<strong class="${cls}">${b.pc > 0 ? '+' : b.pc < 0 ? '−' : ''}${Math.abs(b.pc)}%</strong> t.o.v. de schatting)`;
  return `<div class="why">vergeleken op ${esc(b.lv)}: ${parts.join(' · ') || 'alleen verdwenen advertenties'}${pc}</div>`;
}
function fixRow(b) {
  return '<div class="row fix">'
    + (b.grp && !b.ok ? '<button class="quiet" data-do="klopt" title="het model klopt">klopt</button>' : '')
    + '<button class="quiet" data-do="ander" title="toets m">ander model</button>'
    + `<label>bouwjaar <input name="jaar" value="${b.yo ? esc(b.yr) : ''}" placeholder="${b.yr && !b.yo ? esc(b.yr) : 'onbekend'}" size="5" maxlength="4" inputmode="numeric" aria-label="Bouwjaar"></label>`
    + '<button class="quiet" data-do="jaar">opslaan</button>'
    + (b.lnk ? '<button class="quiet" data-do="ontkoppel" title="terug naar wat de advertentie zegt">ontkoppelen</button>' : '')
    + '</div><div class="picker" hidden></div>';
}
function modelSearch(q) {
  const words = fold(q).split(/\s+/).filter(Boolean);
  if (!words.length) return MODELS.slice();
  return MODELS.filter(m => { const n = m._f || (m._f = fold(m.n)); return words.every(w => n.includes(w)); });
}
const PICK_MAX = 300;
function fillPicker(box, q) {
  const hits = modelSearch(q);
  box.querySelector('.plist').innerHTML = hits.slice(0, PICK_MAX).map(m => `<button type="button" class="pick" data-do="kies" data-v="${esc(m.n)}">${esc(m.n)} <span class="muted">${m.lk} gekoppeld${m.s === 'eigen' ? ' · eigen' : ''}</span></button>`).join('')
    + (hits.length > PICK_MAX ? `<div class="muted">nog ${hits.length - PICK_MAX} — typ om te zoeken</div>` : '')
    + (hits.length ? '' : '<div class="muted">niets gevonden — maak hieronder een nieuw model</div>');
}
function openPicker(art) {
  const box = art.querySelector('.picker');
  if (!box.hidden) { box.hidden = true; return; }
  box.innerHTML = '<input type="search" name="mq" placeholder="zoek een model, bv. domane sl6" aria-label="Zoek een model"><div class="plist"></div>'
    + '<div class="row"><input name="nieuw" size="34" maxlength="80" placeholder="nieuw model: merk model uitvoering, bv. Koga Kinsei Pro" aria-label="Nieuw model">'
    + '<button class="quiet" data-do="nieuw">aanmaken en koppelen</button></div>';
  box.hidden = false;
  fillPicker(box, '');
  box.querySelector('input[name=mq]').focus();
}
function mergeModels(items) {
  for (const m of items || []) {
    const i = MODELS.findIndex(x => x.k === m.k);
    if (m.gone) { if (i >= 0) MODELS.splice(i, 1); modelByKey.delete(m.k); continue; }
    if (i >= 0) MODELS[i] = m; else MODELS.push(m);
    modelByKey.set(m.k, m);
  }
  if (view === 'models') drawModelRows();
}

function card(b) {
  const imgs = b.img.length ? b.img.map(u => `<a href="${esc(b.u)}" target="_blank" rel="noopener"><img src="${esc(u)}" alt="" loading="lazy"></a>`).join('')
    : '<div class="empty"></div>';
  const badges = (b.m === 'favoriet' ? '<span class="badge fav">★ favoriet</span> ' : '')
    + (b.m === 'weg' ? `<span class="badge reserved">weggezet (${esc(b.mr)})</span> ` : '')
    + (b.n ? '<span class="badge">nieuw</span> ' : '') + (b.res ? '<span class="badge reserved">gereserveerd</span> ' : '')
    + (b.promo ? `<span class="badge" title="betaalde promotie">${esc(b.promo.toLowerCase())}</span> ` : '')
    + (b.own ? `<span class="badge fav">✓ gekocht ${esc(b.own)}</span> ` : '');
  const km = b.km == null ? '' : `<span class="km">${b.kma ? 'ca. ' : ''}${b.km < 10 ? String(b.km).replace('.', ',') : Math.round(b.km)} km</span>`;
  const flip = b.fm == null ? '<span class="pill bad">flip —</span>'
    : `<span class="pill ${b.fm > 0 && !b.fg ? 'good' : 'bad'}" title="${esc(b.fb)}">flip ${signed(b.fm)}${b.fg ? ' (onzeker)' : ''}</span>`;
  const upg = b.uo ? `<span class="pill good" title="${esc(b.uw)}">upgrade +${b.ug}</span>`
    : `<span class="pill bad" title="${esc(b.uw)}">geen upgrade</span>`;
  const vr = b.vr == null ? '' : `<span class="pill ${b.vr >= 1.1 ? 'good' : ''}" title="geschatte waarde / prijs">waarde ${String(b.vr.toFixed(2)).replace('.', ',')}</span>`;
  const st = b.st ? `<div class="why">${b.st.v != null ? b.st.v + '× bekeken' : ''}${b.st.f != null ? ' · ' + b.st.f + '× bewaard' : ''}${b.st.df ? ` (${b.st.df > 0 ? '+' : ''}${b.st.df} sinds vorige meting)` : ''} · gemeten ${esc(b.st.at)}</div>` : '';
  const reasons = REASONS.map((r, i) => `<button class="quiet" data-do="weg" data-v="${esc(r)}" title="toets ${i + 1}">${esc(r)}</button>`).join('');
  const markBtns = b.m === 'weg' ? '<button class="quiet" data-do="geen">terugzetten</button>'
    : (b.m === 'favoriet' ? '<button class="quiet" data-do="geen">★ uit favorieten</button>' : '<button class="quiet" data-do="fav">☆ favoriet</button>')
      + '<span class="muted">weg:</span>' + reasons;
  const last = b.b.length ? b.b[b.b.length - 1] : null;
  const hist = b.b.map(x => `${euro(x.a)} op ${esc(x.at)}`).join(', ');
  const bidRow = `<div class="row bids">${last ? `<span>jouw bod: <span class="st">${euro(last.a)} — ${esc(last.s)}</span>${b.b.length > 1 ? ` <span class="muted">(${hist})</span>` : ''}</span>`
      + STATUSES.filter(s => s !== last.s).map(s => `<button class="quiet" data-do="status" data-v="${esc(s)}">${esc(s)}</button>`).join('') : ''}
    <label>€<input name="bod" inputmode="decimal" size="5" aria-label="Bod"></label><button class="quiet" data-do="bod">${last ? 'nieuw bod' : 'ik heb geboden'}</button></div>`;
  return `<article class="bike${b.m === 'weg' ? ' away' : ''}" data-id="${esc(b.id)}">
    <div class="photos">${imgs}</div>
    <div>
      <div class="top"><span class="price">${euro(b.p)}</span><span class="muted">${esc(b.pk)}${b.bi ? ' · ' + esc(b.bi) : ''}</span>${km}<span>${badges}</span></div>
      <a class="title" href="${esc(b.u)}" target="_blank" rel="noopener">${esc(b.t)}</a>
      <div class="link">${modelLine(b)}</div>
      ${compareLine(b)}
      ${fixRow(b)}
      <span class="muted">${esc(b.c)}</span>
      <div class="specs">${esc(b.sp) || '<span class="muted">geen specs in de advertentie</span>'}</div>
      <div class="verdicts">${flip}${upg}${vr}</div>
      <div class="why">${b.rs != null ? 'verkoop ca. ' + euro(b.rs) + ' — ' : ''}${esc(b.fb)}</div>
      <div class="why">${esc(b.uw)}</div>
      ${st}
      ${b.back ? `<div class="note">${esc(b.back)}</div>` : ''}
      ${b.no ? `<div class="mynote">${esc(b.no)}</div>` : ''}
      ${b.cmp.length ? `<details class="desc"><summary>vergeleken met ${b.nc} fietsen${b.nc > b.cmp.length ? ` (hier ${b.cmp.length}: de snel verkochte en de goedkoopste)` : ''}</summary><div>${b.cmp.map(c => `<a href="${esc(c[2])}" target="_blank" rel="noopener">${esc(c[0])}</a> — ${euro(c[1])}${c[3] ? ' · ' + c[3] : ''}${c[5] ? ' · <span class="fast">snel verkocht</span> ' + esc(c[4]) : c[4] ? ' · verdwenen ' + esc(c[4]) : ''}`).join('<br>')}</div></details>` : ''}
      <details class="desc"><summary>beschrijving</summary><div>${esc(b.d)}</div></details>
      <div class="row">${markBtns}<span class="muted">·</span><button class="quiet" data-do="check">controleer</button>${b.ck ? `<span class="muted">gecontroleerd ${esc(b.ck.replace('T', ' '))}</span>` : ''}</div>
      ${bidRow}
      <div class="row"><input name="notitie" value="${esc(b.no)}" maxlength="500" size="34" placeholder="notitie, bv. gevraagd of €300 kan" aria-label="Notitie"><button class="quiet" data-do="note">opslaan</button></div>
    </div></article>`;
}

function counts() {
  const n = {open: 0, fav: 0, bids: 0, all: 0, away: 0};
  const save = view;
  for (const k of Object.keys(n)) { view = k; n[k] = BIKES.filter(b => inView(b) && passes(b)).length; }
  view = save;
  n.bids += GONE.length;
  document.querySelectorAll('.views button[data-view]').forEach(bt => {
    const k = bt.dataset.view; if (k in n) bt.textContent = bt.dataset.label + ' (' + n[k] + ')';
  });
}
// De lijst met alle modellen: eigen, referentie en herkend, ook zonder
// advertenties; zoeken, sorteren op een kolom, en tekenen in porties.
const MODEL_COLS = [['n', 'Model'], ['a', 'Te koop'], ['lk', 'Gekoppeld'], ['f', 'Snel verkocht'], ['fm', 'Mediaan snel'],
                    ['m', 'Mediaan vraag'], ['lo', 'Laagste']];
const MODEL_BATCH = 200;
let modelSort = 'lk', modelDesc = true, modelRows = [], modelDrawn = 0;
function drawModels() {
  const box = $('modellist');
  if (!box.dataset.ready) {
    box.innerHTML = '<p class="explain">Elke fiets hangt aan een model: merk + model + uitvoering uit de titel ("Trek Domane SL6"), een referentiemodel uit reference_bikes.csv, of een model dat je zelf koppelde of aanmaakte (<em>eigen</em>). Klik op een model om zijn fietsen te zien. <em>Gekoppeld</em> telt ook verdwenen advertenties van de laatste 180 dagen; <em>snel verkocht</em> is binnen 7 dagen verdwenen of gereserveerd en daarna weg.</p>'
      + '<div class="row"><input id="newmodel" size="40" maxlength="80" placeholder="nieuw model toevoegen: merk model uitvoering, bv. Koga Kinsei Pro" aria-label="Nieuw model"><button class="quiet" id="addmodel">toevoegen</button></div>'
      + '<div class="row"><input type="search" id="msearch" size="30" placeholder="zoek een model" aria-label="Zoek een model"><span class="muted" id="mcount"></span></div>'
      + `<div class="table-wrap"><table><thead><tr>${MODEL_COLS.map(([k, l]) => `<th${k === 'n' ? '' : ' class="num"'} data-sort="${k}">${l}</th>`).join('')}</tr></thead><tbody id="mbody"></tbody></table></div>`;
    box.dataset.ready = '1';
    $('msearch').addEventListener('input', drawModelRows);
    $('addmodel').addEventListener('click', addModel);
    $('newmodel').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addModel(); } });
    box.querySelector('thead').addEventListener('click', e => {
      const th = e.target.closest('th[data-sort]'); if (!th) return;
      if (modelSort === th.dataset.sort) modelDesc = !modelDesc; else { modelSort = th.dataset.sort; modelDesc = modelSort !== 'n'; }
      drawModelRows();
    });
  }
  drawModelRows();
}
function drawModelRows() {
  if (!$('mbody')) return;
  const dir = modelDesc ? -1 : 1;
  modelRows = modelSearch($('msearch').value).sort((x, y) => {
    if (modelSort === 'n') return dir * fold(x.n).localeCompare(fold(y.n));
    const a = x[modelSort], b = y[modelSort];
    if (a == null || b == null) return a == null && b == null ? 0 : a == null ? 1 : -1;  // leeg altijd onderaan
    return dir * (a - b) || fold(x.n).localeCompare(fold(y.n));
  });
  $('modellist').querySelectorAll('th[data-sort]').forEach(th => {
    const label = MODEL_COLS.find(c => c[0] === th.dataset.sort)[1];
    th.textContent = label + (th.dataset.sort === modelSort ? (modelDesc ? ' ↓' : ' ↑') : '');
  });
  $('mbody').innerHTML = ''; modelDrawn = 0;
  $('mcount').textContent = modelRows.length + ' modellen';
  drawMoreModels();
}
function drawMoreModels() {
  const html = modelRows.slice(modelDrawn, modelDrawn + MODEL_BATCH).map(m =>
    `<tr><td><a href="#" data-model="${esc(m.k)}">${esc(m.n)}</a> <span class="muted">${m.s === 'automatisch' ? 'herkend' : esc(m.s)}</span></td>`
    + `<td class="num">${m.a}</td><td class="num">${m.lk}</td><td class="num">${m.f || ''}</td><td class="num">${m.fm == null ? '' : euro(m.fm)}</td>`
    + `<td class="num">${euro(m.m)}</td><td class="num">${euro(m.lo)}</td></tr>`).join('');
  $('mbody').insertAdjacentHTML('beforeend', html);
  modelDrawn = Math.min(modelDrawn + MODEL_BATCH, modelRows.length);
  more.hidden = modelDrawn >= modelRows.length;
  more.textContent = modelDrawn < modelRows.length ? `nog ${modelRows.length - modelDrawn} modellen — scroll verder` : '';
}
function addModel() {
  const input = $('newmodel'), v = input.value.trim();
  if (!v) { input.focus(); return; }
  post(MODEL_PATH, {model: v}).then(d => { if (d && d.models) input.value = ''; });
}
document.addEventListener('click', e => {
  const a = e.target.closest('a[data-model]'); if (!a) return;
  e.preventDefault();
  modelFilter = a.dataset.model;
  if (view === 'models' || view === 'patterns') view = 'all';
  document.querySelectorAll('.views button').forEach(x => x.classList.toggle('on', x.dataset.view === view));
  draw(); window.scrollTo(0, 0);
});
function draw() {
  shown = view === 'models' ? [] : BIKES.filter(b => inView(b) && passes(b)).sort(SORTS[$('sort').value] || SORTS.newest);
  list.innerHTML = ''; drawn = 0; cur = -1;
  $('modellist').hidden = view !== 'models';
  $('modelchip').hidden = !modelFilter;
  const chip = modelFilter ? ((modelByKey.get(modelFilter) || {}).n || (BIKES.find(b => b.mk === modelFilter) || {}).grp || modelFilter) : '';
  $('modelchip').innerHTML = modelFilter ? `model: <strong>${esc(chip)}</strong> <button class="quiet" id="nomodel">× alle modellen</button>` : '';
  if (modelFilter) $('nomodel').onclick = () => { modelFilter = ''; draw(); };
  $('patterns').hidden = view !== 'patterns';
  $('gonebids').hidden = view !== 'bids' || !GONE.length;
  list.hidden = view === 'patterns' || view === 'models';
  $('count').textContent = view === 'patterns' || view === 'models' ? '' : shown.length + ' fietsen';
  if (view === 'models') drawModels(); else drawMore();
  counts(); remember();
}
function drawMore() {
  if (view === 'models') { drawMoreModels(); return; }
  if (view === 'patterns') { more.hidden = true; return; }
  const html = shown.slice(drawn, drawn + BATCH).map(card).join('');
  list.insertAdjacentHTML('beforeend', html);
  drawn = Math.min(drawn + BATCH, shown.length);
  more.hidden = drawn >= shown.length;
  more.textContent = drawn < shown.length ? `nog ${shown.length - drawn} — scroll verder` : '';
}
new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) drawMore(); }, {rootMargin: '800px'}).observe(more);

function el(id) { return list.querySelector(`article[data-id="${CSS.escape(id)}"]`); }
function focusAt(i) {
  const cards = list.querySelectorAll('article.bike');
  if (!cards.length) { cur = -1; return; }
  cur = Math.max(0, Math.min(i, cards.length - 1));
  if (cur >= cards.length - 3 && drawn < shown.length) drawMore();
  cards.forEach((c, j) => c.classList.toggle('cur', j === cur));
  cards[cur].scrollIntoView({block: 'nearest'});
}
function curId() { const c = list.querySelectorAll('article.bike')[cur]; return c ? c.dataset.id : null; }

// Na een klik: de fiets vervangen, of weghalen als hij niet meer in deze weergave hoort.
function update(b) {
  if (!b) return;
  const i = BIKES.findIndex(x => x.id === b.id);
  if (i >= 0) BIKES[i] = b; else BIKES.push(b);
  byId.set(b.id, b);
  const old = el(b.id);
  if (old) {
    if (inView(b) && passes(b)) { old.outerHTML = card(b); }
    else {
      const idx = Array.from(list.children).indexOf(old);
      old.remove(); shown = shown.filter(x => x.id !== b.id); drawn--;
      if (idx <= cur) cur = Math.max(-1, cur - (idx < cur ? 1 : 0));
    }
  }
  $('count').textContent = shown.length + ' fietsen';
  counts();
  if (cur >= 0) focusAt(cur);
}
// toast, say() en pageData komen uit LIVE_JS (dashboard.py), net als de
// postcodeknop (een gewone .act, met herladen).
function post(path, fields, box) {
  const body = new URLSearchParams({token: pageData.token, markt: 'racefietsen', ...fields});
  if (box) box.classList.add('busy');
  return fetch(path, {method: 'POST', body, headers: {'X-Live': '1'}})
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(data => { if (data.reload) { location.reload(); return; } say(data.message); if (data.models) mergeModels(data.models); update(data.bike); return data; })
    .catch(() => say('Niet gelukt; ververs de pagina (F5) en probeer het opnieuw.'))
    .finally(() => { if (box) box.classList.remove('busy'); });
}
function act(id, what, value, art) {
  const b = byId.get(id); if (!b) return;
  if (what === 'fav') return post('/markeer', {item_id: id, soort: 'favoriet'}, art);
  if (what === 'weg') return post('/markeer', {item_id: id, soort: value}, art);
  if (what === 'geen') return post('/markeer', {item_id: id, soort: 'geen'}, art);
  if (what === 'check') return post('/controleer', {item_id: id}, art);
  if (what === 'note') return post('/notitie', {item_id: id, notitie: art.querySelector('input[name=notitie]').value}, art);
  if (what === 'bod') {
    const v = art.querySelector('input[name=bod]').value.trim();
    if (!v) { art.querySelector('input[name=bod]').focus(); return; }
    return post('/bod', {item_id: id, bedrag: v}, art);
  }
  if (what === 'status') return post('/bod/status', {item_id: id, status: value}, art);
  // Het model en het bouwjaar (bike_link): de server rekent alleen deze fiets opnieuw.
  if (what === 'klopt') return post(MODEL_PATH, {item_id: id, confirm: '1'}, art);
  if (what === 'ander') return openPicker(art);
  if (what === 'kies') return post(MODEL_PATH, {item_id: id, model: value}, art);
  if (what === 'nieuw') {
    const v = art.querySelector('input[name=nieuw]').value.trim();
    if (!v) { art.querySelector('input[name=nieuw]').focus(); return; }
    return post(MODEL_PATH, {item_id: id, model: v}, art);
  }
  if (what === 'jaar') return post(MODEL_PATH, {item_id: id, year: art.querySelector('input[name=jaar]').value.trim()}, art);
  if (what === 'ontkoppel') return post(MODEL_PATH, {item_id: id, clear: '1'}, art);
}
list.addEventListener('click', e => {
  const bt = e.target.closest('button[data-do]'); if (!bt) return;
  const art = bt.closest('article.bike');
  const cards = Array.from(list.querySelectorAll('article.bike'));
  cur = cards.indexOf(art); cards.forEach((c, j) => c.classList.toggle('cur', j === cur));
  act(art.dataset.id, bt.dataset.do, bt.dataset.v, art);
});
list.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || !e.target.matches('input')) return;
  e.preventDefault();
  const art = e.target.closest('article.bike');
  const what = {bod: 'bod', notitie: 'note', jaar: 'jaar', nieuw: 'nieuw'}[e.target.name];
  if (what) act(art.dataset.id, what, null, art);
});
list.addEventListener('input', e => { if (e.target.name === 'mq') fillPicker(e.target.closest('.picker'), e.target.value); });
document.addEventListener('keydown', e => {
  if (e.target.matches('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) {
    if (e.key === 'Escape') e.target.blur();
    return;
  }
  const k = e.key.toLowerCase();
  if (k === 'j' || e.key === 'ArrowDown') { e.preventDefault(); focusAt(cur + 1); return; }
  if (k === 'k' || e.key === 'ArrowUp') { e.preventDefault(); focusAt(cur - 1); return; }
  const id = curId(); if (!id) return;
  const art = el(id);
  if (k === 'f') act(id, byId.get(id).m === 'favoriet' ? 'geen' : 'fav', null, art);
  else if (k === 'w') act(id, 'weg', REASONS[0], art);
  else if (/^[1-9]$/.test(k) && REASONS[+k - 1]) act(id, 'weg', REASONS[+k - 1], art);
  else if (k === 'u') act(id, 'geen', null, art);
  else if (k === 'c') act(id, 'check', null, art);
  else if (k === 'm') { e.preventDefault(); act(id, 'ander', null, art); }
  else if (k === 'o') window.open(byId.get(id).u, '_blank', 'noopener');
  else if (k === 'b') { e.preventDefault(); art.querySelector('input[name=bod]').focus(); }
  else if (k === 'n') { e.preventDefault(); art.querySelector('input[name=notitie]').focus(); }
  else if (k === ' ') { e.preventDefault(); const d = art.querySelector('details.desc'); d.open = !d.open; }
});
document.querySelectorAll('.views button[data-view]').forEach(bt => bt.addEventListener('click', () => {
  view = bt.dataset.view;
  document.querySelectorAll('.views button').forEach(x => x.classList.toggle('on', x === bt));
  draw();
}));
const kmOut = $('kmval');
function kmLabel() { if (!kmOut) return; const v = +$('km').value; kmOut.textContent = v >= +$('km').max ? 'alles' : 'max ' + v + ' km'; }
['q', 'sort', 'fmin', 'fmax', 'unk', 'pmax', 'km', 'nokm', 'res', 'new'].forEach(id => $(id) && $(id).addEventListener('input', () => { kmLabel(); draw(); }));
restoreFilters(); kmLabel();
document.querySelectorAll('.views button').forEach(x => x.classList.toggle('on', x.dataset.view === view));
draw();
"""


def _finite(value):
    """NaN en oneindig als null: JSON kent ze niet, en één zo'n getal liet
    JSON.parse de hele pagina weigeren (een framemaat "60 cm of meer",
    30-09-2026)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


def page_json(data) -> str:
    """JSON veilig in een <script type=application/json>: `</` kan hem niet
    afsluiten, en er komt geen NaN/Infinity in."""
    return json.dumps(_finite(data), ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).replace("</", "<\\/")


def render(base: Base, fresh: Fresh, token: str = "", message: str = "") -> str:
    import dashboard as dash

    with base.lock:
        bikes = [bike_json(r, fresh) for r in base.rows]
        models = model_list(base)
    gone = gone_bids(base, fresh)
    lo, hi = ((base.target_cm - 2, base.target_cm + 2) if base.target_cm else (54, 58))
    notices = ""
    if message:
        notices += f"<div class='banner' role='status'>{esc(message)}</div>"
    if not base.rows:
        notices += ("<div class='banner'>Nog geen racefietsen in de database. Draai eerst een ronde: "
                    "<code>python koopjes.py run overdag</code>.</div>")
    if base.owner_problem:
        notices += (f"<div class='banner'>Geen upgradeoordeel: {esc(base.owner_problem)}</div>")
    home = fresh.home
    if home:
        where = (f"Afstand hemelsbreed vanaf <strong>{esc(home.postcode)}</strong>. ")
        km_filter = ("<label>Afstand <input type='range' id='km' min='5' max='250' step='5' value='250'> "
                     "<output id='kmval'></output></label>"
                     "<label><input type='checkbox' id='nokm' checked> ook zonder plek</label>")
    else:
        where = "Nog geen postcode: vul hem in om op afstand te filteren en te sorteren. "
        km_filter = "<input type='hidden' id='km' value='250' max='250'><input type='checkbox' id='nokm' hidden checked>"
    postcode = (dash.act("/afstand", "postcode",
                         f"<span class='muted'>{where}</span><input name='postcode' size='7' "
                         f"value='{esc(home.postcode if home else '', quote=True)}' placeholder='bv. 3511AB' "
                         "aria-label='Postcode'><button class='quiet'>opslaan</button>")
                if token else "")
    views_bar = "".join(
        f"<button data-view='{k}' data-label='{esc(label)}'>{esc(label)}</button>"
        for k, label in (("open", "Te beoordelen"), ("fav", "Favorieten"), ("bids", "Mijn biedingen"),
                         ("all", "Alle"), ("away", "Weggezet"), ("models", "Modellen"), ("patterns", "Patronen")))
    sort = ("<select id='sort' aria-label='Volgorde'>"
            "<option value='newest'>Nieuwste eerst</option><option value='flip'>Beste flip eerst</option>"
            "<option value='value'>Beste waardescore eerst</option><option value='upgrade'>Beste upgrade eerst</option>"
            f"<option value='near'{'' if home else ' disabled'}>Dichtstbij eerst</option>"
            "<option value='cheap'>Goedkoopste eerst</option></select>")
    reasons_keys = " ".join(f"<kbd>{i}</kbd> {esc(r)}" for i, r in enumerate(mr.BIKE_REASONS, start=1))
    gone_html = "".join(
        f"<li><a href='{esc(g['u'], quote=True)}' target='_blank' rel='noopener'>{esc(g['t'])}</a> — "
        + ", ".join(f"€{b['a']:.0f} op {esc(b['at'])} ({esc(b['s'])})" for b in g["b"])
        + f" <span class='muted'>{'verdwenen ' + esc(g['gone']) if g['gone'] else 'laatst gezien ' + esc(g['last'])}</span></li>"
        for g in gone)
    meta = (f"{len(base.rows)} racefietsen te koop · laatste ronde {esc(dash.local_time(base.newest)) if base.newest else '—'}"
            + (" · <strong>live</strong> (wijzigingen gaan in koopjes.db)" if token else ""))
    return (
        "<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Racefietsen</title><style>{dash.CSS}{dash.SITE_CSS}{CSS}</style></head><body>"
        f"<main data-token='{esc(token, quote=True)}' data-markt='{MARKET_KEY}'>"
        f"{dash.site_nav(PATH) if token else ''}<h1>Racefietsen op Marktplaats</h1>"
        f"<div class='meta'>{meta}</div>{notices}{postcode}"
        "<div class='bar'>"
        f"<div class='views'>{views_bar}</div>"
        "<div class='filters'>"
        "<input type='search' id='q' placeholder='Zoek in titel, specs, plaats, notitie' aria-label='Zoeken'>"
        f"{sort}"
        f"<label>Maat <input type='number' id='fmin' value='{lo:.0f}' aria-label='Maat van'>–"
        f"<input type='number' id='fmax' value='{hi:.0f}' aria-label='Maat tot'> cm</label>"
        "<label><input type='checkbox' id='unk' checked> maat onbekend</label>"
        "<label>Max €<input type='number' id='pmax' aria-label='Maximale prijs'></label>"
        f"{km_filter}"
        "<label><input type='checkbox' id='res'> gereserveerd</label>"
        "<label><input type='checkbox' id='new'> alleen nieuw</label>"
        "<span class='muted' id='count'></span></div>"
        "<div class='keys'>Toetsen: <kbd>j</kbd>/<kbd>↓</kbd> volgende · <kbd>k</kbd>/<kbd>↑</kbd> vorige · "
        f"<kbd>f</kbd> favoriet · <kbd>w</kbd> niet waard · {reasons_keys} · <kbd>u</kbd> terugzetten · "
        "<kbd>b</kbd> bod invullen · <kbd>n</kbd> notitie · <kbd>spatie</kbd> beschrijving · "
        "<kbd>o</kbd> openen op Marktplaats · <kbd>c</kbd> controleer · <kbd>m</kbd> ander model · "
        "<kbd>Esc</kbd> uit een invulveld</div>"
        "</div>"
        "<div id='modelchip' class='row' hidden></div>"
        f"<div id='list' data-home='{1 if home else 0}'></div><section id='modellist' hidden></section><div id='more'></div>"
        f"<div id='gonebids' hidden><h3>Biedingen op fietsen die niet meer online zijn</h3><ul>{gone_html}</ul></div>"
        f"<section id='patterns' hidden>{vw.patterns_html(base.patterns or vw.ViewPatterns(), 'racefietsen')}</section>"
        f"<script type='application/json' id='bikes'>{page_json(bikes)}</script>"
        f"<script type='application/json' id='models'>{page_json(models)}</script>"
        f"<script type='application/json' id='gone'>{page_json(gone)}</script>"
        f"<script type='application/json' id='reasons'>{page_json(list(mr.BIKE_REASONS))}</script>"
        f"<script type='application/json' id='statuses'>{page_json(list(ob.STATUSES))}</script>"
        f"</main><div id='toast' role='status' hidden></div><script>{dash.LIVE_JS}{JS}</script>"
        "</body></html>")


def bike_update(base: Base, fresh: Fresh, item_id: str, message: str) -> dict:
    with base.lock:
        row = base.row(item_id)
        return {"message": message, "bike": bike_json(row, fresh) if row else None}


def model_update(base: Base, db_path, form: dict) -> dict:
    """Het antwoord op MODEL_PATH: de bijgewerkte fiets en de regels van de
    modellen die veranderden, zodat de pagina zonder herladen klopt."""
    try:
        message, row, keys = apply_model(base, db_path, form)
    except ModelError as exc:
        return {"message": f"Niet opgeslagen: {exc}"}
    data = {"message": message, "models": model_list(base, keys)}
    if row is not None:
        data["bike"] = bike_json(row, load_fresh(db_path))
    return data


def find_listing(db_path, item_id: str) -> Optional[mp.Listing]:
    listings, _, _ = load_listings(db_path)
    return next((l for l in listings if l.item_id == item_id), None)


def resale_for(db_path, item_id: str) -> Optional[float]:
    """De flipschatting van één fiets (verwachte verkoopprijs), zonder het
    upgradedeel: voor de doelprijs van een geaccepteerd bod op /flips."""
    read = _read(db_path)
    listings, _, _ = load_listings(db_path, _read_result=read)
    listing = next((l for l in listings if l.item_id == item_id), None)
    if listing is None:
        return None
    est = estimate(listing, bi.identify(listing, read.links.get(item_id)), load_pool(db_path, _read_result=read),
                   val.NEGOTIATION_DEFAULT[1])
    return None if est.resale is None else round(est.resale, 2)
