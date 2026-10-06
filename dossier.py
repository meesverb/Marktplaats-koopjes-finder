"""Een dossier van één racefiets om aan Claude te geven: de knop dossier op
/racefietsen (`python dashboard.py --serve`) of `python dossier.py <id>`.

Waarom (de eigenaar, 06-10-2026): "net als met de knop controleer, alle
relevante data van die bepaalde fiets krijgen zodat ik dat aan Claude kan
geven om alles te checken: of het een goede deal is, wat er vernieuwd moet
worden, en wat data-analyse over de vergelijkingen". De kaart toont maar een
deel: de schatting in één zin, 12 vergelijkingsfietsen, het fragment van de
omschrijving. Hier staat alles wat de database over de fiets en zijn
vergelijkingsfietsen weet, als Markdown met de vergelijkingen als CSV, en
bovenaan de vragen, zodat het in één keer te plakken is.

Ophalen gaat als controleer (recheck.py): één verzoek per klik, nooit twee
tegelijk, met de wachttijd ertussen, en dezelfde vastlegging (prijs,
gereserveerd, biedingen). De pagina geeft meer dan de zoekresultaten. Wat
een ronde van een opgehaalde pagina bewaart, bewaart dit ook: de volledige
omschrijving, en framehoogte, materiaal en rem uit de Kenmerken
(recheck.save_page_specs()). Alle foto's in plaats van drie, de overige
Kenmerken, of het een particulier is en of verzenden kan, gaan alleen in
het dossier, niet in de database. De naam van de verkoper en van de
bieders niet: daar heeft Claude niets aan.

Het dossier rekent niets nieuws: schatting, trede, waardescore en
upgradeoordeel zijn die van /racefietsen (racebikes.estimate(),
racebikes._verdicts()). Het zet er alleen meer naast. Bieden of reageren
doet de eigenaar zelf.
"""
from __future__ import annotations

import argparse
import csv
import io
import sqlite3
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import bike_identity as bi
import db
import racebikes as rb
import racefiets_jev as mp
import recheck as rc
import upgrade as up
import valuation as val

PATH = rb.PATH + "/dossier"  # POST item_id: ophalen en het dossier terug (dashboard.py)
# Zoveel vergelijkingsfietsen gaan in de CSV: die van de schatting eerst,
# dan de rest van het model en de modelfamilie. Bij een populair model zijn
# het er honderden; met alles erin werd het dossier te lang om te plakken.
MAX_COMPS = 300
# Zoveel onderdelen uit de eigen klussenlijsten (/flips), de nieuwste eerst.
MAX_PARTS = 30
# De foto's op de advertentiepagina hebben een maat in de link
# ("...?rule=ecg_mp_eps$_#.jpg", gezien op 06-10-2026); de pagina noemt de
# maten zelf (gallery.media.imageSizes). De grootste die er is, want een
# kras of een versleten kettingblad moet te zien zijn. 85 (XXL) als de
# pagina ze niet noemt: die gaf toen een foto van 1200 px.
PHOTO_SIZES = ("XXL", "XL", "L")
PHOTO_SIZE = "85"
SELLER_TYPES = {"CONSUMER": "particulier"}
DIMENSIONS = (("frame", "frame"), ("drivetrain", "aandrijving"), ("brakes", "remmen"), ("wheels", "wielen"),
              ("extras", "extra's"))
OWNER_SECTION = "## Vastgesteld door de eigenaar"
# De specs zoals racefiets_jev.extract_specs() ze noemt, in de taal van de eigenaar.
SPEC_LABELS = {"groupset": "groepset", "frame_material": "framemateriaal", "brake_type": "remmen",
               "speeds": "versnellingen", "model_year": "bouwjaar", "wheel_type": "wielen",
               "weight_kg": "gewicht (kg)", "electronic": "elektronisch schakelen", "frame_size": "framemaat",
               "has_powermeter": "powermeter", "has_computer": "fietscomputer", "groupset_tier": "groepsetniveau"}

QUESTIONS = """\
## Vraag aan Claude

Ik overweeg deze racefiets op Marktplaats te kopen: om te flippen, of als
upgrade van mijn eigen fiets (sectie *Mijn fiets*). Hieronder staat alles wat
mijn koopjesfinder erover weet. Wil je:

1. **Zeggen of het een goede deal is.** Zet de prijs af tegen de schatting en
   de vergelijkingsfietsen, voor een flip (wat houd ik over na wat erin moet)
   en als upgrade. Wat zou je bieden, en tot hoever zou je gaan?
2. **Zeggen wat er vernieuwd moet worden.** Lees de omschrijving en bekijk de
   foto's: slijtage aan ketting, cassette, kettingbladen, banden, remblokken
   of remschijven, stuurlint, kabels; schade aan frame, vork of velgen;
   verouderde standaarden. Geef per onderdeel een prijsindicatie en zeg waar
   die vandaan komt; staan er onderaan prijzen uit mijn eigen flips, gebruik
   die. Weet je een prijs niet zeker, zeg dat dan in plaats van er een te
   verzinnen.
3. **De vergelijkingsfietsen analyseren** (de CSV onderaan): spreiding,
   uitschieters, prijs tegen bouwjaar, groepset en staat, snel verkocht tegen
   nog te koop. Hoe stevig staat de schatting, en is de trede de goede?
4. **Zeggen wat ik de verkoper nog moet vragen** voordat ik bied.

Om goed te lezen:

- Alle prijzen van andere fietsen zijn **vraagprijzen**, geen
  verkoopprijzen. *Verdwenen* is niet hetzelfde als verkocht (ook
  ingetrokken of verlopen); *snel verkocht* is: binnen 7 dagen weg, of
  gereserveerd en daarna weg.
- De schatting komt uit één *trede* van vergelijkbare fietsen: model ±2 jaar,
  dan model, modelfamilie ±2 jaar, modelfamilie zelfde tijdperk, zelfde
  opbouw ±2 jaar. Welke het werd staat bij de schatting.
- De foto's zijn links. Kun je ze niet openen, zeg het dan; dan sleep ik ze
  in de chat.
"""


