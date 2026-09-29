"""Het dashboard: één pagina voor alles wat er op Marktplaats aan
fietscomputers te koop staat, in plaats van een rapport per zoekterm. En net
zo'n pagina voor de sporthorloges (markets.py beschrijft de markten).

    python dashboard.py                 # schrijft dashboard.html uit koopjes.db
    python dashboard.py --open          # en opent hem
    python dashboard.py --markt sporthorloges   # dashboard_horloges.html
    python dashboard.py --markt alle    # beide
    python dashboard.py --serve         # live in de browser, met Gekocht/Verkocht-knoppen
                                        # en favoriet/weg per advertentie
                                        # (fietscomputers op /, sporthorloges op /horloges)

Gebouwd uit de database, niet uit één run: de zoekopdracht "fietscomputer"
in schedule.json zoekt op 17 merken, en elk merk leverde een eigen rapport op
(racefiets_report_garmin-edge.html, ..._wahoo-roam.html, ...). Die hingen niet
aan elkaar, en een flip-schatting per rapport zag alleen de advertenties van
dat ene merk. Hier staat alles bij elkaar, met de vergelijkingsprijzen over
alle zoektermen en eerdere rondes heen.

Tabs: Flips (wat je per advertentie verdient), Upgrades (t.o.v. de eigen
computer), Favorieten, Alle computers, Marktprijzen per model, Vinted (alleen na `python
vinted.py import`: wat je op Vinted koopt en op Marktplaats verkoopt), en
Uitgefilterd (houders, hoesjes, onderdelen, defecte en gezochte — om na te
kijken dat er geen echte computer tussen zit). De rekenregels staan in
computers.py en computer_scoring.json; dit bestand toont alleen.

Het geschreven dashboard.html leest alleen. `--serve` start een klein
programma op je eigen computer (alleen bereikbaar via 127.0.0.1) dat dezelfde
pagina live toont, met knoppen om je eigen aan- en verkopen vast te leggen in
koopjes.db (tabel `trade`, zie trades.py) en om advertenties als favoriet te
bewaren of weg te zetten (tabel `listing_mark`, zie marks.py). Dat is het
enige dat hier schrijft.
"""
from __future__ import annotations

import argparse
import hmac
import html
import secrets
import sqlite3
import statistics
import sys
import webbrowser
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import parse_qs, quote, urlsplit

import computers as pc
import db
import markets as mk
import marks as mr
import racefiets_jev as mp
import patterns as pt
import trades as tr
import vinted as vn

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = "dashboard.html"
COMPUTER_CATEGORY = mk.COMPUTERS.categories[0]

esc = html.escape


@dataclass
class Unknown:
    """Een advertentie zonder bekend model: een computer (of horloge) met
    onbekend model, of iets dat is uitgefilterd."""
    listing: mp.Listing
    kind: str
    reason: str


@dataclass
class Dashboard:
    listings: list  # alle actieve advertenties in de categorie
    unknown: list = field(default_factory=list)  # Unknown
    newest_seen: str = ""
    new_ids: set = field(default_factory=set)
    config: dict = field(default_factory=dict)
    progress: Optional[tr.Progress] = None  # Mijn flips
    patterns: Optional[pt.Patterns] = None  # Patronen
    bought: dict = field(default_factory=dict)  # item_id -> Trade
    marks: dict = field(default_factory=dict)  # item_id -> marks.Mark
    vinted: Optional[vn.VintedView] = None  # tab Vinted; None = nog geen export ingelezen
    db_path: str = ""
    # Alleen in de live versie (--serve): formulieren, met het geheim dat
    # bewijst dat een POST van deze pagina komt en niet van een andere site.
    editable: bool = False
    token: str = ""
    message: str = ""
    market: mk.Market = mk.COMPUTERS
    # Links naar de andere dashboards: (label, href).
    other_links: list = field(default_factory=list)

    # De signalen heten .computer omdat ze uit computers.py komen; bij de
    # sporthorloges zijn het horloges.
    @property
    def items(self) -> list:
        return pc.active_computers(self.listings)

    @property
    def unknown_items(self) -> list:
        return [u for u in self.unknown if u.kind == self.market.item]

    computers = items
    unknown_computers = unknown_items

    @property
    def excluded(self) -> list:
        """(listing, soort, reden) voor alles wat geen computer (horloge) is."""
        rows = [(l, l.computer.kind, l.computer.reason) for l in pc.filtered_out(self.listings)]
        rows += [(u.listing, u.kind, u.reason) for u in self.unknown if u.kind != self.market.item]
        return sorted(rows, key=lambda r: (r[1], r[0].title.lower()))

    # Wat je al gekocht hebt, is geen kans meer: weg uit Flips en Upgrades
    # (in Alle computers blijft het staan, met een vinkje). Een gereserveerde
    # advertentie evenmin: die is al aan een ander toegezegd. En wat je zelf
    # wegzette ook niet, tot de prijs zakt (marks.py).
    def _available(self, listing) -> bool:
        return (listing.item_id not in self.bought and not listing.reserved
                and not self.is_dismissed(listing))

    def is_dismissed(self, listing) -> bool:
        return mr.is_dismissed(self.marks.get(listing.item_id), listing)

    def is_favorite(self, listing) -> bool:
        mark = self.marks.get(listing.item_id)
        return mark is not None and mark.favorite

    @property
    def all_rows(self) -> list:
        """(advertentie, modellabel, signalen) voor alles in Alle computers."""
        rows = [(l, l.computer.model.label, l.computer) for l in self.items]
        return rows + [(u.listing, "model onbekend", None) for u in self.unknown_items]

    @property
    def favorites(self) -> list:
        return [row for row in self.all_rows if self.is_favorite(row[0])]

    @property
    def gone_favorites(self) -> list:
        """Favorieten van deze markt die niet meer actief zijn: verdwenen, of
        te lang niet gezien. Uit `listing_mark` met wat `listing` er nog van
        weet, zodat je ziet dat hij weg is in plaats van dat hij stil
        verdwijnt."""
        active = {l.item_id for l in self.listings}
        return [m for m in self.marks.values()
                if m.favorite and m.item_id not in active
                and any(f"/{c}/" in (m.url or "") for c in self.market.categories)]

    @property
    def dismissed_flips(self) -> list:
        """Flips die er zonder jouw wegzetten wel hadden gestaan."""
        return [l for l in pc.flips(self.listings)
                if l.computer.profit_eur > 0 and self.is_dismissed(l)
                and l.item_id not in self.bought and not l.reserved]

    @property
    def flips(self) -> list:
        return [l for l in pc.flips(self.listings) if l.computer.profit_eur > 0 and self._available(l)]

    @property
    def open_bids(self) -> list:
        return [l for l in pc.open_bids(self.listings) if self._available(l)]

    @property
    def upgrades(self) -> list:
        if not self.market.has_upgrades:
            return []
        return [l for l in pc.upgrades(self.listings) if self._available(l)]


# --- Uit de database ---------------------------------------------------------


