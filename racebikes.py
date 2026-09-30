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

- **flip**: geschatte verkoopprijs − wat hij kost. De verkoopprijs is die
  van upgrade.estimate_value(): de mediaan-vraagprijs van vergelijkbare
  fietsen (zelfde framemateriaal, groepsettier en remtype) maal de
  afdingfactor, en zonder vergelijkbare fietsen grof de mediaan van alles
  (dan staat er "grof"). Geen kosten eraf: onderdelen en reizen zoekt de
  eigenaar per fiets uit, op /flips.
- **upgrade**: upgrade.find_upgrades() tegen de eigen fiets uit
  mijn_fiets.md, precies als het tabblad Upgrade van het rapport: beter
  dan de eigen fiets, binnen het budget, maat niet fout.

Plus de waardescore (upgrade.value_score(): waarde / prijs). Niet de
dealscore; die hoort bij het rapport (CLAUDE.md: twee scores, niet
vermengen).

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

import html
import json
import math
import sqlite3
import statistics
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
    linked: int = 0  # advertenties aan hetzelfde model (referentie of merk+model)
    median: Optional[float] = None  # mediaan-vraagprijs van de vergelijkingsfietsen
    level: str = ""  # welke trede van bike_identity.comparables() de schatting gaf
    comps: list = field(default_factory=list)  # (titel, prijs, url, jaar, verdwenen), goedkoopste eerst


@dataclass
class Base:
    rows: list = field(default_factory=list)
    newest: str = ""
    owner_problem: str = ""
    baseline: Optional[float] = None
    target_cm: Optional[float] = None
    patterns: Optional[vw.ViewPatterns] = None

    def row(self, item_id: str) -> Optional[Row]:
        return next((r for r in self.rows if r.listing.item_id == item_id), None)


def _time(value) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


SELECT = (
    "SELECT item_id, title, description, price_eur, price_type, is_bid, price_is_asking, city, "
    "posted_date, condition, frame_height, url, first_seen, last_seen, image_urls, reserved_at, "
    "bid_count, bid_minimum, bid_high, bids_checked_at, checked_at, full_description, disappeared_at "
    "FROM listing WHERE url LIKE ?")
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


def _read(db_path) -> tuple[list, dict, dict]:
    if not Path(db_path).exists():
        return [], {}, {}
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(SELECT, (f"%/{CATEGORY}/%",)).fetchall()
        return rows, db.read_listing_specs(conn, source=db.SITE_SPEC_SOURCE), db.list_places(conn)
    except sqlite3.Error:
        return [], {}, {}
    finally:
        conn.close()


def load_listings(db_path, active_days: int = ACTIVE_DAYS, _read_result=None) -> tuple[list, Optional[datetime], set]:
    """(advertenties, nieuwste waarneming, id's van de nieuwe) in de categorie
    racefietsen, met alles wat de database erover weet."""
    rows, site, places = _read_result or _read(db_path)
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


def load_pool(db_path, _read_result=None) -> bi.Pool:
    """Alle racefietsen van de laatste POOL_DAYS met een vraagprijs, ook
    verdwenen, als (Identity, prijs, (item_id, titel, url, verdwenen))."""
    rows, site, places = _read_result or _read(db_path)
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
        items.append((bi.identify(listing), listing.price_eur, (listing.item_id, listing.title, listing.url, gone)))
    return bi.Pool(items)