class DossierError(Exception):
    """Geen dossier; de tekst gaat naar de pagina."""


NOT_A_BIKE = "Die fiets staat niet in de database (alleen racefietsen hebben een dossier)."


@dataclass
class Stored:
    """Wat de database over de fiets zelf weet."""
    listing: mp.Listing
    asking: Optional[float] = None  # de vraagprijs als die zeker is (asking_from_row()); anders None
    posted: str = ""
    first_seen: str = ""
    last_seen: str = ""
    disappeared_at: str = ""
    days_online: Optional[int] = None
    reserved_at: str = ""
    details_at: str = ""
    prices: list = field(default_factory=list)  # [(observed_at, prijs)], oudste eerst
    stats: list = field(default_factory=list)  # [(observed_at, bekeken, bewaard, online sinds)]


def _readonly(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn) -> set:
    return {t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def load_stored(db_path, item_id: str) -> Optional[Stored]:
    """De fiets zoals racebikes._listing() hem leest, ook als hij verdwenen of
    al lang niet meer gezien is: een dossier van een fiets die net verkocht
    werd, zegt nog steeds iets. None: geen racefiets met dit id."""
    if not Path(db_path).exists():
        return None
    conn = _readonly(db_path)
    try:
        row = conn.execute(rb.SELECT + " AND item_id = ?", (f"%/{rb.CATEGORY}/%", item_id)).fetchone()
        if row is None:
            return None
        tables = _tables(conn)
        site = {item_id: {k: v for k, v in conn.execute(
            "SELECT key, value FROM spec WHERE source = ? AND listing_id = ?", (db.SITE_SPEC_SOURCE, item_id))}}
        place = (conn.execute("SELECT latitude, longitude, promotion, traits FROM listing_place WHERE item_id = ?",
                              (item_id,)).fetchone() if "listing_place" in tables else None)
        extra = conn.execute("SELECT posted_date, details_fetched_at FROM listing WHERE item_id = ?",
                             (item_id,)).fetchone()
        prices = [(r[0], r[1]) for r in conn.execute(
            "SELECT observed_at, price_eur FROM listing_price WHERE item_id = ? ORDER BY observed_at", (item_id,))]
        stats = ([tuple(r) for r in conn.execute(
            "SELECT observed_at, views, favorites, online_since FROM listing_stats WHERE item_id = ? "
            "ORDER BY observed_at",
            (item_id,))] if "listing_stats" in tables else [])
    finally:
        conn.close()
    listing = rb._listing(row, site, {item_id: tuple(place)} if place else {})
    return Stored(listing, asking=asking_from_row(row), posted=extra["posted_date"] or "", first_seen=row["first_seen"] or "",
                  last_seen=row["last_seen"] or "", disappeared_at=row["disappeared_at"] or "",
                  days_online=row["days_online"], reserved_at=row["reserved_at"] or "",
                  details_at=extra["details_fetched_at"] or "", prices=prices, stats=stats)


def asking_from_row(row) -> Optional[float]:
    """De vraagprijs uit de database, alleen als die zeker is. price_eur is
    bij een biedadvertentie soms het minimumbod (FAST_BID) of het hoogste bod
    (MIN_BID met een bod erboven, na controleer of het dossier), en een ronde
    schrijft price_type niet altijd weg (gezien 06-10-2026: leeg bij bijna
    alle rijen die eerst via seen_listings.json binnenkwamen). Zonder bieden
    is de prijs de vraagprijs; bij MIN_BID alleen als hij niet het hoogste
    bod is. Verder onbekend: liever geen vraagprijs dan een bod onder die naam."""
    price = row["price_eur"]
    if price is None:
        return None
    if not row["is_bid"]:
        return price
    if row["price_type"] == "MIN_BID" and (row["bid_high"] is None or price != row["bid_high"]):
        return price
    return None


def _comp_rows(db_path, item_ids) -> dict:
    """{item_id: rij} met wat de CSV van elke vergelijkingsfiets wil."""
    ids = list(item_ids)
    if not ids or not Path(db_path).exists():
        return {}
    conn = _readonly(db_path)
    found = {}
    try:
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            for r in conn.execute(
                    "SELECT item_id, title, description, full_description, frame_height, condition, first_seen, "
                    "last_seen, disappeared_at, days_online, reserved_at FROM listing "
                    f"WHERE item_id IN ({','.join('?' * len(chunk))})", chunk):
                found[r["item_id"]] = r
    finally:
        conn.close()
    return found


def _own_parts(db_path) -> list:
    """De onderdelen op de eigen klussenlijsten (/flips) met een prijs:
    wat de eigenaar echt betaalde of zelf schatte, de nieuwste eerst."""
    if not Path(db_path).exists():
        return []
    conn = _readonly(db_path)
    try:
        if "flip_task" not in _tables(conn):
            return []
        return conn.execute(
            "SELECT title, est_eur, price_eur, price_source, shop, bought_at, updated_at FROM flip_task "
            "WHERE kind = 'onderdeel' AND deleted_at IS NULL AND (price_eur IS NOT NULL OR est_eur IS NOT NULL) "
            "ORDER BY updated_at DESC LIMIT ?", (MAX_PARTS,)).fetchall()
    finally:
        conn.close()


# --- Opmaak ----------------------------------------------------------------------------


def euro(amount: Optional[float]) -> str:
    if amount is None:
        return "—"
    return f"€{amount:,.0f}".replace(",", ".")


def _local(value: Optional[str]) -> str:
    """Een tijd op de eigen klok, zoals dashboard.local_time(): de database
    bewaart UTC ("...+00:00"), de pagina "...Z". Zonder tijdzone (een eigen
    bod, een datum) blijft hij zoals hij is."""
    text = value or ""
    if len(text) <= 10:
        return text
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:16].replace("T", " ")
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%Y-%m-%d %H:%M")