def _parse_time(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def load_dashboard(db_path, config: Optional[dict] = None, market: mk.Market = mk.COMPUTERS) -> Dashboard:
    """De actieve advertenties in de categorieën van `market`: niet verdwenen
    en gezien binnen `active_days` van de nieuwste waarneming. Relatief aan de
    nieuwste en niet aan nu, zodat een dashboard na een week zonder rondes
    niet leeg is maar de stand van de laatste ronde laat zien."""
    config = config or pc.default_config()
    d = _with_trades(_load_market(db_path, config, market), db_path)
    d.marks = mr.load_marks(db_path)
    d.patterns = pt.load_patterns(db_path, config, market)
    d.vinted = vn.load_view(db_path, config) if market.has_vinted else None
    d.db_path = str(Path(db_path).resolve())
    return d


def _with_trades(d: Dashboard, db_path) -> Dashboard:
    """Mijn flips erbij: de eigen trades van deze markt, met de huidige
    marktwaarde per model. `bought` kent alle trades: wat gekocht is, is geen
    kans meer, uit welk dashboard het ook gekocht werd."""
    everything = tr.load_trades(db_path)
    trades = [t for t in everything if mk.trade_market(t) is d.market]
    own_ids = frozenset(t.item_id for t in everything if t.item_id)
    market = (pc.market_resale(db_path, catalog=d.market.catalog(), config=d.config, exclude=own_ids,
                               categories=d.market.comp_categories)
              if trades and Path(db_path).exists() else {})
    d.progress = tr.progress(trades, market, d.config["flip"].get("costs_eur", 0.0))
    d.bought = {t.item_id: t for t in everything if t.item_id}
    return d


def load_active_listings(db_path, categories: Sequence[str], settings: dict):
    """(advertenties, nieuwste waarneming, id's van de nieuwe) uit koopjes.db:
    niet verdwenen, in een van `categories` (de categorie uit de URL), en
    gezien binnen `active_days` van de nieuwste waarneming. Ook voor de
    sporthorloges (watches.py). Zonder database of zonder rijen: ([], None,
    set())."""
    if not Path(db_path).exists():
        return [], None, set()
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(listing)")}
        images = "image_urls" if "image_urls" in columns else "'' AS image_urls"
        asking = "price_is_asking" if "price_is_asking" in columns else "NULL AS price_is_asking"
        reserved = "reserved_at" if "reserved_at" in columns else "NULL AS reserved_at"
        bids = ("bid_count, bid_minimum, bids_checked_at" if "bids_checked_at" in columns
                else "NULL AS bid_count, NULL AS bid_minimum, NULL AS bids_checked_at")
        where = " OR ".join("url LIKE ?" for _ in categories)
        rows = conn.execute(
            f"SELECT item_id, title, description, price_eur, price_type, is_bid, {asking}, "
            f"city, posted_date, condition, url, first_seen, last_seen, {images}, {reserved}, {bids} "
            f"FROM listing WHERE disappeared_at IS NULL AND ({where})",
            tuple(f"%/{category}/%" for category in categories),
        ).fetchall()
    finally:
        conn.close()

    seen = [t for t in (_parse_time(r["last_seen"]) for r in rows) if t]
    if not seen:
        return [], None, set()
    newest = max(seen)
    active_since = newest - timedelta(days=settings["active_days"])
    new_since = newest - timedelta(hours=settings["new_hours"])

    listings, new_ids = [], set()
    for r in rows:
        last = _parse_time(r["last_seen"])
        if last is None or last < active_since:
            continue
        listing = mp.Listing(
            item_id=r["item_id"],
            title=r["title"] or "",
            description=r["description"] or "",
            price_eur=r["price_eur"],
            price_type=r["price_type"] or "",
            city=r["city"] or "",
            date=r["posted_date"] or "",
            condition=r["condition"] or "",
            frame_height="",
            groupset="",
            groupset_tier=None,
            url=r["url"] or "",
            price_is_bid=bool(r["is_bid"]),
            first_seen=r["first_seen"] or "",
            image_urls=r["image_urls"] or "",
            reserved=r["reserved_at"] is not None,
        )
        # Wat de biedopvraging vond (migratie 11). Van vóór die migratie staat
        # alleen price_is_asking = 0 als teken van een lopend bod (migratie
        # 3); één bod is dan genoeg om Listing.price_is_asking hetzelfde te
        # laten zeggen.
        listing.bid_minimum = r["bid_minimum"]
        listing.bids_checked_at = r["bids_checked_at"]
        if r["bid_count"] is not None:
            listing.bid_count = r["bid_count"]
        elif r["is_bid"] and r["price_is_asking"] == 0:
            listing.bid_count = 1
        first = _parse_time(r["first_seen"])
        if first and first >= new_since:
            new_ids.add(listing.item_id)
        listings.append(listing)
    if len(new_ids) == len(listings):
        # De allereerste ronde: alles is "nieuw", en dan zegt het label niets.
        new_ids = set()
    return listings, newest, new_ids


def _load_market(db_path, config: dict, market: mk.Market = mk.COMPUTERS) -> Dashboard:
    listings, newest, new_ids = load_active_listings(db_path, market.categories, config["dashboard"])
    if newest is None:
        return Dashboard([], config=config, market=market)

    catalog = market.catalog()
    pc.apply_computer_signals(listings, db_path=db_path, catalog=catalog, config=config,
                              comp_categories=market.comp_categories)
    # Alleen titels zonder bekend model; een fiets met computer ("Racefiets
    # Cube + Garmin Edge 130 Plus") hoort hier niet bij.
    unknown = [
        Unknown(l, *market.classify_unknown(l.title, l.description))
        for l in listings
        if l.computer is None and pc.classify_title(l.title, catalog) is None
    ]
    return Dashboard(listings, unknown, newest.isoformat(timespec="minutes"), new_ids, config, market=market)


def model_resale(d: Dashboard) -> dict[str, float]:
    """{modellabel: verwachte verkoopprijs} over alle vergelijkingsprijzen van
    het model (niet per advertentie zonder zichzelf, zoals bij een flip)."""
    if not d.db_path:
        return {}
    return pc.market_resale(d.db_path, catalog=d.market.catalog(), config=d.config,
                            categories=d.market.comp_categories)


def market_rows(d: Dashboard) -> list[tuple[str, list, Optional[float]]]:
    """Per model: (label, actieve advertenties, mediaan vraagprijs), meeste
    advertenties eerst. Gereserveerde en lopende biedingen tellen niet mee
    voor de mediaan."""
    by_model: dict[str, list] = {}
    for l in d.items:
        by_model.setdefault(l.computer.model.label, []).append(l)
    rows = []
    for label, items in by_model.items():
        asking = [l.price_eur for l in items if l.price_eur and l.price_is_asking and not l.reserved]
        rows.append((label, items, statistics.median(asking) if asking else None))
    return sorted(rows, key=lambda r: (-len(r[1]), r[0]))


# --- HTML ---------------------------------------------------------------------


def euro(amount: Optional[float]) -> str:
    if amount is None:
        return "—"
    text = f"€{abs(amount):,.0f}".replace(",", ".")
    return f"−{text}" if amount < 0 else text


def band(low: Optional[float], high: Optional[float]) -> str:
    if low is None or high is None:
        return ""
    if round(low) == round(high):
        return f"weinig spreiding ({euro(low)})"
    return f"{euro(low)} tot {euro(high)}"


def signed_euro(amount: Optional[float]) -> str:
    if amount is None:
        return "—"
    return ("+" if amount >= 0 else "") + euro(amount)


MONTHS = ("jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec")


def nl_date(value: Optional[str]) -> str:
    try:
        day = date.fromisoformat((value or "")[:10])
    except ValueError:
        return value or "?"
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def local_time(iso: str) -> str:
    moment = _parse_time(iso)
    if moment is None:
        return iso or "?"
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%d-%m-%Y %H:%M")


def thumb(listing) -> str:
    url = (listing.image_urls or "").split()
    if not url:
        return "<div class='thumb empty' aria-hidden='true'></div>"
    return (f"<a href='{esc(listing.url, quote=True)}' target='_blank' rel='noopener'>"
            f"<img class='thumb' src='{esc(url[0], quote=True)}' alt='' loading='lazy'></a>")


def comp_text(c) -> str:
    """Waarmee de verkoopprijs is vergeleken, kort: dezelfde uitvoering of het
    hele model (computers.apply_computer_signals())."""
    if c.comp_scope == "uitvoering":
        return f"n={c.comp_count}, zelfde uitvoering: {c.variant.label}"
    if c.variant is not None and c.variant_comp_count < c.model_comp_count:
        return f"n={c.comp_count}, hele model; {c.variant.label}: {c.variant_comp_count}"
    return f"n={c.comp_count} vergelijkbaar"


def variant_summary(items: list) -> str:
    """"X · Solar 5× €420; gewone uitvoering 12× €260" voor een model met
    meer dan één uitvoering te koop; mediaan vraagprijs per uitvoering."""
    groups: dict[str, list] = {}
    for l in items:
        variant = l.computer.variant
        groups.setdefault(variant.group_label if variant else "gewone uitvoering", []).append(l)
    if len(groups) < 2:
        return ""
    parts = []
    for label, group in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        asking = [pc.listed_price(l) for l in group if l.price_is_asking and pc.listed_price(l) is not None]
        median = f" {euro(statistics.median(asking))}" if asking else ""
        parts.append(f"{label} {len(group)}×{median}")
    return "; ".join(parts)


def listing_cell(listing, d: Dashboard, model_label: str, note: str = "") -> str:
    new = "<span class='badge fav'>★ favoriet</span> " if d.is_favorite(listing) else ""
    new += "<span class='badge'>nieuw</span> " if listing.item_id in d.new_ids else ""
    if listing.reserved:
        new += "<span class='badge reserved'>gereserveerd</span> "
    if d.is_dismissed(listing):
        new += f"<span class='badge reserved'>{esc(d.marks[listing.item_id].label)}</span> "
    place = f" · {esc(listing.city)}" if listing.city else ""
    note_html = f"<div class='note'>{esc(note)}</div>" if note else ""
    return (
        f"<td class='what'><div class='model'>{new}{esc(model_label)}</div>"
        f"<a href='{esc(listing.url, quote=True)}' target='_blank' rel='noopener'>{esc(listing.title)}</a>"
        f"<span class='muted'>{place}</span>{note_html}{mark_control(listing, d)}{buy_control(listing, d)}</td>"
    )


def hidden(d: Dashboard, **values) -> str:
    fields = {"token": d.token, "markt": d.market.key, **values}
    return "".join(f"<input type='hidden' name='{k}' value='{esc(str(v), quote=True)}'>" for k, v in fields.items())


def buy_control(listing, d: Dashboard) -> str:
    """"Gekocht" bij een advertentie: een badge als hij al in Mijn flips
    staat, anders (alleen live) een knop met de prijs alvast ingevuld."""
    trade = d.bought.get(listing.item_id)
    if trade:
        return (f"<div class='owned'>✓ gekocht op {esc(nl_date(trade.bought_at))} voor "
                f"{euro(trade.buy_price_eur)}</div>")
    if not d.editable:
        return ""
    price = "" if listing.price_eur is None else f"{listing.price_eur:.0f}"
    return (
        "<form class='inline' method='post' action='/gekocht'>"
        f"{hidden(d, item_id=listing.item_id)}"
        f"<label>€<input name='prijs' value='{price}' inputmode='decimal' size='5' required "
        "aria-label='Inkoopprijs'></label><button>Gekocht</button></form>"
    )


def mark_control(listing, d: Dashboard) -> str:
    """Favoriet of weg bij een advertentie (alleen live), en de regel dat een
    weggezette advertentie terug is omdat de prijs zakte (ook in de
    geschreven pagina). Eén formulier; de knop die je indrukt, zegt wat."""
    mark = d.marks.get(listing.item_id)
    back = mark is not None and mark.mark == mr.DISMISSED and mr.price_dropped(mark, listing)
    note = (f"<div class='note'>Weer terug: de prijs zakte van {euro(mark.price_eur)} naar "
            f"{euro(listing.price_eur)} sinds je hem wegzette ({esc(mark.reason or 'weg')}).</div>"
            if back else "")
    if not d.editable:
        return note

    def button(value: str, label: str) -> str:
        return f"<button class='quiet' name='soort' value='{esc(value, quote=True)}'>{esc(label)}</button>"

    away = "<span class='muted'>weg:</span>" + "".join(button(r, r) for r in mr.REASONS)
    if d.is_dismissed(listing):
        buttons = button("geen", "terugzetten") + button(mr.FAVORITE, "☆ favoriet")
    elif mark is not None and mark.favorite:
        buttons = button("geen", "★ uit favorieten") + away
    else:
        buttons = button(mr.FAVORITE, "☆ favoriet") + away + (button("geen", "wissen") if back else "")
    return (f"{note}<form class='inline mark' method='post' action='/markeer'>"
            f"{hidden(d, item_id=listing.item_id, tab='')}{buttons}</form>")


def bid_note(listing) -> str:
    """Wat de biedopvraging zei: aantal biedingen en minimumbod, met wanneer
    — een bod van de nachtronde kan overdag al hoger zijn."""
    count = getattr(listing, "bid_count", None)
    checked = getattr(listing, "bids_checked_at", None)
    if count is None or not checked:
        return ""
    parts = [f"{count} bieding{'en' if count != 1 else ''}" if count else "nog geen bod"]
    if listing.bid_minimum:
        parts.append(f"min. {euro(listing.bid_minimum)}")
    parts.append(f"opgehaald {local_time(checked)}")
    return " · ".join(parts)


def price_cell(listing, extra: str = "") -> str:
    kind = pc.price_kind(listing)
    note = bid_note(listing)
    return (f"<td class='num' data-sort='{listing.price_eur if listing.price_eur is not None else ''}'>"
            f"{euro(listing.price_eur)}<div class='sub'>{esc(kind)}</div>"
            f"{f'<div class=sub>{esc(note)}</div>' if note else ''}"
            f"{f'<div class=sub>{esc(extra)}</div>' if extra else ''}</td>")


def tiles(items: list[tuple[str, str, str]]) -> str:
    """Een rij stat-tegels: (label, waarde, toelichting)."""
    return "<div class='tiles'>" + "".join(
        f"<div class='tile'><div class='label'>{esc(label)}</div><div class='value'>{value}</div>"
        f"<div class='sub'>{esc(sub)}</div></div>"
        for label, value, sub in items
    ) + "</div>"


def table(head: list[tuple[str, str]], rows: list[str], table_id: str = "") -> str:
    """head: (kop, 'num'|'text'|'') — alleen kolommen met een soort zijn sorteerbaar."""
    ths = "".join(
        f"<th{' class=num' if kind == 'num' else ''}"
        f"{f' data-type={kind}' if kind else ''}>{esc(title)}</th>"
        for title, kind in head
    )
    ident = f" id='{table_id}'" if table_id else ""
    return (f"<div class='table-wrap'><table class='sortable'{ident}><thead><tr>{ths}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def flips_panel(d: Dashboard) -> str:
    flip = d.config["flip"]
    flips = d.flips
    best = flips[0] if flips else None
    parts = [tiles([
        ("Flips met winst", str(len(flips)), f"na {euro(flip.get('costs_eur', 0))} verzendkosten per stuk"),
        ("Beste flip", signed_euro(best.computer.profit_eur) if best else "—",
         best.computer.model.label if best else "nog niets"),
        ("Samen", euro(sum(l.computer.profit_eur for l in flips)) if flips else "—",
         "als je ze allemaal koopt en verkoopt"),
        ("Zonder prijs", str(len(d.open_bids)), "met een maximaal bod"),
    ])]
    parts.append(
        "<p class='explain'><strong>Winst</strong> = verwachte verkoopprijs − prijs − verzendkosten "
        f"({euro(flip.get('costs_eur', 0))} per flip, instelbaar als <code>costs_eur</code> in "
        "<code>computer_scoring.json</code>). "
        "De verkoopprijs is de mediaan van wat andere advertenties voor hetzelfde model vragen "
        f"(nu en de laatste {flip['comp_window_days']} dagen, verkochte meegeteld): van dezelfde "
        f"<em>uitvoering</em> als dat er minstens {flip['min_comps']} zijn (maat-letter zoals 7S/7X, kastmaat, "
        "Solar, Sapphire, Titanium, AMOLED, MicroLED, Music, LTE, bundel, MARQ-editie — zoals de titel ze "
        "noemt), anders van het "
        "hele model; onder de verkoopprijs staat welke van de twee. "
        f"× {str(flip['negotiation_factor']).replace('.', ',')} voor afdingen. De band eronder is de winst "
        "bij het goedkoopste en duurste kwart van die advertenties. Bij <em>huidig bod</em> loopt de prijs "
        "nog op; bij <em>vraagprijs, bieden kan</em> kun je vaak lager uitkomen. Gereserveerde advertenties "
        f"staan hier niet (wel in Alle {d.market.items}) en tellen niet als vergelijkingsprijs zolang ze online staan.</p>"
    )
    away = d.dismissed_flips
    if away:
        parts.append(
            f"<p class='explain'>{len(away)} flip{'s' if len(away) != 1 else ''} weggezet (niet waard of "
            f"gereserveerd): terug te vinden in Alle {esc(d.market.items)} met <em>Toon: weggezet</em>. Zakt de "
            "prijs onder die van toen je hem wegzette, dan staat hij hier weer.</p>")
    if flips:
        rows = []
        for l in flips:
            c = l.computer
            rows.append(
                "<tr>"
                f"<td class='pic'>{thumb(l)}</td>"
                f"<td class='num profit' data-sort='{c.profit_eur}'>"
                f"<span class='gain' aria-hidden='true'>▲</span>{signed_euro(c.profit_eur)}"
                f"<div class='sub'>{band(c.profit_low_eur, c.profit_high_eur)}</div></td>"
                f"{price_cell(l)}"
                f"<td class='num' data-sort='{c.resale_eur}' title='{esc(c.comp_note, quote=True)}'>{euro(c.resale_eur)}"
                f"<div class='sub'>{esc(comp_text(c))}</div></td>"
                f"{listing_cell(l, d, c.model.label, c.reason)}"
                "</tr>"
            )
        parts.append(table([("", ""), ("Winst", "num"), ("Inkoop", "num"), ("Verkoop", "num"),
                            ("Advertentie", "text")], rows))
    else:
        parts.append(f"<p class='empty'>Geen {d.market.item} die onder de verwachte verkoopprijs staat.</p>")

    if d.open_bids:
        parts.append("<h3>Zonder prijs — bied maximaal</h3>"
                     "<p class='explain'>Bieden zonder minimum of geen prijs genoemd. Het maximale bod is de "
                     "lage verkoopschatting min verzendkosten: daarboven speel je bij een tegenvaller verlies.</p>")
        rows = [
            "<tr>"
            f"<td class='pic'>{thumb(l)}</td>"
            f"<td class='num' data-sort='{l.computer.max_bid_eur}'><strong>{euro(l.computer.max_bid_eur)}</strong>"
            f"<div class='sub'>verkoop ±{euro(l.computer.resale_eur)}, {esc(comp_text(l.computer))}</div></td>"
            f"<td class='num'>{esc(pc.price_kind(l))}</td>"
            f"{listing_cell(l, d, l.computer.model.label, l.computer.reason)}"
            "</tr>"
            for l in d.open_bids
        ]
        parts.append(table([("", ""), ("Bied max.", "num"), ("Prijs", ""), ("Advertentie", "text")], rows))
    return "\n".join(parts)


def upgrades_panel(d: Dashboard) -> str:
    base = pc.baseline_model(config=d.config)
    ups = d.upgrades
    own = ups[0].computer.own_resale_eur if ups else None
    nets = [l.computer.net_upgrade_cost_eur for l in ups if l.computer.net_upgrade_cost_eur is not None]
    base_label = base.label if base else "eigen computer"
    parts = [tiles([
        ("Upgrades te koop", str(len(ups)), f"kunnen meer dan je {base_label}"),
        (f"Je {base.model if base else 'computer'} levert op", euro(own) if own is not None else "—",
         ("zelf ingesteld (eigen_verkoopprijs_eur)" if d.config["baseline"].get("eigen_verkoopprijs_eur") is not None
          else "verwachte verkoopprijs") if own is not None else "te weinig vergelijkbare advertenties"),
        ("Goedkoopste, netto", euro(min(nets)) if nets else "—",
         "prijs min wat je eigen computer oplevert (negatief: je houdt geld over)"),
    ])]
    parts.append(
        "<p class='explain'><strong>+punten</strong> = functiescore min die van je eigen computer "
        f"({esc(base_label)}). Rerouting, plannen op het apparaat en training wegen het zwaarst, knoppen "
        "gaan voor touch, geen updates kost punten (<code>python computers.py</code> toont de score per model). "
        "<strong>Netto</strong> = prijs min wat je eigen computer oplevert als je hem verkoopt.</p>"
    )
    if not ups:
        parts.append("<p class='empty'>Geen herkende computer die meer kan dan je eigen.</p>")
        return "\n".join(parts)
    rows = []
    for l in ups:
        c = l.computer
        gains, losses = pc.feature_changes(c.model, base, d.config)
        changes = "".join(f"<li class='plus'>{esc(g)}</li>" for g in gains)
        changes += "".join(f"<li class='minus'>{esc(x)}</li>" for x in losses)
        unknown = f"<div class='sub'>{len(c.features.unknown)} velden onbekend</div>" if c.features.unknown else ""
        rows.append(
            "<tr>"
            f"<td class='pic'>{thumb(l)}</td>"
            f"<td class='num' data-sort='{c.upgrade_delta}'><strong>+{c.upgrade_delta:.0f}</strong>"
            f"<div class='sub'>score {c.features.score:.0f}</div>{unknown}</td>"
            f"{price_cell(l)}"
            f"<td class='num' data-sort='{c.net_upgrade_cost_eur if c.net_upgrade_cost_eur is not None else ''}'>"
            f"{euro(c.net_upgrade_cost_eur)}</td>"
            f"<td><ul class='changes'>{changes or '<li>zelfde functies, beter bekend</li>'}</ul></td>"
            f"{listing_cell(l, d, c.model.label, c.reason)}"
            "</tr>"
        )
    parts.append(table([("", ""), ("+punten", "num"), ("Prijs", "num"), ("Netto", "num"),
                        ("Wat je erbij krijgt / inlevert", ""), ("Advertentie", "text")], rows))
    return "\n".join(parts)


def mark_state(listing, d: Dashboard) -> str:
    """Voor het filter Toon in Alle computers."""
    if d.is_favorite(listing):
        return mr.FAVORITE
    return mr.DISMISSED if d.is_dismissed(listing) else ""


def all_panel(d: Dashboard) -> str:
    scored = d.market.has_score
    items = d.all_rows
    brands = sorted({label.split(" ")[0] for _, label, c in items if c is not None})
    options = "".join(f"<option value='{esc(b)}'>{esc(b)}</option>" for b in brands)
    away = sum(1 for l, _, _ in items if d.is_dismissed(l))
    parts = [
        "<div class='filters'>"
        "<input type='search' id='all-search' placeholder='Zoek in titel of model' aria-label='Zoeken'>"
        f"<select id='all-brand' aria-label='Merk'><option value=''>Alle merken</option>{options}"
        "<option value='model onbekend'>Model onbekend</option></select>"
        "<select id='all-mark' aria-label='Toon'><option value=''>Toon: zonder weggezette</option>"
        f"<option value='{mr.FAVORITE}'>Toon: favorieten ({len(d.favorites)})</option>"
        f"<option value='{mr.DISMISSED}'>Toon: weggezet ({away})</option>"
        "<option value='alles'>Toon: alles</option></select>"
        "<label><input type='checkbox' id='all-new'> alleen nieuw</label>"
        "<span class='muted' id='all-count'></span></div>"
    ]
    rows = []
    for l, label, c in sorted(items, key=lambda i: (i[1] == "model onbekend", i[1], i[0].price_eur or 0)):
        brand = label.split(" ")[0] if c is not None else "model onbekend"
        profit = c.profit_eur if c else None
        delta = c.upgrade_delta if c else None
        score = c.features.score if c else None
        note = c.reason if c else next(u.reason for u in d.unknown if u.listing is l)
        rows.append(
            f"<tr data-brand='{esc(brand, quote=True)}' data-new='{int(l.item_id in d.new_ids)}' "
            f"data-mark='{mark_state(l, d)}' data-text='{esc((label + ' ' + l.title).lower(), quote=True)}'>"
            f"<td class='pic'>{thumb(l)}</td>"
            f"{price_cell(l)}"
            f"<td class='num' data-sort='{profit if profit is not None else ''}'>{signed_euro(profit)}</td>"
            + (f"<td class='num' data-sort='{delta if delta is not None else ''}'>"
               f"{'—' if delta is None else f'{delta:+.0f}'}</td>"
               f"<td class='num' data-sort='{score if score is not None else ''}'>{'—' if score is None else f'{score:.0f}'}</td>"
               if scored else "")
            + f"{listing_cell(l, d, label, note)}"
            "</tr>"
        )
    head = [("", ""), ("Prijs", "num"), ("Winst", "num")]
    if scored:
        head += [("Upgrade", "num"), ("Score", "num")]
    parts.append(table(head + [("Advertentie", "text")], rows, "all-table"))
    return "\n".join(parts)


def favorites_panel(d: Dashboard) -> str:
    favs = d.favorites
    how = ("Klik bij een advertentie op <em>☆ favoriet</em> om hem hier te bewaren, of zet hem weg met "
           "<em>niet waard</em> of <em>gereserveerd</em>: dan verdwijnt hij uit Flips"
           + (" en Upgrades" if d.market.has_upgrades else "")
           + " tot de prijs zakt.")
    if not d.editable:
        how = ("Bewaren en wegzetten doe je in de live versie: <code>python dashboard.py --serve</code>. " + how)
    parts = [f"<p class='explain'>{how} Een markering is alleen voor jou: een weggezette advertentie telt "
             "gewoon mee als vergelijkingsprijs.</p>"]
    if favs:
        rows = []
        for l, label, c in favs:
            mark = d.marks[l.item_id]
            then = (f"bij bewaren {euro(mark.price_eur)}"
                    if mark.price_eur is not None and mark.price_eur != l.price_eur else "")
            note = c.reason if c else next(u.reason for u in d.unknown if u.listing is l)
            profit = c.profit_eur if c else None
            rows.append(
                "<tr>"
                f"<td class='pic'>{thumb(l)}</td>"
                f"{price_cell(l, then)}"
                f"<td class='num' data-sort='{profit if profit is not None else ''}'>{signed_euro(profit)}</td>"
                f"{listing_cell(l, d, label, note)}"
                "</tr>"
            )
        parts.append(table([("", ""), ("Prijs", "num"), ("Winst", "num"), ("Advertentie", "text")], rows))
    else:
        parts.append("<p class='empty'>Nog geen favorieten.</p>")

    gone = d.gone_favorites
    if gone:
        parts.append(f"<h3>Niet meer online ({len(gone)})</h3><p class='explain'>Verdwenen of al een paar "
                     "dagen niet meer gezien. Verdwenen is niet per se verkocht: een advertentie kan ook "
                     "ingetrokken zijn.</p>")
        rows = []
        for m in gone:
            link = (f"<a href='{esc(m.url, quote=True)}' target='_blank' rel='noopener'>{esc(m.title or m.item_id)}</a>"
                    if m.url else esc(m.title or m.item_id))
            when = (f"verdwenen {nl_date(m.disappeared_at)}" if m.disappeared_at
                    else f"laatst gezien {nl_date(m.last_seen)}")
            remove = (f"<form class='inline mark' method='post' action='/markeer'>"
                      f"{hidden(d, item_id=m.item_id, tab='')}"
                      "<button class='quiet' name='soort' value='geen'>weghalen</button></form>"
                      if d.editable else "")
            rows.append(
                "<tr>"
                f"<td class='num' data-sort='{m.current_price_eur if m.current_price_eur is not None else ''}'>"
                f"{euro(m.current_price_eur)}</td>"
                f"<td class='what'>{link}<div class='note'>{esc(when)}</div>{remove}</td>"
                "</tr>"
            )
        parts.append(table([("Laatste prijs", "num"), ("Advertentie", "text")], rows))
    return "\n".join(parts)


def market_panel(d: Dashboard) -> str:
    factor = d.config["flip"]["negotiation_factor"]
    scored = d.market.has_score
    by_model: dict[str, list] = {}
    for l in d.items:
        by_model.setdefault(l.computer.model.label, []).append(l)
    # Over alle vergelijkingsprijzen van het model; per advertentie rekent de
    # flip zonder die advertentie zelf, en dat hoort niet in een tabel per model.
    per_model = model_resale(d)
    rows = []
    for label, items in sorted(by_model.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        model = items[0].computer.model
        # Geen €0: dat is "gratis" of een ruilaanbod (computers.listed_price()).
        asking = [pc.listed_price(l) for l in items if l.price_is_asking and pc.listed_price(l) is not None]
        median = statistics.median(asking) if asking else None
        resale = per_model.get(label, items[0].computer.resale_eur)
        new_price = model.number("nieuwprijs_eur")
        variants = variant_summary(items)
        rows.append(
            "<tr>"
            f"<td class='what'><div class='model'>{esc(label)}</div>"
            f"<span class='muted'>{esc(model.get('introductiejaar') or '')}</span>"
            + (f"<div class='sub'>{esc(variants)}</div>" if variants else "")
            + "</td>"
            f"<td class='num' data-sort='{len(items)}'>{len(items)}</td>"
            f"<td class='num' data-sort='{min(asking) if asking else ''}'>{euro(min(asking) if asking else None)}</td>"
            f"<td class='num' data-sort='{median if median is not None else ''}'>{euro(median)}</td>"
            f"<td class='num' data-sort='{resale if resale is not None else ''}'>"
            f"{euro(resale) if resale is not None else euro(median * factor) if median else '—'}</td>"
            f"<td class='num' data-sort='{new_price if new_price else ''}'>{euro(new_price)}</td>"
            + (f"<td class='num' data-sort='{items[0].computer.features.score}'>{items[0].computer.features.score:.0f}</td>"
               if scored else "")
            + "</tr>"
        )
    intro = ("<p class='explain'>Per model wat er nu te koop staat. <strong>Verwacht verkoop</strong> is de "
             f"mediaan-vraagprijs × {str(factor).replace('.', ',')}, over alle advertenties van de laatste "
             f"{d.config['flip']['comp_window_days']} dagen (ook verkochte); een flip rekent per uitvoering als "
             "die er genoeg heeft. Onder het model staan de uitvoeringen die nu te koop staan, met hun "
             "mediaan-vraagprijs. Nieuwprijs alleen waar een bron "
             f"hem gaf (<code>{esc(d.market.catalog_path.name)}</code>).</p>")
    head = [("Model", "text"), ("Te koop", "num"), ("Laagste", "num"), ("Mediaan vraag", "num"),
            ("Verwacht verkoop", "num"), ("Nieuwprijs", "num")]
    return intro + table(head + ([("Score", "num")] if scored else []), rows)


def _vinted_thumb(item: vn.VintedItem) -> str:
    if not item.row.image_url:
        return "<div class='thumb empty' aria-hidden='true'></div>"
    return (f"<a href='{esc(item.row.url, quote=True)}' target='_blank' rel='noopener'>"
            f"<img class='thumb' src='{esc(item.row.image_url, quote=True)}' alt='' loading='lazy'></a>")


def _vinted_cell(item: vn.VintedItem, label: str) -> str:
    new = "<span class='badge'>nieuw</span> " if item.is_new else ""
    extra = [item.row.condition, f"{item.row.favorites} fav." if item.row.favorites is not None else "",
             "zakelijke verkoper" if item.row.is_business else ""]
    muted = " · ".join(x for x in extra if x)
    return (f"<td class='what'><div class='model'>{new}{esc(label)}</div>"
            f"<a href='{esc(item.row.url, quote=True)}' target='_blank' rel='noopener'>{esc(item.row.title)}</a>"
            f"{f'<span class=muted> · {esc(muted)}</span>' if muted else ''}</td>")


def _ratio(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.2f}".replace(".", ",")


def vinted_panel(d: Dashboard) -> str:
    v = d.vinted
    if v is None:
        # Altijd een tab, ook zonder export: zo is te zien dat de import in een
        # andere database belandde dan deze, in plaats van dat de tab ontbreekt.
        return ("<p class='empty'>Nog geen Vinted-export in deze database "
                f"(<code>{esc(d.db_path)}</code>). Lees er een in met "
                "<code>python vinted.py import productsList_....csv</code> en ververs deze pagina.</p>")
    flip = d.config["flip"]
    flips = v.flips
    parts = [tiles([
        ("Op Vinted", str(len(v.computers)), f"computers met bekend model, export {local_time(v.newest_export)}"),
        ("Vinted ÷ Marktplaats", _ratio(v.median_ratio), "mediaan over de modellen met genoeg vergelijking"),
        ("Koop op Vinted", str(len(flips)), "onder de Marktplaats-verkoopprijs"),
        ("Beste", signed_euro(flips[0].profit_eur) if flips else "—",
         flips[0].model.label if flips else "nog niets"),
    ])]
    parts.append(
        "<p class='explain'>Uit de Vinted-exports die je met <code>python vinted.py import</code> inlas. "
        "<strong>Je betaalt</strong> = vraagprijs + kopersbescherming (uit de export) + "
        f"€{v.shipping_eur:.2f}".replace(".", ",") + " verzending (<code>vinted.shipping_eur</code>; uit het "
        "buitenland meer). "
        "<strong>Verkoop</strong> is de verwachte verkoopprijs op Marktplaats, dezelfde als in Flips; "
        f"de winst gaat daar nog {euro(v.costs_eur)} verzending af. Vinted-prijzen tellen nooit mee voor "
        "de Marktplaats-schattingen. Een advertentie die niet in een nieuwe export staat, is niet verkocht: "
        "een export is één zoekopdracht.</p>"
    )
    if flips:
        rows = [
            "<tr>"
            f"<td class='pic'>{_vinted_thumb(i)}</td>"
            f"<td class='num profit' data-sort='{i.profit_eur}'>"
            f"<span class='gain' aria-hidden='true'>▲</span>{signed_euro(i.profit_eur)}</td>"
            f"<td class='num' data-sort='{i.cost_eur}'>{euro(i.cost_eur)}"
            f"<div class='sub'>vraagt {euro(i.row.price_eur)}</div></td>"
            f"<td class='num' data-sort='{i.resale_eur}'>{euro(i.resale_eur)}"
            f"<div class='sub'>n={i.mp_count} op Marktplaats</div></td>"
            f"{_vinted_cell(i, i.model.label)}"
            "</tr>"
            for i in flips
        ]
        parts.append("<h3>Koop op Vinted, verkoop op Marktplaats</h3>")
        parts.append(table([("", ""), ("Winst", "num"), ("Je betaalt", "num"), ("Verkoop MP", "num"),
                            ("Advertentie", "text")], rows))
    else:
        parts.append("<p class='empty'>Geen Vinted-advertentie onder de Marktplaats-verkoopprijs.</p>")

    rows = []
    for m in v.models:
        ratio = m.ratio
        rows.append(
            "<tr>"
            f"<td class='what'><div class='model'>{esc(m.model.label)}</div></td>"
            f"<td class='num' data-sort='{len(m.vinted)}'>{len(m.vinted)}</td>"
            f"<td class='num' data-sort='{m.vinted[0]}'>{euro(m.vinted[0])}</td>"
            f"<td class='num' data-sort='{m.vinted_median}'>{euro(m.vinted_median)}</td>"
            f"<td class='num' data-sort='{len(m.marktplaats)}'>{len(m.marktplaats)}</td>"
            f"<td class='num' data-sort='{m.mp_median if m.mp_median is not None else ''}'>{euro(m.mp_median)}</td>"
            f"<td class='num' data-sort='{m.resale_eur if m.resale_eur is not None else ''}'>{euro(m.resale_eur)}</td>"
            f"<td class='num' data-sort='{ratio if ratio is not None else ''}'>{_ratio(ratio)}</td>"
            "</tr>"
        )
    parts.append("<h3>Per model</h3><p class='explain'>Vraagprijzen op Vinted (nu) naast Marktplaats (de laatste "
                 f"{flip['comp_window_days']} dagen, verkochte meegeteld). Vinted ÷ MP pas vanaf "
                 f"{flip['min_comps']} Marktplaats-advertenties. Op Vinted blijven dure advertenties vaak lang "
                 "staan, dus een hogere mediaan daar is nog geen hogere verkoopprijs.</p>")
    parts.append(table([("Model", "text"), ("Vinted", "num"), ("Laagste", "num"), ("Mediaan", "num"),
                        ("MP", "num"), ("Mediaan MP", "num"), ("Verkoop MP", "num"), ("Vinted ÷ MP", "num")], rows))
    counts: dict[str, int] = {}
    for i in v.excluded:
        counts[i.kind] = counts.get(i.kind, 0) + 1
    if counts or v.unknown:
        summary = ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        parts.append(f"<p class='explain'>Niet meegeteld: {len(v.unknown)} zonder bekend model"
                     f"{', ' + esc(summary) if summary else ''} (horloges, trainers, kleding, houders en fietsen "
                     "die Vinted bij de zoekopdracht meegaf).</p>")
    return "\n".join(parts)


def excluded_panel(d: Dashboard) -> str:
    rows_data = d.excluded
    counts: dict[str, int] = {}
    for _, kind, _ in rows_data:
        counts[kind] = counts.get(kind, 0) + 1
    summary = ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    if d.market is not mk.COMPUTERS:
        parts = [
            f"<p class='explain'>Wat níet als {esc(d.market.item)} meetelt, met de reden — om na te kijken dat er "
            f"geen echt {esc(d.market.item)} tussen zit. Bandjes, laders en hoesjes herkent het filter aan hun "
            "plek in de titel: <em>vóór</em> de modelnaam (\"Bandje voor Garmin Fenix 6\") is een accessoire, "
            "<em>erna met</em> \"met\"/\"incl.\"/\"+\" (\"Fenix 6 met siliconen polsband\") een horloge met "
            "extra's. Staat het woord er direct achter (\"Fenix 6 Pro bandje\"), dan beslist de prijs t.o.v. "
            "hetzelfde model. Andere merken en Garmin-producten die geen horloge zijn (weegschaal, "
            f"hartslagband, navigatie) staan hier als <em>overig</em>. Nu: {esc(summary) or 'niets'}.</p>"
        ]
    else:
        parts = [
        "<p class='explain'>Wat níet als computer meetelt, met de reden — om na te kijken dat er geen "
        "echte computer tussen zit. Houders en hoesjes herkent het filter aan hun plek in de titel: "
        "<em>vóór</em> de modelnaam (\"Hoesje voor Garmin 1000\") is een accessoire, <em>erna met</em> "
        "\"met\"/\"incl.\"/\"+\" (\"Edge 530 + stuurmount\") een computer met extra's. Staat het "
        "woord er direct achter (\"Karoo 3 houder nieuw\"), dan beslist de prijs t.o.v. hetzelfde model. "
        f"Nu: {esc(summary) or 'niets'}.</p>"
        ]
    rows = [
        "<tr>"
        f"<td class='pic'>{thumb(l)}</td>"
        f"<td>{esc(kind)}</td>"
        f"<td class='num' data-sort='{l.price_eur if l.price_eur is not None else ''}'>{euro(l.price_eur)}</td>"
        f"<td class='what'><a href='{esc(l.url, quote=True)}' target='_blank' rel='noopener'>{esc(l.title)}</a>"
        f"<div class='note'>{esc(reason)}</div></td>"
        "</tr>"
        for l, kind, reason in rows_data
    ]
    parts.append(table([("", ""), ("Soort", "text"), ("Prijs", "num"), ("Advertentie en reden", "text")], rows))
    return "\n".join(parts)


def month_chart(monthly: list) -> str:
    """Winst per maand als staafjes. Eén reeks, dus geen legenda; elke staaf
    heeft zijn bedrag erboven en een tooltip. Verlies hangt onder de nullijn."""
    if not monthly:
        return ""
    width, height, pad_top, pad_bottom = 640, 180, 22, 26
    values = [v for _, v in monthly]
    top, bottom = max(max(values), 0), min(min(values), 0)
    span = (top - bottom) or 1
    plot = height - pad_top - pad_bottom
    zero = pad_top + plot * top / span
    slot = width / len(monthly)
    bar = min(48, slot * 0.6)
    parts = [f"<svg class='chart' viewBox='0 0 {width} {height}' role='img' "
             "aria-label='Gerealiseerde winst per maand'>",
             f"<line x1='0' x2='{width}' y1='{zero:.1f}' y2='{zero:.1f}' class='axis'/>"]
    for i, (month, value) in enumerate(monthly):
        x = i * slot + (slot - bar) / 2
        h = abs(value) / span * plot
        y = zero - h if value >= 0 else zero
        year, mon = month.split("-")
        label = f"{MONTHS[int(mon) - 1]} '{year[2:]}"
        parts.append(
            f"<g><title>{esc(label)}: {esc(signed_euro(value))}</title>"
            f"<rect x='{x:.1f}' y='{y:.1f}' width='{bar:.1f}' height='{max(h, 1):.1f}' rx='3' class='bar'/>"
            f"<text x='{x + bar / 2:.1f}' y='{(y - 6) if value >= 0 else (y + h + 14):.1f}' "
            f"class='val'>{esc(signed_euro(value))}</text>"
            f"<text x='{x + bar / 2:.1f}' y='{height - 8}' class='lab'>{esc(label)}</text></g>"
        )
    parts.append("</svg>")
    return "".join(parts)


def mine_panel(d: Dashboard) -> str:
    p = d.progress or tr.progress([], {}, 0.0)
    shipping = d.config["flip"].get("costs_eur", 0.0)
    today = date.today().isoformat()
    error = ""
    if p.estimate_error is not None:
        direction = "boven" if p.estimate_error >= 0 else "onder"
        error = f"{abs(p.estimate_error):.0%} {direction} de schatting (n={p.estimate_n})"
    parts = [tiles([
        ("Gerealiseerde winst", signed_euro(p.realized_profit_eur) if p.sold else "—",
         f"{len(p.sold)} verkocht, samen {euro(p.revenue_eur)} omzet" if p.sold else "nog niets verkocht"),
        ("Op voorraad", str(len(p.stock)), f"{euro(p.invested_in_stock_eur)} erin gestoken" if p.stock else "niets"),
        ("Verwachte winst voorraad", signed_euro(p.expected_stock_profit_eur),
         f"na {euro(shipping)} verzendkosten per stuk"),
        ("Gemiddeld verkocht na", f"{p.avg_days_to_sell:.0f} dagen" if p.avg_days_to_sell is not None else "—",
         error or "hoe goed de schatting klopte, verschijnt na je eerste verkopen"),
    ])]
    if not d.editable:
        parts.append("<p class='explain'>Invoeren doe je in de live versie: <code>python dashboard.py --serve</code>. "
                     "Die opent dit dashboard met knoppen <em>Gekocht</em> en <em>Verkocht</em>.</p>")
    if p.monthly:
        parts.append("<h3>Winst per maand</h3>" + month_chart(p.monthly))

    parts.append(f"<h3>Op voorraad ({len(p.stock)})</h3>")
    if p.stock:
        rows = []
        for s in p.stock:
            t = s.trade
            sell = ""
            if d.editable:
                guess = "" if s.expected_resale_eur is None else f"{s.expected_resale_eur:.0f}"
                sell = (
                    "<form class='inline' method='post' action='/verkocht'>"
                    f"{hidden(d, id=t.id)}"
                    f"<label>€<input name='prijs' value='{guess}' inputmode='decimal' size='5' required "
                    "aria-label='Verkoopprijs'></label>"
                    f"<label>kosten €<input name='kosten' value='{shipping:g}' inputmode='decimal' size='3' "
                    "aria-label='Verzendkosten'></label>"
                    f"<input type='date' name='datum' value='{today}' aria-label='Verkocht op'>"
                    "<select name='via' aria-label='Verkocht via'><option>marktplaats</option><option>vinted</option>"
                    "<option>anders</option></select><button>Verkocht</button></form>"
                    + delete_form(d, t.id)
                )
            link = (f"<a href='{esc(t.url, quote=True)}' target='_blank' rel='noopener'>{esc(t.title)}</a>"
                    if t.url else esc(t.title))
            rows.append(
                "<tr>"
                f"<td class='what'><div class='model'>{esc(t.model or 'model onbekend')}</div>{link}"
                f"{'<div class=note>' + esc(t.notes) + '</div>' if t.notes else ''}{sell}</td>"
                f"<td data-sort='{t.bought_at}'>{esc(nl_date(t.bought_at))}"
                f"<div class='sub'>{t.days_held()} dagen</div></td>"
                f"<td class='num' data-sort='{t.cost_basis_eur}'>{euro(t.cost_basis_eur)}</td>"
                f"<td class='num' data-sort='{s.expected_resale_eur or ''}'>{euro(s.expected_resale_eur)}</td>"
                f"<td class='num' data-sort='{s.expected_profit_eur if s.expected_profit_eur is not None else ''}'>"
                f"{signed_euro(s.expected_profit_eur)}</td>"
                "</tr>"
            )
        parts.append(table([("Wat", "text"), ("Gekocht", "text"), ("Inkoop", "num"), ("Verwacht verkoop", "num"),
                            ("Verwachte winst", "num")], rows))
    else:
        parts.append("<p class='empty'>Niets op voorraad. Klik bij een advertentie op <em>Gekocht</em>, of voeg "
                     "hieronder iets toe dat je ergens anders kocht.</p>")

    parts.append(f"<h3>Verkocht ({len(p.sold)})</h3>")
    if p.sold:
        rows = []
        for t in p.sold:
            actions = ""
            if d.editable:
                actions = (
                    "<form class='inline' method='post' action='/terug'>"
                    f"{hidden(d, id=t.id)}<button class='quiet'>terug naar voorraad</button></form>"
                    + delete_form(d, t.id)
                )
            link = (f"<a href='{esc(t.url, quote=True)}' target='_blank' rel='noopener'>{esc(t.title)}</a>"
                    if t.url else esc(t.title))
            vs = ""
            if t.expected_resale_eur:
                vs = f"<div class='sub'>verwacht {euro(t.expected_resale_eur)}</div>"
            rows.append(
                "<tr>"
                f"<td class='what'><div class='model'>{esc(t.model or 'model onbekend')}</div>{link}{actions}</td>"
                f"<td data-sort='{t.sold_at}'>{esc(nl_date(t.sold_at))}"
                f"<div class='sub'>{t.days_held()} dagen · {esc(t.sold_via or '')}</div></td>"
                f"<td class='num' data-sort='{t.cost_basis_eur}'>{euro(t.cost_basis_eur)}</td>"
                f"<td class='num' data-sort='{t.sell_price_eur}'>{euro(t.sell_price_eur)}"
                f"<div class='sub'>−{euro(t.sell_costs_eur or 0)} kosten</div>{vs}</td>"
                f"<td class='num profit' data-sort='{t.profit_eur}'>{signed_euro(t.profit_eur)}</td>"
                "</tr>"
            )
        parts.append(table([("Wat", "text"), ("Verkocht", "text"), ("Inkoop", "num"), ("Verkoopprijs", "num"),
                            ("Winst", "num")], rows))

    if d.editable:
        labels = [m.label for m in d.market.catalog()]
        options = "".join(f"<option>{esc(l)}</option>" for l in labels)
        parts.append(
            "<h3>Zelf toevoegen</h3><p class='explain'>Voor wat je niet via een advertentie hierboven kocht, "
            "zoals een aankoop op Vinted.</p>"
            "<form class='addform' method='post' action='/toevoegen'>"
            f"{hidden(d)}"
            f"<label>Wat<input name='titel' required placeholder='{esc(d.market.example_title, quote=True)}'></label>"
            f"<label>Model<select name='model'><option value=''>model onbekend</option>{options}</select></label>"
            "<label>Inkoop €<input name='prijs' inputmode='decimal' size='6' required></label>"
            "<label>Kosten €<input name='kosten' inputmode='decimal' size='4' value='0'></label>"
            f"<label>Gekocht op<input type='date' name='datum' value='{today}'></label>"
            "<label>Notitie<input name='notitie'></label>"
            "<button>Toevoegen</button></form>"
        )
    return "\n".join(parts)


def delete_form(d: Dashboard, trade_id: int) -> str:
    return ("<form class='inline' method='post' action='/verwijder' "
            "onsubmit=\"return confirm('Deze regel verwijderen?')\">"
            f"{hidden(d, id=trade_id)}<button class='quiet'>verwijderen</button></form>")


def patterns_panel(d: Dashboard) -> str:
    p = d.patterns or pt.Patterns()
    assumed = d.config["flip"]["negotiation_factor"]
    comma = lambda x: f"{x:.2f}".replace(".", ",")
    if p.measured_factor is not None:
        factor_value = comma(p.measured_factor)
        factor_sub = f"aanname {comma(assumed)}; n={p.measured_n} snel verdwenen"
    else:
        factor_value = "—"
        factor_sub = f"nog {max(pt.MIN_FOR_FACTOR - p.measured_n, 0)} snel verdwenen advertenties nodig (nu {p.measured_n})"
    flip_sub = (f"de rest: {p.other_days:.0f} dagen" if p.other_days is not None
                else "van de rest is nog niets verdwenen" if p.flip_days is not None else "nog niets verdwenen")
    parts = [tiles([
        ("Gegevens", f"{p.days_of_data} dagen", f"sinds {nl_date(p.since.date().isoformat())}" if p.since else "nog niets"),
        ("Verdwenen", str(p.gone), f"van {p.total} {d.market.items} ooit gezien; {p.gone_reserved} eerst gereserveerd"),
        ("Gemeten afdingfactor", factor_value, factor_sub),
        ("Flips weg na", f"{p.flip_days:.0f} dagen" if p.flip_days is not None else "—",
         (flip_sub + f" (n={p.flip_n})") if p.flip_days is not None else flip_sub),
    ])]
    if p.days_of_data < 28:
        parts.append(
            "<div class='banner'>Nog weinig gegevens. Patronen worden betrouwbaar na een paar weken nachtelijke "
            "volledige rondes (<code>python koopjes.py run nacht</code>): alleen dan wordt vastgesteld dat een "
            f"advertentie verdwenen is. Per model verschijnt een getal pas vanaf {pt.MIN_PER_MODEL} advertenties.</div>")
    parts.append(
        "<p class='explain'>Uit alles wat de crawl ooit zag, ook verdwenen advertenties. <strong>Verdwenen is niet "
        "verkocht</strong>: een advertentie kan ook ingetrokken zijn. Verdween hij terwijl hij gereserveerd "
        "stond (<em>eerst gereserveerd</em>), dan is hij vrijwel zeker verkocht; dat telt alleen als een ronde "
        "de reservering zag, dus het is een ondergrens. Wie binnen "
        f"{pt.QUICK_DAYS} dagen weg is, was realistisch geprijsd — de laatste prijs daarvan, gedeeld door de "
        "mediaan-vraagprijs van het model, is de <em>gemeten afdingfactor</em>. Staat die er, dan kun je hem in "
        "<code>computer_scoring.json</code> als <code>negotiation_factor</code> zetten in plaats van de aanname.</p>")

    rows = []
    for m in p.models:
        pct = lambda x: "—" if x is None else f"{x:.0%}"
        rows.append(
            "<tr>"
            f"<td class='what'><div class='model'>{esc(m.model)}</div></td>"
            f"<td class='num' data-sort='{m.seen}'>{m.seen}</td>"
            f"<td class='num' data-sort='{m.gone}'>{m.gone}"
            f"{f'<div class=sub>{m.gone_reserved} gereserveerd</div>' if m.gone_reserved else ''}</td>"
            f"<td class='num' data-sort='{m.median_days_gone if m.median_days_gone is not None else ''}'>"
            f"{'—' if m.median_days_gone is None else f'{m.median_days_gone:.0f}'}</td>"
            f"<td class='num' data-sort='{m.quick_share if m.quick_share is not None else ''}'>{pct(m.quick_share)}</td>"
            f"<td class='num' data-sort='{m.median_ask or ''}'>{euro(m.median_ask)}</td>"
            f"<td class='num' data-sort='{m.quick_price or ''}'>{euro(m.quick_price)}"
            f"{'<div class=sub>factor ' + comma(m.factor) + '</div>' if m.factor else ''}</td>"
            f"<td class='num' data-sort='{m.dropped_share if m.dropped_share is not None else ''}'>{pct(m.dropped_share)}</td>"
            "</tr>")
    parts.append("<h3>Per model</h3>")
    parts.append(table([("Model", "text"), ("Gezien", "num"), ("Verdwenen", "num"), ("Dagen online", "num"),
                        (f"Weg ≤{pt.QUICK_DAYS} d", "num"), ("Mediaan vraag", "num"), ("Snel weg voor", "num"),
                        ("Prijs verlaagd", "num")], rows))

    if p.months:
        parts.append("<h3>Mediaan vraagprijs per maand</h3><p class='explain'>Van nieuwe advertenties die maand; "
                     "alleen modellen met minstens één maand van 3 of meer.</p>")
        rows = []
        for model, months in sorted(p.monthly.items()):
            if not any(n >= 3 for _, n in months.values()):
                continue
            cells = "".join(
                f"<td class='num'>{euro(months[m][0]) if m in months else '—'}"
                f"{'<div class=sub>n=' + str(months[m][1]) + '</div>' if m in months else ''}</td>"
                for m in p.months)
            rows.append(f"<tr><td class='what'><div class='model'>{esc(model)}</div></td>{cells}</tr>")
        heads = [("Model", "text")] + [(f"{MONTHS[int(m[5:]) - 1]} '{m[2:4]}", "") for m in p.months]
        parts.append(table(heads, rows))

    if p.weekday_new:
        top = max(v for _, v, _ in p.weekday_new) or 1
        rows = "".join(
            f"<tr><td>{esc(day)}</td><td class='num'>{avg:.1f}".replace(".", ",") + "</td>"
            f"<td><div class='meter' style='width:{avg / top * 100:.0f}%'></div></td>"
            f"<td class='num sub'>{n} dagen</td></tr>"
            for day, avg, n in p.weekday_new)
        parts.append("<h3>Nieuwe advertenties per weekdag</h3><p class='explain'>Gemiddeld per dag, gemeten aan de "
                     "rondes (de eerste ronde telt niet mee). Het uur van plaatsen geeft Marktplaats niet.</p>"
                     f"<div class='table-wrap'><table><tbody>{rows}</tbody></table></div>")
    return "\n".join(parts)


CSS = """
:root { color-scheme: light; --surface: #fcfcfb; --card: #ffffff; --line: #e4e3df;
  --text: #0b0b0b; --text-2: #52514e; --muted: #6b6a66; --accent: #2a78d6; --good: #0ca30c;
  --bad: #d03b3b; --badge: #e8f0fb; --fav: #fbeec2; }
@media (prefers-color-scheme: dark) { :root { color-scheme: dark; --surface: #1a1a19; --card: #222221;
  --line: #3a3a38; --text: #ffffff; --text-2: #c3c2b7; --muted: #a3a29a; --accent: #3987e5;
  --good: #0ca30c; --bad: #e06666; --badge: #23344a; --fav: #4a3c10; } }
* { box-sizing: border-box; }
body { margin: 0; padding: 20px 16px 48px; background: var(--surface); color: var(--text);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1200px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 4px; }
h3 { font-size: 1.05rem; margin: 28px 0 6px; }
a { color: var(--accent); }
.meta, .muted, .sub, .note { color: var(--muted); }
.meta { font-size: .9rem; margin-bottom: 14px; }
.sub { font-size: .78rem; margin-top: 2px; }
.note { font-size: .78rem; margin-top: 3px; }
nav.tabs { display: flex; gap: 4px; flex-wrap: wrap; border-bottom: 1px solid var(--line); margin-bottom: 16px; }
nav.tabs button { background: none; border: 0; border-bottom: 3px solid transparent; color: var(--text-2);
  font: inherit; padding: 8px 12px; cursor: pointer; }
nav.tabs button.active { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }
.panel[hidden] { display: none; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 4px 0 14px; }
.tile { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }
.tile .label { font-size: .85rem; color: var(--text-2); }
.tile .value { font-size: 1.7rem; font-weight: 600; margin-top: 2px; }
.explain { color: var(--text-2); font-size: .88rem; max-width: 90ch; }
.table-wrap { overflow-x: auto; background: var(--card); border: 1px solid var(--line); border-radius: 10px; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; text-align: left; }
tbody tr:last-child td { border-bottom: 0; }
th { font-size: .82rem; color: var(--text-2); font-weight: 600; white-space: nowrap; }
th[data-type] { cursor: pointer; }
th[data-type]::after { content: " ↕"; color: var(--muted); font-weight: 400; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.profit { font-size: 1.15rem; font-weight: 600; }
.gain { color: var(--good); font-size: .75rem; margin-right: 4px; }
td.pic { width: 76px; padding-right: 0; }
img.thumb, .thumb.empty { width: 64px; height: 64px; object-fit: cover; border-radius: 6px; display: block;
  background: var(--line); }
td.what { min-width: 260px; }
.model { font-weight: 600; }
.badge { display: inline-block; font-size: .7rem; font-weight: 700; padding: 1px 6px; border-radius: 8px;
  background: var(--badge); color: var(--text); vertical-align: 1px; }
.badge.reserved { background: var(--line); color: var(--text-2); }
.badge.fav { background: var(--fav); }
form.mark { margin-top: 4px; gap: 4px; }
form.mark button { font-size: .78rem; padding: 2px 8px; }
ul.changes { margin: 0; padding: 0; list-style: none; font-size: .82rem; }
ul.changes li::before { display: inline-block; width: 1.1em; font-weight: 700; }
ul.changes li.plus::before { content: "+"; color: var(--good); }
ul.changes li.minus::before { content: "−"; color: var(--bad); }
.filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 10px; }
.filters input[type=search], .filters select { font: inherit; padding: 6px 8px; border: 1px solid var(--line);
  border-radius: 6px; background: var(--card); color: var(--text); }
.filters input[type=search] { min-width: 240px; }
tr.hidden { display: none; }
.empty { color: var(--muted); padding: 12px 0; }
code { font-size: .85em; }
.banner { background: var(--badge); border-radius: 8px; padding: 10px 14px; margin: 0 0 14px; }
.owned { margin-top: 4px; font-size: .82rem; font-weight: 600; }
form.inline { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 6px; font-size: .85rem; }
form.inline input, form.inline select, .addform input, .addform select { font: inherit; padding: 3px 6px;
  border: 1px solid var(--line); border-radius: 6px; background: var(--card); color: var(--text); }
form.inline input[size] { width: auto; }
button { font: inherit; font-size: .85rem; padding: 4px 10px; border-radius: 6px; border: 1px solid var(--accent);
  background: var(--accent); color: #fff; cursor: pointer; }
button.quiet { background: none; color: var(--text-2); border-color: var(--line); }
nav.tabs button { font-size: inherit; border-radius: 0; }
.addform { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; background: var(--card);
  border: 1px solid var(--line); border-radius: 10px; padding: 12px; }
.addform label { display: flex; flex-direction: column; font-size: .8rem; color: var(--text-2); gap: 3px; }
svg.chart { width: 100%; max-width: 720px; height: auto; background: var(--card); border: 1px solid var(--line);
  border-radius: 10px; }
.meter { height: 10px; border-radius: 4px; background: var(--accent); min-width: 2px; }
svg.chart .bar { fill: var(--accent); }
svg.chart .axis { stroke: var(--line); }
svg.chart text { font-size: 15px; text-anchor: middle; fill: var(--text-2); }
svg.chart text.val { fill: var(--text); font-weight: 600; }
"""

JS = """
const buttons = document.querySelectorAll('nav.tabs button');
function show(name) {
  const target = document.getElementById('panel-' + name);
  if (!target) return;
  document.querySelectorAll('.panel').forEach(p => p.hidden = p !== target);
  buttons.forEach(b => b.classList.toggle('active', b.dataset.panel === name));
}
buttons.forEach(b => b.addEventListener('click', () => {
  show(b.dataset.panel); history.replaceState(null, '', '#' + b.dataset.panel);
}));
if (location.hash) show(location.hash.slice(1));
window.addEventListener('hashchange', () => show(location.hash.slice(1)));

// Favoriet/weg laadt de pagina opnieuw. Daarna wil je terug waar je was:
// dezelfde tab (de server stuurt terug naar de tab uit het formulier), en
// dezelfde plek en filters (die gaan via sessionStorage naar de nieuwe pagina).
const RESTORE = 'koopjes-terug';
let restore = null;
try {
  restore = JSON.parse(sessionStorage.getItem(RESTORE) || 'null');
  sessionStorage.removeItem(RESTORE);
  if (restore && restore.path !== location.pathname) restore = null;
} catch (_) { restore = null; }
document.addEventListener('submit', e => {
  const form = e.target;
  if (!form.classList.contains('mark')) return;
  const active = document.querySelector('nav.tabs button.active');
  form.querySelector("input[name='tab']").value = active ? active.dataset.panel : '';
  const filters = {};
  document.querySelectorAll('.filters [id]').forEach(el => {
    if (el.matches('input, select')) filters[el.id] = el.type === 'checkbox' ? el.checked : el.value;
  });
  try {
    sessionStorage.setItem(RESTORE, JSON.stringify({path: location.pathname, y: window.scrollY, filters}));
  } catch (_) {}
});

document.querySelectorAll('table.sortable').forEach(table => {
  const tbody = table.querySelector('tbody');
  table.querySelectorAll('th[data-type]').forEach((th, index) => {
    let asc = th.dataset.type !== 'num';
    th.addEventListener('click', () => {
      const col = Array.from(th.parentNode.children).indexOf(th);
      const rows = Array.from(tbody.rows);
      const key = r => {
        const cell = r.cells[col];
        if (th.dataset.type === 'num') {
          const v = parseFloat(cell.dataset.sort);
          return Number.isNaN(v) ? null : v;
        }
        return cell.textContent.trim().toLowerCase();
      };
      rows.sort((a, b) => {
        const x = key(a), y = key(b);
        if (x === null) return 1;
        if (y === null) return -1;
        return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1);
      });
      rows.forEach(r => tbody.appendChild(r));
      asc = !asc;
    });
  });
});

const search = document.getElementById('all-search');
const brand = document.getElementById('all-brand');
const markFilter = document.getElementById('all-mark');
const onlyNew = document.getElementById('all-new');
const count = document.getElementById('all-count');
function filterAll() {
  const q = search.value.trim().toLowerCase();
  const which = markFilter.value;
  let shown = 0;
  document.querySelectorAll('#all-table tbody tr').forEach(r => {
    // Standaard zonder weggezette; 'alles' toont ze erbij.
    const markOk = which === 'alles' || (which ? r.dataset.mark === which : r.dataset.mark !== 'weg');
    const ok = (!q || r.dataset.text.includes(q)) && (!brand.value || r.dataset.brand === brand.value)
      && (!onlyNew.checked || r.dataset.new === '1') && markOk;
    r.classList.toggle('hidden', !ok);
    if (ok) shown++;
  });
  count.textContent = shown + ' getoond';
}
if (restore) {
  Object.entries(restore.filters || {}).forEach(([id, value]) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (el.type === 'checkbox') el.checked = !!value;
    else if (el.tagName !== 'SELECT' || Array.from(el.options).some(o => o.value === value)) el.value = value;
  });
}
if (search) {
  [search, brand, markFilter, onlyNew].forEach(el => el.addEventListener('input', filterAll));
  filterAll();
}
if (restore) window.scrollTo(0, restore.y || 0);
"""


def render(d: Dashboard, overview_link: Optional[str] = None) -> str:
    m = d.market
    computers = len(d.items) + len(d.unknown_items)
    p = d.progress
    mine_label = f"Mijn flips ({signed_euro(p.realized_profit_eur)})" if p and p.sold else "Mijn flips"
    tabs = [("flips", f"Flips ({len(d.flips)})", flips_panel(d))]
    if m.has_upgrades:
        tabs.append(("upgrades", f"Upgrades ({len(d.upgrades)})", upgrades_panel(d)))
    tabs += [
        ("favorieten", f"Favorieten ({len(d.favorites)})", favorites_panel(d)),
        ("mijn", mine_label, mine_panel(d)),
        ("alle", f"Alle {m.items} ({computers})", all_panel(d)),
        ("markt", "Marktprijzen", market_panel(d)),
    ]
    if m.has_vinted:
        tabs.append(("vinted", f"Vinted ({len(d.vinted.flips)})" if d.vinted else "Vinted", vinted_panel(d)))
    tabs += [
        ("patronen", "Patronen", patterns_panel(d)),
        ("uitgefilterd", f"Uitgefilterd ({len(d.excluded)})", excluded_panel(d)),
    ]
    nav = "".join(
        f"<button data-panel='{name}'{' class=active' if i == 0 else ''}>{esc(label)}</button>"
        for i, (name, label, _) in enumerate(tabs)
    )
    panels = "".join(
        f"<section class='panel' id='panel-{name}'{'' if i == 0 else ' hidden'}>{body}</section>"
        for i, (name, _, body) in enumerate(tabs)
    )
    notices = ""
    if d.message:
        notices += f"<div class='banner' role='status'>{esc(d.message)}</div>"
    if not d.listings:
        notices += (f"<div class='banner'>Nog geen {esc(m.short.lower())} in de database. Draai eerst een ronde: "
                    "<code>python koopjes.py run nacht</code>.</div>")
    link = f" · <a href='{esc(overview_link, quote=True)}'>racefietsen: overzicht</a>" if overview_link else ""
    link += "".join(f" · <a href='{esc(href, quote=True)}'>{esc(label)}</a>" for label, href in d.other_links)
    new = f" ({len(d.new_ids)} nieuw)" if d.new_ids else ""
    live = " · <strong>live</strong> (wijzigingen gaan in koopjes.db)" if d.editable else ""
    meta = (f"Bijgewerkt {datetime.now().strftime('%d-%m-%Y %H:%M')} · {computers} {m.items} te koop{new} "
            f"· laatste ronde {local_time(d.newest_seen)}{link}{live}")
    return (
        "<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{esc(m.short)}</title><style>{CSS}</style></head><body><main>"
        f"<h1>{esc(m.title)}</h1>"
        f"<div class='meta'>{meta}</div>{notices}"
        f"<nav class='tabs'>{nav}</nav>{panels}"
        f"</main><script>{JS}</script></body></html>"
    )


def write_dashboard(db_path, out_path, overview_link: Optional[str] = None,
                    market: mk.Market = mk.COMPUTERS, other_links: Sequence = ()) -> Dashboard:
    """`other_links`: (label, href) naar de dashboards van de andere markten."""
    d = load_dashboard(db_path, market=market)
    d.other_links = list(other_links)
    Path(out_path).write_text(render(d, overview_link), encoding="utf-8")
    return d


# --- Live: --serve --------------------------------------------------------------


class FormError(ValueError):
    """Een formulier met iets dat niet klopt; de tekst gaat terug naar de pagina."""


def parse_euro(value: str, what: str, required: bool = True) -> Optional[float]:
    text = (value or "").replace("€", "").replace(" ", "").replace(",", ".")
    if not text:
        if required:
            raise FormError(f"{what} ontbreekt.")
        return None
    try:
        amount = float(text)
    except ValueError:
        raise FormError(f"{what} '{value}' is geen bedrag.") from None
    if amount < 0:
        raise FormError(f"{what} kan niet negatief zijn.")
    return round(amount, 2)


def parse_day(value: str) -> str:
    if not value:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise FormError(f"Datum '{value}' klopt niet (jjjj-mm-dd).") from None


def parse_id(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise FormError("Onbekende regel.") from None


def action_bought(db_path, form: dict) -> str:
    item_id = form.get("item_id", "")
    price = parse_euro(form.get("prijs"), "Inkoopprijs")
    market = mk.by_key(form.get("markt"))
    d = load_dashboard(db_path, market=market)
    listing = next((l for l in d.listings if l.item_id == item_id), None)
    if listing is None:
        raise FormError("Die advertentie staat niet (meer) in het dashboard; voeg hem zelf toe onder Mijn flips.")
    if item_id in d.bought:
        raise FormError(f"'{listing.title}' staat al in Mijn flips.")
    c = listing.computer
    conn = db.connect(str(db_path))
    try:
        db.add_trade(conn, title=listing.title, bought_at=parse_day(form.get("datum")), buy_price_eur=price,
                     item_id=item_id, url=listing.url, model=c.model.label if c else None,
                     expected_resale_eur=c.resale_eur if c else None, market=market.key)
    finally:
        conn.close()
    return f"Gekocht: {listing.title} voor {euro(price)}. Hij staat nu onder Mijn flips."


def action_mark(db_path, form: dict) -> str:
    """Favoriet, weg (met reden) of terug naar geen markering. Zetten kan
    alleen bij een advertentie die in het dashboard staat: de prijs van nu
    gaat mee, zodat een weggezette advertentie terugkomt als die zakt.
    Weghalen kan altijd, ook bij een favoriet die niet meer online is."""
    item_id = form.get("item_id", "")
    choice = form.get("soort", "")
    if choice == "geen":
        conn = db.connect(str(db_path))
        try:
            known = db.clear_mark(conn, item_id)
        finally:
            conn.close()
        if not known:
            raise FormError("Die advertentie had geen markering.")
        return "Markering weggehaald."
    if choice != mr.FAVORITE and choice not in mr.REASONS:
        raise FormError(f"Onbekende keuze '{choice}'.")
    market = mk.by_key(form.get("markt"))
    config = pc.default_config()
    listings, _, _ = load_active_listings(db_path, market.categories, config["dashboard"])
    listing = next((l for l in listings if l.item_id == item_id), None)
    if listing is None:
        raise FormError("Die advertentie staat niet (meer) in het dashboard.")
    conn = db.connect(str(db_path))
    try:
        if choice == mr.FAVORITE:
            db.set_mark(conn, item_id, mr.FAVORITE, price_eur=listing.price_eur)
        else:
            db.set_mark(conn, item_id, mr.DISMISSED, reason=choice, price_eur=listing.price_eur)
    finally:
        conn.close()
    if choice == mr.FAVORITE:
        return f"Favoriet: {listing.title}."
    again = (f" Hij komt terug als de prijs onder {euro(listing.price_eur)} zakt."
             if listing.price_eur is not None else "")
    return f"Weggezet ({choice}): {listing.title}.{again}"


def action_add(db_path, form: dict) -> str:
    title = (form.get("titel") or "").strip()
    if not title:
        raise FormError("Vul in wat het is.")
    model = form.get("model") or None
    target = mk.by_key(form.get("markt"))
    if model and model not in target.labels():
        raise FormError(f"Onbekend model '{model}'.")
    price = parse_euro(form.get("prijs"), "Inkoopprijs")
    costs = parse_euro(form.get("kosten"), "Kosten", required=False) or 0.0
    market = (pc.market_resale(db_path, catalog=target.catalog(), categories=target.comp_categories)
              if model else {})
    conn = db.connect(str(db_path))
    try:
        db.add_trade(conn, title=title, bought_at=parse_day(form.get("datum")), buy_price_eur=price,
                     buy_costs_eur=costs, model=model, expected_resale_eur=market.get(model),
                     notes=(form.get("notitie") or "").strip(), market=target.key)
    finally:
        conn.close()
    return f"Toegevoegd: {title} voor {euro(price)}."


def action_sold(db_path, form: dict) -> str:
    trade_id = parse_id(form.get("id"))
    price = parse_euro(form.get("prijs"), "Verkoopprijs")
    costs = parse_euro(form.get("kosten"), "Kosten", required=False) or 0.0
    via = form.get("via") if form.get("via") in ("marktplaats", "vinted", "anders") else "anders"
    sold_at = parse_day(form.get("datum"))
    bought = next((t for t in tr.load_trades(db_path) if t.id == trade_id), None)
    if bought is None:
        raise FormError("Onbekende regel.")
    if sold_at < bought.bought_at[:10]:
        raise FormError(f"Verkocht op {nl_date(sold_at)} ligt vóór de aankoop ({nl_date(bought.bought_at)}).")
    conn = db.connect(str(db_path))
    try:
        if not db.sell_trade(conn, trade_id, sold_at=sold_at, sell_price_eur=price,
                             sell_costs_eur=costs, sold_via=via):
            raise FormError("Onbekende regel.")
    finally:
        conn.close()
    return f"Verkocht voor {euro(price)}."


def action_unsell(db_path, form: dict) -> str:
    conn = db.connect(str(db_path))
    try:
        if not db.unsell_trade(conn, parse_id(form.get("id"))):
            raise FormError("Onbekende regel.")
    finally:
        conn.close()
    return "Terug naar voorraad."


def action_delete(db_path, form: dict) -> str:
    conn = db.connect(str(db_path))
    try:
        if not db.delete_trade(conn, parse_id(form.get("id"))):
            raise FormError("Onbekende regel.")
    finally:
        conn.close()
    return "Verwijderd."


ACTIONS = {
    "/gekocht": action_bought,
    "/toevoegen": action_add,
    "/verkocht": action_sold,
    "/terug": action_unsell,
    "/verwijder": action_delete,
    "/markeer": action_mark,
}
# Na deze acties terug naar de tab waar je klikte (het formulier zegt welke);
# na de rest naar Mijn flips, waar je ziet wat je vastlegde.
STAY_ON_TAB = {"/markeer"}
MAX_FORM_BYTES = 10_000


class DashboardHandler(BaseHTTPRequestHandler):
    """GET / toont het dashboard live; POST naar een van ACTIONS schrijft en
    stuurt terug naar de pagina (tab Mijn flips, of bij favoriet/weg de tab
    waar je klikte) met een melding.

    Alleen bereikbaar via 127.0.0.1. Een andere website kan je browser toch
    een formulier naar localhost laten sturen; daarom draagt elk formulier
    een geheim dat bij het starten wordt gekozen (token), en worden Host en
    Origin gecontroleerd (tegen DNS-rebinding)."""

    db_path = "koopjes.db"
    token = ""
    server_version = "koopjes-dashboard"

    def _origins(self) -> set:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self._origins()

    def _send(self, code: int, body: str, content_type: str = "text/plain; charset=utf-8") -> None:
        data = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # De browser verbrak de verbinding terwijl de pagina nog onderweg
            # was (ververst, gesloten, of twee keer geopend). Op Windows gaf dat
            # een traceback met WinError 10053 in het venster, terwijl er niets
            # mis is: de volgende aanvraag werkt gewoon.
            self.close_connection = True

    def _back(self, message: str, market: mk.Market = mk.COMPUTERS, tab: str = "mijn") -> None:
        # Alleen een tabnaam; iets anders (leeg, of wat een andere site
        # meestuurt) opent de eerste tab.
        anchor = f"#{tab}" if tab.isascii() and tab.isalpha() and tab.islower() else ""
        self.send_response(303)
        self.send_header("Location", market.serve_path + "?melding=" + quote(message) + anchor)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        path = "/" if url.path == "/index.html" else url.path.rstrip("/") or "/"
        market = next((m for m in mk.MARKETS.values() if m.serve_path == path), None)
        if market is None:
            return self._send(404, "Niet gevonden")
        if not self._host_ok():
            return self._send(403, "Alleen via 127.0.0.1")
        d = load_dashboard(self.db_path, market=market)
        d.editable, d.token = True, self.token
        d.other_links = [(m.short, m.serve_path) for m in mk.MARKETS.values() if m is not market]
        d.message = parse_qs(url.query).get("melding", [""])[0][:300]
        self._send(200, render(d), "text/html; charset=utf-8")

    def do_POST(self) -> None:
        origin = self.headers.get("Origin")
        if not self._host_ok() or (origin and urlsplit(origin).netloc not in self._origins()):
            return self._send(403, "Alleen via 127.0.0.1")
        path = urlsplit(self.path).path
        action = ACTIONS.get(path)
        if action is None:
            return self._send(404, "Niet gevonden")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_FORM_BYTES:
            return self._send(413, "Te groot")
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        form = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
        market = mk.by_key(form.get("markt"))
        tab = form.get("tab", "") if path in STAY_ON_TAB else "mijn"
        if not hmac.compare_digest(form.get("token", ""), self.token):
            # Een verouderde pagina (programma opnieuw gestart) of een
            # andere site: niets doen, alleen de verse pagina tonen.
            return self._back("De pagina was verouderd; er is niets opgeslagen. Probeer het opnieuw.", market, tab)
        try:
            message = action(self.db_path, form)
        except FormError as exc:
            message = f"Niet opgeslagen: {exc}"
        self._back(message, market, tab)

    def log_message(self, format: str, *args) -> None:
        pass  # geen regel per verzoek in de terminal


def make_server(db_path, port: int = 8765) -> ThreadingHTTPServer:
    """De server, klaar om te draaien (serve_forever). Migreert de database
    eerst, zodat de tabellen `trade` en `listing_mark` bestaan."""
    db.connect(str(db_path)).close()
    handler = type("Handler", (DashboardHandler,), {"db_path": str(db_path), "token": secrets.token_urlsafe(24)})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def serve(db_path, port: int, open_browser: bool) -> int:
    try:
        httpd = make_server(db_path, port)
    except OSError as exc:
        print(f"Kan niet starten op poort {port}: {exc}. Probeer --port met een ander getal.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"Dashboard live op {url} (sporthorloges: {url}horloges) — stoppen met Ctrl+C.")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nGestopt.")
    finally:
        httpd.server_close()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Bouw dashboard.html met alle fietscomputers uit koopjes.db "
                                                 "(of dashboard_horloges.html met de sporthorloges).")
    parser.add_argument("--db", default="koopjes.db")
    parser.add_argument("--markt", choices=[*mk.MARKETS, "alle"], default=mk.COMPUTERS.key,
                        help="welk dashboard (standaard fietscomputers; 'alle' schrijft ze allebei)")
    parser.add_argument("--out", help="uitvoerbestand (standaard dashboard.html, dashboard_horloges.html); "
                                      "alleen bij één markt")
    parser.add_argument("--open", action="store_true", help="open het dashboard in de browser")
    parser.add_argument("--serve", action="store_true",
                        help="toon het dashboard live, met knoppen om aan- en verkopen vast te leggen "
                             "en advertenties als favoriet te bewaren of weg te zetten")
    parser.add_argument("--port", type=int, default=8765, help="poort voor --serve (standaard 8765)")
    parser.add_argument("--no-browser", action="store_true", help="bij --serve de browser niet openen")
    args = parser.parse_args(argv)
    if not Path(args.db).exists():
        print(f"Database {args.db} bestaat niet. Draai eerst een ronde: python koopjes.py run nacht",
              file=sys.stderr)
        return 1
    if args.serve:
        return serve(args.db, args.port, not args.no_browser)
    chosen = list(mk.MARKETS.values()) if args.markt == "alle" else [mk.MARKETS[args.markt]]
    if args.out and len(chosen) > 1:
        print("--out kan alleen bij één markt; laat hem weg bij --markt alle.", file=sys.stderr)
        return 1
    written = []
    for market in chosen:
        out = args.out or (DEFAULT_OUT if market is mk.COMPUTERS else market.dashboard_file)
        base = Path(out).resolve().parent
        overview = "overzicht.html" if (base / "overzicht.html").exists() else None
        others = [(m.short, m.dashboard_file) for m in mk.MARKETS.values()
                  if m is not market and (base / m.dashboard_file).exists()]
        d = write_dashboard(args.db, out, overview, market, others)
        extra = f", {len(d.upgrades)} upgrades" if market.has_upgrades else ""
        print(f"Dashboard: {out} — {len(d.items) + len(d.unknown_items)} {market.items}, "
              f"{len(d.flips)} flips{extra}, {len(d.excluded)} uitgefilterd")
        written.append(out)
    if args.open:
        for out in written:
            webbrowser.open(Path(out).resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
