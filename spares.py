"""Reserves voor het flippen: losse fietsonderdelen die de rondes toch al
tegenkomen, per soort (cassettes, kettingen, zadels, pedalen, ...), op
/racefietsen in de weergave Onderdelen.

Waarom (de eigenaar, 02-10-2026): "fietsonderdelen die er doorheen komen die
wel handig zijn als vervanging of extra's, zodat ik ze kan gebruiken voor
het flippen — meteen kunnen zeggen voor welke spullen ik reserves nodig heb,
aka cassettes, kettingen, zadels, pedalen". Hij kiest de soorten zelf (aan
of uit, bewaard in `setting`), en per soort staan de goedkoopste die nu te
koop zijn.

Alleen wat al binnenkomt (zijn keuze): er komt geen zoekopdracht bij. De
rondes zoeken vooral hele racefietsen; losse onderdelen zijn wat er tussen
de racefietsen staat en wat de zoekopdrachten met `category: alle`
(giant-defy) en de powermeter-zoekopdracht vinden. Dat zijn er weinig. Meer
kan met een zoekopdracht in de categorie fietsonderdelen in schedule.json —
dat zijn extra verzoeken, dus eerst afwegen (README → Racefietsen).

Herkenning op de titel: een soort als hij het woord noemt ("cassette",
"pedalen", "zadel" maar niet "zadelpen"). Buiten de categorie
fietsonderdelen telt een titel die op een hele fiets lijkt ("racefiets",
"maat 56") niet mee: "Giant Defy met nieuwe cassette" is een fiets. Gezocht-
advertenties tellen nooit mee. Alleen lezen; bieden doet de eigenaar zelf.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import db
import racefiets_jev as mp

# (sleutel, wat de pagina zegt, patroon op de titel in kleine letters).
# Volgorde = volgorde op de pagina.
KINDS = (
    ("cassette", "Cassettes", r"\bcassettes?\b"),
    ("ketting", "Kettingen", r"\bkettin(?:g|gen)\b|\bchain\b"),
    ("zadel", "Zadels", r"\bzadels?\b|\bsaddle\b"),
    ("pedalen", "Pedalen", r"\bpeda(?:len|al|ls?)\b|\bspd(?:-sl)?\b|\blook keo\b"),
    ("banden", "Buitenbanden", r"\b(?:buiten|vouw)band(?:en)?\b|\b(?:race)?banden\b|\b700\s?x\s?2\d\s?c?\b"),
    ("binnenbanden", "Binnenbanden", r"\bbinnenband(?:en)?\b"),
    ("wielen", "Wielen", r"\bwiel(?:en|set|sets)\b|\b(?:voor|achter)wiel\b"),
    ("kettingblad", "Kettingbladen en cranks", r"\bkettingbla(?:d|den)\b|\bcrank(?:stel|set|s|arm)?\b"),
    ("derailleur", "Derailleurs", r"\b(?:voor|achter)?derailleurs?\b"),
    ("shifters", "Shifters en remgrepen", r"\bshifters?\b|\b(?:schakel|rem)grepen\b|\bst-[0-9r]"),
    ("remmen", "Remmen en remblokken", r"\bremblok(?:ken)?\b|\bremmen\b|\bremklauw(?:en)?\b"),
    ("groepset", "Groepsets", r"\bgroep(?:set)?\b|\bgroupset\b"),
    ("stuur", "Sturen en stuurpennen", r"\bstuur(?:pen)?\b|\bracestuur\b"),
    ("zadelpen", "Zadelpennen", r"\bzadelpen(?:nen)?\b|\bseatpost\b"),
    ("stuurlint", "Stuurlint", r"\bstuurlint\b|\bbar ?tape\b"),
    ("bidonhouder", "Bidonhouders", r"\bbidonhouders?\b"),
)
KIND_RE = {key: re.compile(pattern) for key, _, pattern in KINDS}
LABELS = {key: label for key, label, _ in KINDS}
# Wat de eigenaar als voorbeeld noemde: aan tot hij zelf kiest.
DEFAULT_ON = ("cassette", "ketting", "zadel", "pedalen")
SETTING_KEY = "reserve_soorten"

# Een titel die een hele fiets is, buiten de categorie onderdelen.
BIKE_RE = re.compile(r"\b(?:race|heren|dames|sport|stads|e-?)?fiets\b|\bracer\b|\bmaat\s?\d|\b[4-6]\d\s?cm\b|\bframemaat\b")
WANTED_RE = re.compile(r"\b(?:zoek|zoeke|gezocht|gevraagd|wanted|wie\s+heeft|ruilen)\b")
# Geen reserveonderdeel: gereedschap direct achter het onderdeel
# ("cassettesleutel", "kettingzweep" — maar "cassette met afnemer" is een
# cassette), houders ("Garmin houder voor stuur") en schoenen ("SPD"; wel
# pedalen met schoenplaatjes).
NOT_A_PART_RE = re.compile(
    r"\b(?:cassette|ketting|kettingblad|crank|trapas|pedaal|pedalen)[\s-]?"
    r"(?:sleutel|afnemer|zweep|pons|tool|gereedschap)|\b(?:houder|mount|beugel)\b|schoen(?:en)?\b")
MAIN_RE = re.compile(r"/v/([^/]+)/([^/]+)/")
PARTS_CATEGORIES = ("fietsonderdelen",)
SKIP_CATEGORIES = ("fietsaccessoires-fietscomputers", "fietsaccessoires-fietskleding")
# Zoveel per soort naar de pagina, de goedkoopste.
PER_KIND = 40
ACTIVE_DAYS = 8  # zoals racebikes.ACTIVE_DAYS


def kinds_of(title: str, category: str) -> list[str]:
    """De soorten die een titel noemt; leeg als het een hele fiets of een
    gezocht-advertentie is."""
    text = (title or "").lower()
    if WANTED_RE.search(text) or NOT_A_PART_RE.search(text):
        return []
    if category not in PARTS_CATEGORIES and BIKE_RE.search(text):
        return []
    return [key for key, _, _ in KINDS if KIND_RE[key].search(text)]


@dataclass
class Part:
    listing: mp.Listing
    kinds: list = field(default_factory=list)
    category: str = ""


def _time(value) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


SELECT = (
    "SELECT item_id, title, description, price_eur, price_type, is_bid, price_is_asking, city, posted_date, "
    "condition, frame_height, url, first_seen, last_seen, image_urls, reserved_at, bid_count, bid_minimum, "
    "bid_high, bids_checked_at, checked_at, full_description, disappeared_at, days_online "
    "FROM listing WHERE disappeared_at IS NULL AND url LIKE '%/v/fietsen-en-brommers/%'")


def load(db_path, item_id: Optional[str] = None) -> list[Part]:
    """Alle onderdelen die nu te koop zijn (gezien binnen ACTIVE_DAYS van de
    nieuwste in deze hoofdcategorie), met hun soorten. `item_id`: alleen die."""
    import racebikes as rb

    if not Path(db_path).exists():
        return []
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        newest = conn.execute("SELECT MAX(last_seen) FROM listing WHERE disappeared_at IS NULL AND "
                              "url LIKE '%/v/fietsen-en-brommers/%'").fetchone()[0]
        rows = conn.execute(SELECT + (" AND item_id = ?" if item_id else ""),
                            (item_id,) if item_id else ()).fetchall()
        tables = {t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        places = db.list_places(conn) if "listing_place" in tables and not item_id else {}
        if item_id and "listing_place" in tables:
            place = conn.execute("SELECT latitude, longitude, promotion, traits FROM listing_place WHERE item_id = ?",
                                 (item_id,)).fetchone()
            places = {item_id: tuple(place)} if place else {}
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    newest = _time(newest)
    if newest is None:
        return []
    since = newest - timedelta(days=ACTIVE_DAYS)
    out = []
    for r in rows:
        match = MAIN_RE.search(r["url"] or "")
        category = match.group(2) if match else ""
        if category in SKIP_CATEGORIES:
            continue
        last = _time(r["last_seen"])
        if last is None or last < since:
            continue
        kinds = kinds_of(r["title"], category)
        if not kinds:
            continue
        out.append(Part(rb._listing(r, {}, places), kinds, category))
    return out


def find_listing(db_path, item_id: str) -> Optional[mp.Listing]:
    """Eén onderdeel dat nu te koop is (voor favoriet/weg op /racefietsen)."""
    found = load(db_path, item_id)
    return found[0].listing if found else None


def cheapest(parts: list, per_kind: int = PER_KIND) -> list[Part]:
    """Per soort de `per_kind` goedkoopste met een prijs; een onderdeel dat
    bij twee soorten hoort komt één keer terug."""
    chosen: dict = {}
    for key, _, _ in KINDS:
        priced = sorted((p for p in parts if key in p.kinds and p.listing.price_eur and p.listing.price_eur > 0),
                        key=lambda p: (p.listing.price_eur, p.listing.item_id))
        for p in priced[:per_kind]:
            chosen[p.listing.item_id] = p
    return sorted(chosen.values(), key=lambda p: (p.listing.price_eur, p.listing.item_id))


def load_choice(db_path) -> list[str]:
    """De soorten die de eigenaar aanzette (setting), anders DEFAULT_ON."""
    if not Path(db_path).exists():
        return list(DEFAULT_ON)
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        raw = db.get_setting(conn, SETTING_KEY)
    except sqlite3.Error:
        raw = None
    finally:
        conn.close()
    try:
        chosen = json.loads(raw) if raw else None
    except ValueError:
        chosen = None
    if not isinstance(chosen, list):
        return list(DEFAULT_ON)
    return [k for k, _, _ in KINDS if k in chosen]


def save_choice(db_path, kinds) -> list[str]:
    clean = [k for k, _, _ in KINDS if k in set(kinds)]
    conn = db.connect(str(db_path))
    try:
        db.set_setting(conn, SETTING_KEY, json.dumps(clean))
    finally:
        conn.close()
    return clean