def day(value: Optional[str]) -> str:
    return _local(value)[:10]


def minute(value: Optional[str]) -> str:
    return _local(value)[:16]


def cell(value) -> str:
    """Eén cel van een Markdown-tabel: geen | en geen regelovergang erin."""
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def table(rows: list, head: tuple = ("", "")) -> str:
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def fenced(text: str, lang: str = "text") -> str:
    """Een codeblok dat de tekst niet kan afsluiten: een verkoper die zelf
    ``` typt, zou de rest van het dossier anders als tekst laten lezen."""
    longest, run = 0, 0
    for ch in text:
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{lang}\n{text.rstrip()}\n{fence}"


def _when(value) -> Optional[datetime]:
    """Een tijd uit de database of van de pagina ("...Z"), altijd met tijdzone."""
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _yes(flag) -> str:
    return "ja" if flag else "nee"


def _brake(disc: Optional[bool]) -> str:
    return "onbekend" if disc is None else "schijfrem" if disc else "velgrem"


# --- Wat de advertentiepagina erbij geeft ------------------------------------------------


def page_photos(page: Optional[dict]) -> list[str]:
    """Alle foto's van de advertentiepagina, in de grootste maat die hij noemt."""
    gallery = (page or {}).get("gallery")
    if not isinstance(gallery, dict):
        return []
    sizes = (gallery.get("media") or {}).get("imageSizes") or {}
    size = next((str(sizes[k]) for k in PHOTO_SIZES if isinstance(sizes, dict) and sizes.get(k)), PHOTO_SIZE)
    out = []
    for url in gallery.get("imageUrls") or []:
        if not isinstance(url, str):
            continue
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("https://") and " " not in url:
            out.append(url.replace("$_#", f"$_{size}"))
    return out


def page_bids(page: Optional[dict]) -> list[tuple]:
    """[(bedrag, datum)] van de biedingen op de pagina, zonder wie er bood."""
    info = (page or {}).get("bidsInfo")
    if not isinstance(info, dict):
        return []
    out = []
    for b in info.get("bids") or []:
        if isinstance(b, dict) and mp.as_number(b.get("value")) is not None:
            out.append((mp.as_number(b["value"]) / 100, day(mp.text_value(b.get("date")))))
    return sorted(out, key=lambda b: b[1])


def page_facts(page: Optional[dict]) -> list[tuple]:
    """(wat, waarde) over de verkoper en de advertentie die alleen de pagina heeft."""
    if not page:
        return []
    facts = []
    seller = page.get("seller") if isinstance(page.get("seller"), dict) else {}
    kind = mp.text_value(seller.get("sellerType"))
    since = mp.text_value(seller.get("activeSinceDiff"))
    if kind or since:
        who = SELLER_TYPES.get(kind, kind.lower() if kind else "")
        facts.append(("Verkoper", ", ".join(p for p in (who, f"op Marktplaats sinds {since}" if since else "") if p)))
    flags = page.get("flags") if isinstance(page.get("flags"), dict) else {}
    if isinstance(flags.get("shippable"), bool):
        facts.append(("Verzenden", "kan (volgens Marktplaats)" if flags["shippable"] else "alleen ophalen"))
    tip = mp.text_value(((page.get("gallery") or {}) if isinstance(page.get("gallery"), dict) else {}).get(
        "microTipText"))
    if tip:
        facts.append(("Label van de verkoper", f"„{tip}”"))
    traits = page.get("traits")
    if isinstance(traits, list) and traits:
        facts.append(("Extra's op Marktplaats", ", ".join(str(t) for t in traits)))
    return facts


# --- Het dossier ------------------------------------------------------------------------


@dataclass
class Comp:
    item_id: str
    title: str
    price: float
    ident: bi.Identity
    url: str
    gone: str
    fast: bool
    used: bool  # in de trede van de schatting
    relation: str  # model / familie / opbouw


def _relation(me: bi.Identity, other: bi.Identity) -> str:
    if me.exact and other.exact == me.exact:
        return "model"
    if me.coarse and other.coarse == me.coarse:
        return "familie"
    return "opbouw"