def estimate(listing: mp.Listing, ident: bi.Identity, pool: bi.Pool, factor: float) -> tuple:
    """(verwachte verkoopprijs, onderbouwing, trede, vergelijkingsfietsen) —
    de mediaan-vraagprijs van hetzelfde model uit dezelfde jaren maal de
    afdingfactor (bike_identity.comparables())."""
    level, found = pool.comparables(ident, listing.item_id)
    if not found:
        why = ("te weinig vergelijkbare fietsen van hetzelfde model en dezelfde jaren"
               if ident.model else "model niet herkend in de titel")
        return None, why, "", [], None
    prices = [c[1] for c in found]
    median = statistics.median(prices)
    years = sorted(c[0].year for c in found if c[0].year)
    span = (f" uit {years[0]}-{years[-1]}" if years and years[0] != years[-1]
            else f" uit {years[0]}" if years else "")
    what = {"referentiemodel+jaar": ident.reference, "referentiemodel": ident.reference,
            "model+jaar": ident.model, "model+tijdperk": f"{ident.model} ({'schijfrem' if ident.disc else 'velgrem'}"
            f"{', elektronisch' if ident.electronic else ''})",
            "opbouw+jaar": f"{ident.material}, groepsettier {ident.tier}, "
                           f"{'schijfrem' if ident.disc else 'velgrem'}",
            "model, jaar onbekend": ident.model}[level]
    basis = f"mediaan van {len(found)} × {what}{span}: €{median:.0f} × {val.dutch(factor)}"
    if level in bi.UNCERTAIN_LEVELS:
        basis = (f"onzeker, bouwjaar en remtype onbekend — {len(found)} × {what} van €{min(prices):.0f} tot "
                 f"€{max(prices):.0f}, mediaan €{median:.0f} × {val.dutch(factor)}; vraag het jaar na")
    comps = sorted(((c[2][1], c[1], c[2][2], c[0].year, c[2][3]) for c in found), key=lambda c: c[1])
    return median * factor, basis, level, comps, median


def specs_line(listing: mp.Listing) -> str:
    specs, _ = up.listing_specs(listing)
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