def gather_comps(base: rb.Base, ident: bi.Identity, item_id: str) -> tuple[str, bool, list]:
    """(trede, weinig, [Comp]): de fietsen van de schatting en daarnaast de
    rest van hetzelfde model en dezelfde modelfamilie, alle jaren en
    materialen: voor de analyse is ook zichtbaar wat de trede wegliet."""
    level, found, few = base.pool.comparables(ident, item_id)
    used = {c[2][0] for c in found}
    seen, out = set(), []
    others = list(base.pool.by_exact.get(ident.exact, ()) if ident.exact else ())
    others += list(base.pool.by_coarse.get(ident.coarse, ()) if ident.coarse else ())
    for c in list(found) + others:
        cid = c[2][0]
        if cid == item_id or cid in seen:
            continue
        seen.add(cid)
        out.append(Comp(cid, c[2][1], c[1], c[0], c[2][2], c[2][3], c[2][4], cid in used, _relation(ident, c[0])))
    order = {"model": 0, "familie": 1, "opbouw": 2}
    out.sort(key=lambda c: (not c.used, order[c.relation], c.price, c.item_id))
    return level, few, out


def _evenly(group: list, n: int) -> list:
    """n fietsen gelijkmatig over de prijzen van `group`, goedkoopste tot
    duurste: de spreiding blijft te zien, in plaats van alleen de onderkant."""
    ordered = sorted(group, key=lambda c: (c.price, c.item_id))
    if n <= 0:
        return []
    if n >= len(ordered):
        return ordered
    if n == 1:
        return [ordered[len(ordered) // 2]]
    return [ordered[round(i * (len(ordered) - 1) / (n - 1))] for i in range(n)]


def pick_rows(comps: list, cap: int) -> list:
    """Hooguit `cap` rijen voor de CSV. Eerst de snel verkochte van de
    schatting (daar rust hij op); de rest verdeeld over de andere van de
    schatting, de rest van het model en de familie, naar verhouding en elke
    groep minstens één als er plek is, per groep gelijkmatig over de prijzen.
    Alleen de goedkoopste 300 gaf een scheef beeld: de duurdere snel verkochte
    waar de schatting op rustte, vielen eruit (review, 06-10-2026)."""
    if len(comps) <= cap:
        return comps
    fast = [c for c in comps if c.used and c.fast]
    rest = [g for g in ([c for c in comps if c.used and not c.fast],
                        [c for c in comps if not c.used and c.relation == "model"],
                        [c for c in comps if not c.used and c.relation != "model"]) if g]
    chosen = _evenly(fast, cap)
    left = cap - len(chosen)
    if left > 0 and rest:
        total = sum(len(g) for g in rest)
        share = [min(len(g), max(1, left * len(g) // total)) for g in rest]
        # Minstens één per groep kan te veel zijn: eraf bij de groep die naar
        # verhouding het meest kreeg; wat de afronding liet liggen, naar de
        # groep met de meeste over.
        while sum(share) > left:
            i = max(range(len(rest)), key=lambda i: share[i] / len(rest[i]))
            share[i] -= 1
        while sum(share) < left:
            room = [i for i in range(len(rest)) if share[i] < len(rest[i])]
            if not room:
                break
            share[max(room, key=lambda i: len(rest[i]) - share[i])] += 1
        for group, n in zip(rest, share):
            chosen += _evenly(group, n)
    keep = {c.item_id for c in chosen}
    return [c for c in comps if c.item_id in keep]


def _spread(prices: list) -> str:
    if not prices:
        return "geen"
    prices = sorted(prices)
    if len(prices) < 4:
        return f"n={len(prices)}: {', '.join(euro(p) for p in prices)}"
    q1, med, q3 = statistics.quantiles(prices, n=4, method="inclusive")
    return (f"n={len(prices)}, min {euro(prices[0])}, 25% {euro(q1)}, mediaan {euro(med)}, "
            f"75% {euro(q3)}, max {euro(prices[-1])}")


def comps_summary(comps: list) -> str:
    groups = [("Gebruikt voor de schatting", [c for c in comps if c.used]),
              ("Zelfde model (alle jaren)", [c for c in comps if c.relation == "model"]),
              ("Zelfde modelfamilie (alle jaren, alle materialen)", [c for c in comps if c.relation != "opbouw"])]
    rows, previous = [], None
    for label, group in groups:
        # Een groep met dezelfde fietsen als de vorige zegt niets nieuws.
        ids = {c.item_id for c in group}
        if not group or ids == previous:
            continue
        previous = ids
        fast = [c.price for c in group if c.fast]
        for_sale = [c.price for c in group if not c.gone]
        rows.append((label, _spread([c.price for c in group]),
                     f"{len(fast)}" + (f", mediaan {euro(statistics.median(fast))}" if fast else ""),
                     f"{len(for_sale)}" + (f", mediaan {euro(statistics.median(for_sale))}" if for_sale else "")))
    out = table(rows, ("Groep", "Vraagprijzen", "Snel verkocht", "Nog te koop"))
    by_year: dict = {}
    for c in comps:
        if c.used:
            by_year.setdefault(c.ident.year, []).append(c)
    if by_year and (len(by_year) > 1 or None not in by_year):
        years = sorted(by_year, key=lambda y: (y is None, y or 0))
        out += "\n\nPer bouwjaar, alleen de fietsen van de schatting:\n\n" + table(
            [(y or "onbekend", len(by_year[y]), euro(statistics.median(c.price for c in by_year[y])),
              sum(1 for c in by_year[y] if c.fast)) for y in years],
            ("Bouwjaar", "Aantal", "Mediaan vraagprijs", "Snel verkocht"))
    return out


CSV_HEAD = ("id", "titel", "vraagprijs", "bouwjaar", "materiaal", "groepset", "versnellingen", "rem",
            "elektronisch", "framemaat", "staat", "eerst_gezien", "laatst_gezien", "verdwenen", "dagen_online",
            "gereserveerd", "snel_verkocht", "in_schatting", "relatie", "link")


def comps_csv(comps: list, db_path) -> str:
    rows = _comp_rows(db_path, [c.item_id for c in comps])
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_HEAD)
    for c in comps:
        r = rows.get(c.item_id)
        text = f"{c.title} {(r['full_description'] or r['description'] or '') if r else ''}"
        groupset = mp.detect_groupset(text)[0]
        i = c.ident
        writer.writerow((
            c.item_id, c.title, f"{c.price:.0f}", i.year or "", i.material or "", groupset, i.speeds or "",
            _brake(i.disc) if i.disc is not None else "", _yes(i.electronic) if i.electronic else "",
            (r["frame_height"] or "") if r else "", (r["condition"] or "") if r else "",
            day(r["first_seen"]) if r else "", day(r["last_seen"]) if r else "", c.gone,
            "" if r is None or r["days_online"] is None else r["days_online"],
            _yes(r is not None and r["reserved_at"]), _yes(c.fast), _yes(c.used), c.relation, c.url))
    return out.getvalue()


def owner_facts(intake_path) -> str:
    """De tabel die de eigenaar zelf invulde in mijn_fiets.md; de afleidingen
    eronder niet (die zijn lang, en Claude maakt ze zelf)."""
    try:
        text = Path(intake_path).read_text(encoding="utf-8")
    except (OSError, TypeError):
        return ""
    start = text.find(OWNER_SECTION)
    if start == -1:
        return ""
    body = text[start + len(OWNER_SECTION):]
    end = body.find("\n## ")
    return (body if end == -1 else body[:end]).strip()


def _bid_line(l: mp.Listing) -> str:
    if l.bid_count is None:
        return "niet opgevraagd" if l.price_is_bid else ""
    parts = [f"{l.bid_count} bieding{'en' if l.bid_count != 1 else ''}" if l.bid_count else "nog geen bod"]
    if l.bid_count and l.bid_high is not None:
        parts.append(f"hoogste {euro(l.bid_high)}")
    if l.bid_minimum:
        parts.append(f"minimumbod {euro(l.bid_minimum)}")
    if getattr(l, "bids_checked_at", None):
        parts.append(f"opgevraagd {minute(l.bids_checked_at)}")
    return ", ".join(parts)


def _online_days(stored: Stored, page: Optional[dict], now: datetime) -> str:
    """Hoe lang hij al online staat. De pagina weet het (stats.since, ook
    bewaard bij een meting van views.py); anders sinds de eerste ronde die
    hem zag, en dat kan later zijn."""
    if stored.disappeared_at:
        return (f"{stored.days_online} dagen, verdwenen {day(stored.disappeared_at)}"
                if stored.days_online is not None else f"verdwenen {day(stored.disappeared_at)}")
    since = (mp.page_stats(page) or {}).get("since") if page else None
    since = since or next((s[3] for s in reversed(stored.stats) if s[3]), None)
    start, how = (since, "volgens de advertentiepagina") if since else (stored.first_seen, "sinds de eerste ronde die hem zag")
    first = _when(start)
    if first is None:
        return ""
    return f"{(now - first).days} dagen (sinds {day(start)}, {how})"


def build(base: rb.Base, db_path, item_id: str, intake_path=None, checked: Optional[rc.Recheck] = None,
          problem: str = "", now: Optional[datetime] = None) -> str:
    """Het dossier van `item_id` als Markdown. `checked`: wat het ophalen net
    vond (recheck_listing(details=True)); None: alleen uit de database.
    `problem`: waarom ophalen niet lukte, bovenaan in het dossier."""
    now = now or datetime.now(timezone.utc)
    stored = load_stored(db_path, item_id)
    if stored is None:
        raise DossierError(NOT_A_BIKE)
    l = stored.listing
    links, _, rules = rb.read_links(db_path)
    ident = bi.identify(l, links.get(item_id), rb.active_rules(rules))
    fresh = rb.load_fresh(db_path)
    scored: dict = {}
    with base.lock:
        est = rb.estimate(l, ident, base.pool, base.factor)
        level, few, comps = gather_comps(base, ident, item_id)
        verdict = rb._verdicts(base, [l], {item_id: ident.year} if ident.own_year else {}, scored)
        owner, owner_problem, factor = base.owner, base.owner_problem, base.factor
        name = base.names.get(ident.exact, (ident.name or "", ""))[0] if ident.exact else ""
    page = checked.page if checked else None
    asking = stored.asking
    if checked and not checked.gone and checked.price_type != "FAST_BID":
        asking = checked.asking

    out = [f"# Dossier: {l.title}", ""]
    status = [f"Gemaakt op {now.astimezone().strftime('%Y-%m-%d %H:%M')} met de koopjesfinder (racefietsen)."]
    if checked and checked.gone:
        status.append("**Net opgehaald: de advertentie staat niet meer op Marktplaats** (verkocht of "
                      "ingetrokken); hieronder wat de database er nog van weet.")
    elif checked:
        summary = checked.summary()
        status.append("De advertentiepagina is net opgehaald: "
                      + (summary[len("Gecontroleerd: "):] if summary.startswith("Gecontroleerd: ") else summary))
        if checked.description is None:
            status.append("**Let op: de omschrijving stond niet op de advertentiepagina waar hij stond** — "
                          "Marktplaats heeft waarschijnlijk zijn paginastructuur gewijzigd. Hieronder staat de "
                          "omschrijving uit de database.")
    else:
        status.append("Alleen uit de database; de advertentiepagina is niet opnieuw opgehaald.")
    if problem:
        status.append(f"**Ophalen lukte niet:** {problem}")
    out += [" ".join(status), "", QUESTIONS]

    # De advertentie.
    rows = [("Titel", l.title), ("Link", l.url), ("Advertentie-id", item_id),
            ("Prijs", f"{euro(l.price_eur)} ({rb.price_kind(l)})")]
    if asking is not None and asking != l.price_eur:
        rows.append(("Vraagprijs", euro(asking)))
    elif asking is None and l.price_type == "FAST_BID":
        rows.append(("Vraagprijs", "geen: alleen bieden"))
    elif asking is None and l.price_is_bid and l.bid_count:
        rows.append(("Vraagprijs", "niet apart bekend (de prijs hierboven is een bod)"))
    bids = _bid_line(l)
    if bids:
        rows.append(("Biedingen", bids))
    on_page = page_bids(page)
    if on_page:
        rows.append(("Biedingen op de pagina", ", ".join(f"{euro(a)} op {d}" for a, d in on_page)))
    rows.append(("Gereserveerd", f"ja, sinds {day(stored.reserved_at)}" if stored.reserved_at else "nee"))
    dist = fresh.distances.get(item_id)
    place = l.city + (f", {dist.label} hemelsbreed" if dist else "")
    attributes = checked.attributes if checked and checked.attributes else {}
    rows += [("Plaats", place), ("Staat", l.condition), ("Framemaat", l.frame_height or "niet vermeld")]
    facts = page_facts(page)
    rows += facts
    if l.promotion and not any(what == "Extra's op Marktplaats" for what, _ in facts):
        rows.append(("Betaalde promotie", l.promotion.lower()))
    rows += [("Geplaatst (zoekresultaten)", stored.posted), ("Eerst gezien", minute(stored.first_seen)),
             ("Laatst gezien in een ronde", minute(stored.last_seen)), ("Online", _online_days(stored, page, now))]
    if getattr(l, "checked_at", None):
        rows.append(("Gecontroleerd", minute(l.checked_at)))
    out += ["## De advertentie", "", table([r for r in rows if r[1]]), ""]

    distinct = [p for i, p in enumerate(stored.prices) if i == 0 or p[1] != stored.prices[i - 1][1]]
    if len(distinct) > 1:
        # Bij een biedadvertentie schrijven controleer en de biedopvraging het
        # hoogste bod als prijs: een stap omhoog is dan geen nieuwe vraagprijs.
        out += [("Prijsverloop (bij een biedadvertentie kan een stap het hoogste bod zijn)" if l.price_is_bid
                 else "Prijsverloop") + ": " + " → ".join(f"{euro(p)} ({day(at)})" for at, p in distinct), ""]
    elif stored.prices:
        out += [f"Prijsverloop: sinds {day(stored.prices[0][0])} steeds {euro(stored.prices[0][1])}.", ""]
    if stored.stats:
        out += ["Bekeken en bewaard (gemeten op de advertentiepagina): " + "; ".join(
            f"{day(at)}: {'?' if v is None else v}× bekeken, {'?' if f is None else f}× bewaard"
            for at, v, f, _ in stored.stats), ""]

    # Kenmerken en wat de tekst zegt.
    out += ["## Kenmerken", ""]
    if attributes:
        out += ["Zoals de verkoper ze op Marktplaats invulde. Materiaal, rem en (als die ontbrak) de framehoogte "
                "zijn net bewaard en tellen mee in de schatting en het upgradeoordeel hieronder, zoals wanneer een "
                "ronde de pagina ophaalt; waar de zoekresultaten al iets zeiden, gaat dat voor. Spreken Kenmerken "
                "en tekst elkaar tegen, vraag het dan na.", "",
                table(list(attributes.items()), ("Kenmerk", "Waarde")), ""]
    elif l.site_specs:
        out += ["Uit de velden van Marktplaats (zoekresultaten): " + ", ".join(
            f"{SPEC_LABELS.get(k, k)}: {v}" for k, v in sorted(l.site_specs.items())), ""]
    specs, year_note = up.listing_specs(l, ident.year if ident.own_year else None)
    read = [(SPEC_LABELS.get(k, k), v) for k, v in specs.items() if v]
    if l.groupset:
        read.insert(0, (SPEC_LABELS["groupset"], l.groupset))
    out += ["Wat de koopjesfinder uit titel en tekst las (kan fout zijn):", "",
            table(read or [("—", "niets herkend")], ("Gegeven", "Waarde")), ""]
    if year_note:
        out += [f"Bouwjaar: {year_note}", ""]

    text = checked.description if checked and checked.description is not None else (l.detail_text or l.description)
    full = bool((checked and checked.description is not None) or l.detail_text)
    out += ["## Omschrijving", "",
            ("De volledige omschrijving van de advertentiepagina" + (f" (opgehaald {day(stored.details_at)})"
                                                                     if not checked and stored.details_at else "")
             if full else "**Alleen het fragment uit de zoekresultaten**; de volledige omschrijving is nooit "
                          "opgehaald (de knop dossier op /racefietsen doet dat)") + ":", "",
            fenced(text or "(geen tekst)"), ""]

    from_page = page_photos(page)
    photos = from_page or (l.image_urls or "").split()
    out += ["## Foto's", "",
            (("De foto van de advertentiepagina:" if len(photos) == 1 else f"Alle {len(photos)} foto's van de "
              "advertentiepagina:") if from_page
             else "De foto's uit de zoekresultaten (Marktplaats geeft daar hooguit drie):"), ""]
    out += [f"{i}. {u}" for i, u in enumerate(photos, 1)] or ["(geen foto's)"]
    out.append("")

    # Welke fiets het is.
    source = {"eigen": "door jou gekoppeld", "regel": "via een regel die je goedkeurde",
              "referentie": "uit de referentielijst", "automatisch": "automatisch uit de titel"}.get(ident.source, "")
    rows = [("Model", (name or ident.name or "niet herkend") + (f" ({source})" if source else "")
             + (" — door jou bevestigd" if ident.confirmed else "")),
            ("Bouwjaar", f"{ident.year} ({'door jou ingevuld' if ident.own_year else 'uit de advertentie'})"
             if ident.year else "onbekend")]
    if ident.recognized_name and ident.recognized_name != (name or ident.name):
        rows.append(("De advertentie zelf zegt", ident.recognized_name))
    rows += [("Materiaal", ident.material or "onbekend"),
             ("Groepset", ", ".join(p for p in (
                 l.groupset or "niet herkend", f"niveau {ident.tier} van 6" if ident.tier else "",
                 f"{ident.speeds}-speed" if ident.speeds else "", "elektronisch" if ident.electronic else "") if p)),
             ("Remmen", _brake(ident.disc))]
    out += ["## Welke fiets het is", "", table(rows), ""]

    # Schatting en oordeel.
    out += ["## Schatting en oordeel van de koopjesfinder", ""]
    lines = []
    if est.resale is None:
        lines.append(f"- **Geen schatting**: {est.basis}.")
    else:
        lines.append(f"- **Verwachte verkoopprijs: {euro(est.resale)}** — {est.basis}.")
        if asking:
            lines.append(f"- Vraagprijs {euro(asking)} tegen de schatting: {round((asking / est.resale - 1) * 100):+d}%.")
        if l.price_eur and l.price_eur != asking:
            # Een minimumbod of lopend bod is geen vraagprijs (CLAUDE.md):
            # het staat er met zijn eigen naam.
            lines.append(f"- {rb.price_kind(l).capitalize()} {euro(l.price_eur)} tegen de schatting: "
                         f"{round((l.price_eur / est.resale - 1) * 100):+d}%.")
        entry = up.entry_price(l)
        if entry.amount is not None:
            lines.append(f"- **Flip**: {euro(est.resale)} − {euro(entry.amount)} ({entry.basis}) = "
                         f"**{euro(est.resale - entry.amount)}**, nog zonder onderdelen, reizen en tijd.")
        price = up.effective_price(l, factor)
        if price.amount:
            lines.append(f"- Waardescore {val.dutch(est.resale / price.amount)} (geschatte waarde / "
                         f"{euro(price.amount)}, {price.basis}); 1,00 = hij kost wat hij waard is, hoger = goedkoper.")
        lines.append(f"- Trede: {bi.LEVEL_LABELS.get(level, level)}{' (weinig: minder dan 5)' if few else ''}; "
                     f"{est.count} fietsen, mediaan vraagprijs {euro(est.median)}; snel verkocht {est.fast[0]}"
                     f"{f' (mediaan {euro(est.fast[1])})' if est.fast[1] is not None else ''}; nog te koop "
                     f"{est.for_sale[0]}{f' (mediaan {euro(est.for_sale[1])})' if est.for_sale[1] is not None else ''}.")
        lines.append(f"- Afdingfactor {val.dutch(factor, 3)}: zonder genoeg snel verkochte is de schatting "
                     "de mediaan-vraagprijs maal deze factor.")
    ok, gain, why = verdict.get(item_id) or (False, None, owner_problem)
    lines.append(f"- **Upgrade van mijn fiets: {'ja' if ok else 'nee'}**" + (f" (+{gain:.0f} punten)" if ok and gain else "")
                 + (f" — {why}" if why else ""))
    out += lines + [""]

    s = scored.get(item_id)
    if s is not None and owner is not None:
        rows = [(label, f"{s.quality.dimensions[key].score:.0f}", f"{owner.quality.dimensions[key].score:.0f}",
                 " · ".join(s.quality.dimensions[key].reasons))
                for key, label in DIMENSIONS if key in s.quality.dimensions and key in owner.quality.dimensions]
        rows.append(("**totaal**", f"**{s.quality.total:.0f}**", f"**{owner.quality.total:.0f}**",
                     " · ".join(s.reasons)))
        out += ["Kwaliteitsscore (0-100, los van de prijs) tegen mijn fiets:", "",
                table(rows, ("Onderdeel", "Deze fiets", "Mijn fiets", "Waarom (deze fiets)")), ""]

    # Mijn fiets.
    facts = owner_facts(intake_path) if intake_path else ""
    out += ["## Mijn fiets", ""]
    if facts:
        out += ["Uit mijn intake (mijn_fiets.md):", "", facts, ""]
    if owner is not None:
        extra = []
        if owner.target_size_cm:
            extra.append(f"mijn framemaat {owner.target_size_cm:.0f} cm")
        if owner.budgets is not None:
            extra.append(f"budget voor een upgrade: {euro(owner.budgets.rim.amount)} met velgremmen, "
                         f"{euro(owner.budgets.disc.amount)} met schijfremmen")
        if extra:
            out += ["- " + "; ".join(extra) + ".", ""]
    elif owner_problem:
        out += [f"Geen eigen fiets in de berekening: {owner_problem}.", ""]
    if not facts and owner is None and not owner_problem:
        out += ["(niet bekend)", ""]

    # Wat de eigenaar er zelf bij heeft.
    mine = []
    mark = fresh.marks.get(item_id)
    if mark is not None:
        mine.append(f"- Markering: {mark.label}" + (f" bij {euro(mark.price_eur)}" if mark.price_eur else "")
                    + f" ({day(mark.marked_at)})")
    if fresh.notes.get(item_id):
        mine.append(f"- Notitie: {fresh.notes[item_id]}")
    trail = fresh.bids.get(item_id)
    if trail and trail.bids:
        mine.append("- Mijn biedingen: " + ", ".join(f"{euro(b.amount_eur)} op {day(b.bid_at)} ({b.status})"
                                                     for b in trail.bids))
    if item_id in fresh.bought:
        mine.append(f"- Gekocht op {day(fresh.bought[item_id])}")
    if mine:
        out += ["## Wat ik er zelf bij noteerde", ""] + mine + [""]

    parts = _own_parts(db_path)
    if parts:
        out += ["## Onderdeelprijzen uit mijn eigen flips",
                "",
                "Wat ik op mijn klussenlijsten (/flips) echt betaalde, of zelf schatte (dat staat erbij).",
                "",
                table([(p["title"], euro(p["price_eur"]) if p["price_eur"] is not None else f"{euro(p['est_eur'])} (geschat)",
                        p["shop"] or "", day(p["bought_at"] or p["updated_at"])) for p in parts],
                      ("Onderdeel", "Prijs", "Winkel", "Datum")), ""]

    # De vergelijkingsfietsen.
    out += ["## Vergelijkingsfietsen", ""]
    if not comps:
        out += ["Geen: " + (est.basis or "geen vergelijkbare fietsen") + ". Kies op /racefietsen het model "
                "(knop ander model) en maak het dossier opnieuw.", ""]
    else:
        shown = pick_rows(comps, MAX_COMPS)
        used = any(c.used for c in comps)
        out += [f"Alle racefietsen van de laatste {rb.POOL_DAYS} dagen met een vraagprijs, ook verdwenen: "
                + ("die van de schatting (*in_schatting* = ja) en daarnaast " if used
                   else "geen ervan telde voor een schatting (te weinig), hier ")
                + f"de rest van hetzelfde model en dezelfde modelfamilie (*relatie*). {len(comps)} fietsen"
                + (f"; in de CSV {len(shown)}: eerst alle snel verkochte van de schatting, dan van elke groep "
                   "een deel naar verhouding, gelijkmatig over de prijzen (de samenvatting hieronder telt ze alle)"
                   if len(shown) < len(comps) else "") + ".", "",
                comps_summary(comps), "", fenced(comps_csv(shown, db_path), "csv"), ""]
    return "\n".join(out).rstrip() + "\n"


def fetch(db_path, item_id: str, session=None, now: Optional[str] = None) -> tuple:
    """Wat de knop eerst doet: de advertentiepagina ophalen zoals controleer,
    met de omschrijving erbij (recheck_listing(details=True)). Lukt dat niet,
    dan komt het dossier uit de database, met de reden erin.
    (Recheck of None, waarom niet, melding voor de pagina). Geen verzoek
    voor iets waar geen dossier van komt: DossierError."""
    if load_stored(db_path, item_id) is None:
        raise DossierError(NOT_A_BIKE)
    try:
        checked = rc.recheck_listing(db_path, item_id, session=session, now=now, details=True)
    except rc.RecheckError as exc:
        return None, str(exc), f"Niet opnieuw opgehaald ({exc}); het dossier komt uit de database."
    return checked, "", checked.summary()


def main(argv=None) -> int:
    """`python dossier.py m2449549680`: het dossier uit de database;
    `--ophalen` haalt eerst de advertentiepagina op (één verzoek)."""
    parser = argparse.ArgumentParser(description="Het dossier van één racefiets, om aan Claude te geven.")
    parser.add_argument("item_id", help="het advertentie-id, bv. m2449549680")
    parser.add_argument("--db", default="koopjes.db")
    parser.add_argument("--mijn-fiets", default=str(Path(__file__).resolve().parent / "mijn_fiets.md"))
    parser.add_argument("--ophalen", action="store_true",
                        help="eerst de advertentiepagina ophalen, zoals de knop controleer (één verzoek)")
    parser.add_argument("--uit", help="naar dit bestand (UTF-8) in plaats van naar het scherm")
    args = parser.parse_args(argv)
    if not Path(args.db).exists():
        print(f"Database {args.db} bestaat niet.", file=sys.stderr)
        return 1
    checked, problem = None, ""
    try:
        if args.ophalen:
            checked, problem, message = fetch(args.db, args.item_id)
            print(message, file=sys.stderr)
        # Na het ophalen: de schatting rekent dan met wat de pagina net zei.
        base = rb.build_base(args.db, args.mijn_fiets)
        text = build(base, args.db, args.item_id, args.mijn_fiets, checked, problem)
    except DossierError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.uit:
        Path(args.uit).write_text(text, encoding="utf-8")
        print(f"Dossier geschreven naar {args.uit}.", file=sys.stderr)
        return 0
    try:
        print(text)
    except UnicodeEncodeError:
        # Een Windows-console is vaak cp1252 en titels hebben emoji; --uit
        # schrijft het echte bestand.
        encoding = sys.stdout.encoding or "ascii"
        print(text.encode(encoding, errors="replace").decode(encoding))
    return 0


if __name__ == "__main__":
    sys.exit(main())