def build_base(db_path, intake_path, comps: Optional[list] = None) -> Base:
    """Het zware deel: per fiets flip, waardescore en upgrade. `comps`: de
    vergelijkingskandidaten voor de taxatie van de eigen fiets, als de
    aanroeper ze al heeft (LiveCache)."""
    import report

    read = _read(db_path)
    listings, newest, new_ids = load_listings(db_path, _read_result=read)
    base = Base(newest=newest.isoformat(timespec="minutes") if newest else "")
    base.patterns = vw.load_patterns(db_path, (CATEGORY,))
    if not listings:
        return base
    factor = val.NEGOTIATION_DEFAULT[1]
    pool = load_pool(db_path, _read_result=read)

    owner, problem = report.load_owner_context(str(intake_path), str(db_path), comps=comps)
    verdicts: dict[str, tuple] = {}
    if owner is None or owner.budgets is None or owner.target_size_cm is None:
        base.owner_problem = problem or (owner.valuation_problem if owner else "") or "geen eigen fiets"
    else:
        base.baseline, base.target_cm = owner.quality.total, owner.target_size_cm
        result = up.find_upgrades(
            listings, baseline=owner.quality.total, config=owner.config, budgets=owner.budgets,
            target_size_cm=owner.target_size_cm,
            owner_wheels=(owner.build.wheel_material, owner.build.wheel_branded),
            owner_already_has=owner.owner_has)
        for c in result.candidates:
            verdicts[c.listing.item_id] = (
                True, c.gain,
                f"+{c.gain:.0f} punten ({c.quality.total:.0f} tegen {owner.quality.total:.0f}), "
                f"€{c.effective.amount:.0f} binnen {c.budget.route}budget €{c.budget.amount:.0f}")
        for r in result.rejected:
            verdicts[r.listing.item_id] = (False, None, r.reason)

    for l in listings:
        ident = pool.identity_of.get(l.item_id) or bi.identify(l)
        resale, basis, level, comps, median = estimate(l, ident, pool, factor)
        entry = up.entry_price(l)
        margin = resale - entry.amount if resale is not None and entry.amount is not None else None
        price = up.effective_price(l, factor).amount
        ratio = resale / price if resale is not None and price else None
        ok, gain, why = verdicts.get(l.item_id, (False, None, base.owner_problem))
        if ok and ident.year is None:
            # Zonder bouwjaar rekent de score de fiets als nieuw (geen
            # leeftijdsverval): een oude fiets met goede onderdelen leek dan
            # een upgrade (de eigenaar, 30-09-2026: "upgrade-oordeel raar").
            ok, why = False, f"bouwjaar onbekend — als hij nieuw zou zijn {why}; vraag het jaar na"
        base.rows.append(Row(
            listing=l, frame=mp.frame_height_bounds(l.frame_height), specs=specs_line(l),
            text=l.detail_text or l.description, new=l.item_id in new_ids,
            flip_margin=margin, resale=resale, flip_basis=basis, flip_rough=level in bi.UNCERTAIN_LEVELS,
            value_ratio=ratio, upgrade_ok=ok, upgrade_gain=gain, upgrade_why=why,
            identity=ident, level=level, comps=comps, linked=pool.linked(ident), median=median))
    return base


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
        "mdl": r.identity.label() if r.identity else "",
        "grp": (r.identity.group or "") if r.identity else "",
        "ref": bool(r.identity and r.identity.reference),
        "lk": r.linked,
        # Vraagprijs tegen de mediaan van de vergelijkingsfietsen: -25 = 25% goedkoper.
        "pc": (round((l.price_eur / r.median - 1) * 100) if r.median and l.price_eur else None),
        "cmp": [[t, p, u, y, g] for t, p, u, y, g in r.comps[:12]],
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
@media (max-width: 760px) { .bike { grid-template-columns: 1fr; } .photos { height: 200px; } }
"""

JS = r"""
window.addEventListener('error', e => {
  const box = document.getElementById('more');
  if (box) { box.hidden = false; box.textContent = 'De pagina kon de fietsen niet tonen: ' + e.message; }
});
const BIKES = JSON.parse(document.getElementById('bikes').textContent);
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
  if (modelFilter && b.grp !== modelFilter) return false;
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
      <div class="link">${b.grp ? `gekoppeld aan <a href="#" data-model="${esc(b.grp)}">${esc(b.grp)}</a>${b.ref ? ' <span class="muted">(referentiemodel)</span>' : ''} · ${b.lk} advertentie${b.lk === 1 ? '' : 's'}` : '<span class="muted">aan geen model gekoppeld</span>'}${b.pc != null ? ` · <strong class="${b.pc <= -10 ? 'cheap' : b.pc >= 10 ? 'dear' : ''}">${b.pc > 0 ? '+' : ''}${b.pc}%</strong> t.o.v. de mediaan` : ''}</div>
      <span class="muted">${esc(b.c)}</span>
      <div class="specs">${esc(b.sp) || '<span class="muted">geen specs in de advertentie</span>'}</div>
      <div class="verdicts">${flip}${upg}${vr}</div>
      <div class="why">${b.rs != null ? 'verkoop ca. ' + euro(b.rs) + ' — ' : ''}${esc(b.fb)}</div>
      <div class="why">${esc(b.uw)}</div>
      ${st}
      ${b.back ? `<div class="note">${esc(b.back)}</div>` : ''}
      ${b.no ? `<div class="mynote">${esc(b.no)}</div>` : ''}
      ${b.cmp.length ? `<details class="desc"><summary>vergeleken met ${b.cmp.length === 12 ? '12+' : b.cmp.length} fietsen</summary><div>${b.cmp.map(c => `<a href="${esc(c[2])}" target="_blank" rel="noopener">${esc(c[0])}</a> — ${euro(c[1])}${c[3] ? ' · ' + c[3] : ''}${c[4] ? ' · verdwenen ' + esc(c[4]) : ''}`).join('<br>')}</div></details>` : ''}
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
function drawModels() {
  // Per model: hoeveel er te koop staan (na de filters), mediaan en laagste prijs.
  const groups = new Map();
  BIKES.filter(b => b.grp && passes(b)).forEach(b => {
    if (!groups.has(b.grp)) groups.set(b.grp, {ref: b.ref, prices: [], lk: b.lk});
    if (b.p != null) groups.get(b.grp).prices.push(b.p);
  });
  const rows = Array.from(groups.entries()).sort((a, b) => b[1].prices.length - a[1].prices.length).map(([g, v]) => {
    const p = v.prices.slice().sort((x, y) => x - y);
    const med = p.length ? p[Math.floor(p.length / 2)] : null;
    return `<tr><td><a href="#" data-model="${esc(g)}">${esc(g)}</a>${v.ref ? ' <span class="muted">referentie</span>' : ''}</td>`
      + `<td class="num">${p.length}</td><td class="num">${v.lk}</td><td class="num">${euro(med)}</td><td class="num">${euro(p[0])}</td></tr>`;
  }).join('');
  $('models').innerHTML = `<p class="explain">Elke fiets hangt aan een referentiemodel uit reference_bikes.csv of anders aan merk + model uit de titel. Klik op een model om alleen die fietsen te zien. <em>Gekoppeld</em> telt ook verdwenen advertenties van de laatste 180 dagen: daarmee wordt vergeleken.</p>`
    + `<div class="table-wrap"><table><thead><tr><th>Model</th><th class="num">Te koop</th><th class="num">Gekoppeld</th><th class="num">Mediaan</th><th class="num">Laagste</th></tr></thead><tbody>${rows}</tbody></table></div>`;
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
  $('models').hidden = view !== 'models';
  if (view === 'models') drawModels();
  $('modelchip').hidden = !modelFilter;
  $('modelchip').innerHTML = modelFilter ? `model: <strong>${esc(modelFilter)}</strong> <button class="quiet" id="nomodel">× alle modellen</button>` : '';
  if (modelFilter) $('nomodel').onclick = () => { modelFilter = ''; draw(); };
  $('patterns').hidden = view !== 'patterns';
  $('gonebids').hidden = view !== 'bids' || !GONE.length;
  list.hidden = view === 'patterns' || view === 'models';
  $('count').textContent = view === 'patterns' || view === 'models' ? '' : shown.length + ' fietsen';
  drawMore(); counts(); remember();
}
function drawMore() {
  if (view === 'patterns' || view === 'models') { more.hidden = true; return; }
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
    .then(data => { if (data.reload) { location.reload(); return; } say(data.message); update(data.bike); return data; })
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
  act(art.dataset.id, e.target.name === 'bod' ? 'bod' : 'note', null, art);
});
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

    bikes = [bike_json(r, fresh) for r in base.rows]
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
        "<kbd>o</kbd> openen op Marktplaats · <kbd>c</kbd> controleer · <kbd>Esc</kbd> uit een invulveld</div>"
        "</div>"
        "<div id='modelchip' class='row' hidden></div>"
        f"<div id='list' data-home='{1 if home else 0}'></div><div id='more'></div><section id='models' hidden></section>"
        f"<div id='gonebids' hidden><h3>Biedingen op fietsen die niet meer online zijn</h3><ul>{gone_html}</ul></div>"
        f"<section id='patterns' hidden>{vw.patterns_html(base.patterns or vw.ViewPatterns(), 'racefietsen')}</section>"
        f"<script type='application/json' id='bikes'>{page_json(bikes)}</script>"
        f"<script type='application/json' id='gone'>{page_json(gone)}</script>"
        f"<script type='application/json' id='reasons'>{page_json(list(mr.BIKE_REASONS))}</script>"
        f"<script type='application/json' id='statuses'>{page_json(list(ob.STATUSES))}</script>"
        f"</main><div id='toast' role='status' hidden></div><script>{dash.LIVE_JS}{JS}</script>"
        "</body></html>")


def bike_update(base: Base, fresh: Fresh, item_id: str, message: str) -> dict:
    row = base.row(item_id)
    return {"message": message, "bike": bike_json(row, fresh) if row else None}


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
    resale, _, _, _, _ = estimate(listing, bi.identify(listing), load_pool(db_path, _read_result=read),
                               val.NEGOTIATION_DEFAULT[1])
    return None if resale is None else round(resale, 2)
