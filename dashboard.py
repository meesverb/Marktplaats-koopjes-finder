"""Het dashboard: één pagina voor alles wat er op Marktplaats aan
fietscomputers te koop staat, in plaats van een rapport per zoekterm. En net
zo'n pagina voor de sporthorloges (markets.py beschrijft de markten).

    python dashboard.py                 # schrijft dashboard.html uit koopjes.db
    python dashboard.py --open          # en opent hem
    python dashboard.py --markt sporthorloges   # dashboard_horloges.html
    python dashboard.py --markt alle    # beide
    python dashboard.py --serve         # live in de browser, met Gekocht/Verkocht-knoppen
                                        # en favoriet/weg/notitie/controleer per advertentie
                                        # (fietscomputers op /, sporthorloges op /horloges)
                                        # en /flips: al je flips met klussenlijst en totalen

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
koopjes.db (tabel `trade`, zie trades.py), om advertenties als favoriet te
bewaren of weg te zetten (tabel `listing_mark`, zie marks.py) en om er een
notitie bij te zetten (tabel `listing_note`). Dat is het enige dat hier
schrijft. Plus de knop controleer: die haalt één advertentie nu op bij
Marktplaats en legt vast of hij gereserveerd is, wat erop geboden is en of
hij er nog staat (recheck.py).
"""
from __future__ import annotations

import argparse
import statistics
import sys
import webbrowser
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Sequence

import computers as pc
import crawl
import db
import distance as dm
import flips as fl
import markets as mk
import marks as mr
import own_bids as ob
import pages as pg
import patterns as pt
import trades as tr
import util
from util import euro, local_time
import views as vw
import vinted as vn

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = "dashboard.html"


@dataclass
class Unknown:
    """Een advertentie zonder bekend model: een computer (of horloge) met
    onbekend model, of iets dat is uitgefilterd."""
    listing: crawl.Listing
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
    view_patterns: Optional[vw.ViewPatterns] = None  # Patronen: weergaven en likes
    bought: dict = field(default_factory=dict)  # item_id -> Trade
    marks: dict = field(default_factory=dict)  # item_id -> marks.Mark
    notes: dict = field(default_factory=dict)  # item_id -> eigen notitie
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
    # Per klik vers, net als marks en notes (LiveCache.dashboard()):
    bids: dict = field(default_factory=dict)  # item_id -> own_bids.BidTrail
    stats: dict = field(default_factory=dict)  # item_id -> views.Latest
    home: Optional[dm.Home] = None  # de eigen postcode (distance.py)
    distances: dict = field(default_factory=dict)  # item_id -> distance.Distance
    # Verwachte verkoopprijs per model (Marktprijzen, model_resale()), één
    # keer per opbouw; None: nog niet uitgerekend.
    resale_by_model: Optional[dict] = None
    fast_by_model: Optional[dict] = None  # {modellabel: [prijs]} snel verkocht (computers.fast_sold())

    # De signalen heten .computer omdat ze uit computers.py komen; bij de
    # sporthorloges zijn het horloges.
    @property
    def items(self) -> list:
        return pc.active_computers(self.listings)

    @property
    def unknown_items(self) -> list:
        return [u for u in self.unknown if u.kind == self.market.item]

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

    def to_review(self, listing) -> bool:
        """Te beoordelen, zoals op /racefietsen: geen markering, geen bod van
        jou, niet gekocht en niet gereserveerd. Elke pagina dezelfde
        weergaven (de eigenaar, 02-10-2026)."""
        return (not self.is_favorite(listing) and not self.is_dismissed(listing)
                and listing.item_id not in self.bought and not listing.reserved
                and listing.item_id not in self.bids)

    @property
    def all_rows(self) -> list:
        """(advertentie, modellabel, signalen) voor alles in Alle computers."""
        rows = [(l, l.computer.model.label, l.computer) for l in self.items]
        return rows + [(u.listing, "model onbekend", None) for u in self.unknown_items]

    @property
    def favorites(self) -> list:
        return [row for row in self.all_rows if self.is_favorite(row[0])]

    def unknown_reasons(self) -> dict:
        """{id(advertentie): reden} voor wat geen bekend model heeft; Alle
        computers zocht de reden per rij door de hele lijst."""
        return {id(u.listing): u.reason for u in self.unknown}

    def bid_trails(self) -> list:
        """Eigen biedingen van deze markt: op een advertentie die hier staat,
        of die er stond (de categorie in de URL). Lopend eerst."""
        return [t for t in ob.ordered(self.bids)
                if any(f"/{c}/" in (t.url or "") for c in self.market.categories)]

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


def load_dashboard(db_path, config: Optional[dict] = None, market: mk.Market = mk.COMPUTERS) -> Dashboard:
    """De actieve advertenties in de categorieën van `market`: niet verdwenen
    en gezien binnen `active_days` van de nieuwste waarneming. Relatief aan de
    nieuwste en niet aan nu, zodat een dashboard na een week zonder rondes
    niet leeg is maar de stand van de laatste ronde laat zien."""
    config = config or pc.default_config()
    d = load_base(db_path, config, market)
    return replace(d, **fresh_parts(db_path))


def fresh_parts(db_path) -> dict:
    """Wat per klik kan veranderen en goedkoop is: markeringen, notities,
    eigen biedingen, de laatste weergaven/likes en de afstanden (een andere
    postcode geldt meteen)."""
    home, distances = dm.load(db_path)
    return {"marks": mr.load_marks(db_path), "notes": mr.load_notes(db_path), "bids": ob.load(db_path),
            "stats": vw.load_latest(db_path), "home": home, "distances": distances}


def load_base(db_path, config: dict, market: mk.Market = mk.COMPUTERS) -> Dashboard:
    """Alles behalve de eigen markeringen en notities: het zware deel
    (vergelijkingsprijzen, flips, patronen), dat de live server onthoudt
    tussen twee klikken (LiveCache)."""
    # De vergelijkingsprijzen één keer: de flips, de voorraad in Mijn flips en
    # Marktprijzen rekenen alle drie met dezelfde advertenties. Marktprijzen
    # las ze vroeger bij elke paginaweergave opnieuw (1-2 s per klik op F5).
    rows = (pc.comparable_rows(db_path, market.catalog(), config["flip"]["comp_window_days"],
                               market.comp_categories) if Path(db_path).exists() else [])
    d = _with_trades(_load_market(db_path, config, market, rows), db_path, rows)
    d.resale_by_model = pc.market_resale(db_path, catalog=market.catalog(), config=config,
                                         categories=market.comp_categories, rows=rows)
    d.fast_by_model = pc.fast_sold(rows)
    d.patterns = pt.load_patterns(db_path, config, market)
    d.view_patterns = vw.load_patterns(db_path, market.categories)
    d.vinted = vn.load_view(db_path, config) if market.has_vinted else None
    d.db_path = str(Path(db_path).resolve())
    return d


def _with_trades(d: Dashboard, db_path, rows: Optional[list] = None) -> Dashboard:
    """Mijn flips erbij: de eigen trades van deze markt, met de huidige
    marktwaarde per model. `bought` kent alle trades: wat gekocht is, is geen
    kans meer, uit welk dashboard het ook gekocht werd."""
    everything = tr.load_trades(db_path)
    # Een fiets of spullen van /flips horen bij geen dashboard; zonder dit
    # maakte markets.by_key() er een fietscomputer van.
    trades = [t for t in everything if (t.market or "") not in fl.OWN_MARKETS and mk.trade_market(t) is d.market]
    own_ids = frozenset(t.item_id for t in everything if t.item_id)
    market = (pc.market_resale(db_path, catalog=d.market.catalog(), config=d.config, exclude=own_ids,
                               categories=d.market.comp_categories, rows=rows)
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
    conn = db.connect_readonly(db_path, rows=True)
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(listing)")}
        images = "image_urls" if "image_urls" in columns else "'' AS image_urls"
        asking = "price_is_asking" if "price_is_asking" in columns else "NULL AS price_is_asking"
        reserved = "reserved_at" if "reserved_at" in columns else "NULL AS reserved_at"
        bids = ("bid_count, bid_minimum, bids_checked_at" if "bids_checked_at" in columns
                else "NULL AS bid_count, NULL AS bid_minimum, NULL AS bids_checked_at")
        checked = ("bid_high, checked_at" if "checked_at" in columns
                   else "NULL AS bid_high, NULL AS checked_at")
        where = " OR ".join("url LIKE ?" for _ in categories)
        rows = conn.execute(
            f"SELECT item_id, title, description, price_eur, price_type, is_bid, {asking}, "
            f"city, posted_date, condition, url, first_seen, last_seen, {images}, {reserved}, {bids}, {checked} "
            f"FROM listing WHERE disappeared_at IS NULL AND ({where})",
            tuple(f"%/{category}/%" for category in categories),
        ).fetchall()
    finally:
        conn.close()

    seen = [t for t in (util.parse_time(r["last_seen"]) for r in rows) if t]
    if not seen:
        return [], None, set()
    newest = max(seen)
    active_since = newest - timedelta(days=settings["active_days"])
    new_since = newest - timedelta(hours=settings["new_hours"])

    listings, new_ids = [], set()
    for r in rows:
        last = util.parse_time(r["last_seen"])
        if last is None or last < active_since:
            continue
        listing = crawl.listing_from_row(r)
        first = util.parse_time(r["first_seen"])
        if first and first >= new_since:
            new_ids.add(listing.item_id)
        listings.append(listing)
    if len(new_ids) == len(listings):
        # De allereerste ronde: alles is "nieuw", en dan zegt het label niets.
        new_ids = set()
    return listings, newest, new_ids


def _load_market(db_path, config: dict, market: mk.Market = mk.COMPUTERS, rows: Optional[list] = None) -> Dashboard:
    listings, newest, new_ids = load_active_listings(db_path, market.categories, config["dashboard"])
    if newest is None:
        return Dashboard([], config=config, market=market)

    catalog = market.catalog()
    pc.apply_computer_signals(listings, db_path=db_path, catalog=catalog, config=config,
                              comp_categories=market.comp_categories, rows=rows)
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
    if d.resale_by_model is not None:
        return d.resale_by_model
    if not d.db_path:
        return {}
    return pc.market_resale(d.db_path, catalog=d.market.catalog(), config=d.config,
                            categories=d.market.comp_categories)


def model_fast(d: Dashboard) -> dict[str, list]:
    """{modellabel: [prijs]} van de snel verkochte (computers.fast_sold())."""
    if d.fast_by_model is not None:
        return d.fast_by_model
    if not d.db_path:
        return {}
    return pc.fast_sold(pc.comparable_rows(d.db_path, d.market.catalog(), d.config["flip"]["comp_window_days"],
                                           d.market.comp_categories))


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


def band(low: Optional[float], high: Optional[float]) -> str:
    if low is None or high is None:
        return ""
    if round(low) == round(high):
        return f"weinig spreiding ({euro(low)})"
    return f"{euro(low)} tot {euro(high)}"


def comp_text(c) -> str:
    """Waarmee de verkoopprijs is vergeleken, kort: dezelfde uitvoering of het
    hele model, en of hij op de snel verkochte rust
    (computers.apply_computer_signals())."""
    fast = f"{c.fast_count} snel verkocht" if c.comp_basis == "snel verkocht" else ""
    if c.comp_scope == "uitvoering":
        return f"{fast or f'n={c.comp_count}'}, zelfde uitvoering: {c.variant.label}"
    if c.variant is not None and c.variant_comp_count < c.model_comp_count:
        return f"{fast or f'n={c.comp_count}'}, hele model; {c.variant.label}: {c.variant_comp_count}"
    return fast or f"n={c.comp_count} vergelijkbaar"


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


def mark_badges(listing, d: Dashboard) -> str:
    """Favoriet of weggezet, als badges. In een eigen span (class markbadge)
    zodat de live pagina ze na een klik kan vervangen zonder te herladen."""
    out = "<span class='badge fav'>★ favoriet</span> " if d.is_favorite(listing) else ""
    if d.is_dismissed(listing):
        out += f"<span class='badge reserved'>{pg.esc(d.marks[listing.item_id].label)}</span> "
    return out


def own_controls(listing, d: Dashboard) -> str:
    """Favoriet/weg, je bod en de notitie: wat een klik verandert (div class mine)."""
    return mark_control(listing, d) + bid_control(listing.item_id, d) + note_control(listing.item_id, d)


def stats_line(item_id: str, d: Dashboard) -> str:
    """De laatste meting van weergaven en likes (views.py), als die er is."""
    latest = d.stats.get(item_id)
    if latest is None or not latest.label:
        return ""
    delta = (f" ({'+' if latest.fav_delta > 0 else ''}{latest.fav_delta} bewaard sinds "
             f"{pg.nl_date(latest.previous_at)})" if latest.fav_delta else "")
    return f"<div class='note'>{pg.esc(latest.label)}{pg.esc(delta)} · gemeten {pg.esc(pg.nl_date(latest.observed_at))}</div>"


def km_of(listing, d: Dashboard) -> Optional[dm.Distance]:
    return d.distances.get(listing.item_id)


def km_cell(listing, d: Dashboard) -> str:
    dist = km_of(listing, d)
    return (f"<td class='num' data-sort='{'' if dist is None else f'{dist.km:.1f}'}'>"
            f"{'—' if dist is None else pg.esc(dist.label)}</td>")


def listing_cell(listing, d: Dashboard, model_label: str, note: str = "") -> str:
    item = pg.esc(listing.item_id, quote=True)
    new = f"<span class='markbadge' data-item='{item}'>{mark_badges(listing, d)}</span>"
    new += "<span class='badge'>nieuw</span> " if listing.item_id in d.new_ids else ""
    if listing.reserved:
        new += "<span class='badge reserved'>gereserveerd</span> "
    dist = km_of(listing, d)
    place = f" · {pg.esc(listing.city)}" if listing.city else ""
    place += f" · {pg.esc(dist.label)}" if dist else ""
    note_html = f"<div class='note'>{pg.esc(note)}</div>" if note else ""
    # data-km: voor het schuifje "max. afstand" bovenaan (JS), op elke tab.
    km = "" if dist is None else f"{dist.km:.1f}"
    return (
        f"<td class='what' data-km='{km}'><div class='model'>{new}{pg.esc(model_label)}</div>"
        f"<a href='{pg.esc(listing.url, quote=True)}' target='_blank' rel='noopener'>{pg.esc(listing.title)}</a>"
        f"<span class='muted'>{place}</span>{note_html}{stats_line(listing.item_id, d)}"
        f"<div class='mine' data-item='{item}'>{own_controls(listing, d)}</div>{buy_control(listing, d)}</td>"
    )


def hidden(d: Dashboard, **values) -> str:
    fields = {"token": d.token, "markt": d.market.key, **values}
    return "".join(f"<input type='hidden' name='{k}' value='{pg.esc(str(v), quote=True)}'>" for k, v in fields.items())


def buy_control(listing, d: Dashboard) -> str:
    """"Gekocht" bij een advertentie: een badge als hij al in Mijn flips
    staat, anders (alleen live) een knop met de prijs alvast ingevuld."""
    trade = d.bought.get(listing.item_id)
    if trade:
        return (f"<div class='owned'>✓ gekocht op {pg.esc(pg.nl_date(trade.bought_at))} voor "
                f"{euro(trade.buy_price_eur)}</div>")
    if not d.editable:
        return ""
    price = "" if listing.price_eur is None else f"{listing.price_eur:.0f}"
    return pg.act("/gekocht", listing.item_id,
               f"<label>€<input name='prijs' value='{price}' inputmode='decimal' size='5' "
               "aria-label='Inkoopprijs'></label><button>Gekocht</button>")


def mark_control(listing, d: Dashboard) -> str:
    """Favoriet of weg bij een advertentie (alleen live), en de regel dat een
    weggezette advertentie terug is omdat de prijs zakte (ook in de
    geschreven pagina). Eén rij knoppen; de knop die je indrukt, zegt wat."""
    mark = d.marks.get(listing.item_id)
    back = mark is not None and mark.mark == mr.DISMISSED and mr.price_dropped(mark, listing)
    note = (f"<div class='note'>Weer terug: de prijs zakte van {euro(mark.price_eur)} naar "
            f"{euro(listing.price_eur)} sinds je hem wegzette ({pg.esc(mark.reason or 'weg')}).</div>"
            if back else "")
    if not d.editable:
        return note

    def button(value: str, label: str) -> str:
        return f"<button class='quiet' name='soort' value='{pg.esc(value, quote=True)}'>{pg.esc(label)}</button>"

    away = "<span class='muted'>weg:</span>" + "".join(button(r, r) for r in mr.REASONS)
    if d.is_dismissed(listing):
        buttons = button("geen", "terugzetten") + button(mr.FAVORITE, "☆ favoriet")
    elif mark is not None and mark.favorite:
        buttons = button("geen", "★ uit favorieten") + away
    else:
        buttons = button(mr.FAVORITE, "☆ favoriet") + away + (button("geen", "wissen") if back else "")
    return note + pg.act("/markeer", listing.item_id, buttons + check_button(listing), "mark")


def check_button(listing) -> str:
    """"controleer": haalt de advertentie nu op bij Marktplaats (recheck.py).
    Bij favoriet/weg, met een eigen data-action, zodat het op dezelfde regel
    staat en na de klik op dezelfde tab en plek terugkomt."""
    checked = getattr(listing, "checked_at", None)
    when = f"<span class='muted'>gecontroleerd {pg.esc(local_time(checked))}</span>" if checked else ""
    # Het puntje scheidt hem van "weg: niet waard / gereserveerd", waar hij
    # anders een derde reden om weg te zetten lijkt.
    return ("<span class='muted'>·</span><button class='quiet' data-action='/controleer' "
            "title='Haalt deze advertentie nu op bij "
            "Marktplaats: gereserveerd, biedingen, prijs, en of hij er nog staat.'>controleer</button>" + when)


def bid_summary(trail) -> str:
    """"jouw bod €120 (open) · eerder €100" en of er intussen hoger geboden is."""
    last = trail.latest
    text = f"jouw bod {euro(last.amount_eur)} ({last.status}, {pg.nl_date(last.bid_at)})"
    if len(trail.bids) > 1:
        text += " · eerder " + ", ".join(euro(b.amount_eur) for b in trail.bids[:-1])
    if trail.outbid and trail.active:
        text += f" · er staat al {euro(trail.bid_high)} op"
    return text


def bid_control(item_id: str, d: Dashboard) -> str:
    """Je eigen bod (own_bids.py): wat je bood en hoe het ervoor staat, en
    (live) een veld om een bod vast te leggen en knoppen voor de status.
    Ingeklapt tot je erop klikt, net als de notitie."""
    trail = d.bids.get(item_id)
    shown = f"<div class='mynote'>{pg.esc(bid_summary(trail))}</div>" if trail else ""
    if not d.editable:
        return shown
    status = ""
    if trail:
        status = "".join(
            f"<button class='quiet' data-action='/bod/status' name='status' value='{pg.esc(st, quote=True)}'>"
            f"{pg.esc(st)}</button>" for st in ob.STATUSES if st != trail.status)
        status = pg.act("/bod/status", item_id, "<span class='muted'>status:</span>" + status, "mark")
    return (
        f"{shown}<details class='note-edit'><summary>{'bod wijzigen' if trail else 'ik heb geboden'}</summary>"
        + pg.act("/bod", item_id,
              "<label>€<input name='bedrag' inputmode='decimal' size='5' aria-label='Bod'></label>"
              f"<button class='quiet'>{'nieuw bod' if trail else 'bod vastleggen'}</button>", "mark")
        + status + "</details>"
    )


def bids_panel(d: Dashboard) -> str:
    """Tab Mijn biedingen: wat je zelf op Marktplaats bood, lopend eerst."""
    trails = d.bid_trails()
    parts = [f"<p class='explain'>Wat je zelf op Marktplaats bood (bieden doe je daar, het script nooit). Leg een "
             f"bod vast bij een advertentie met <em>ik heb geboden</em>; zet de status als je antwoord krijgt. "
             f"<em>Geaccepteerd</em> zet hem meteen op <a href='{pg.FLIPS_PATH}'>/flips</a>, met je bod als "
             "inkoopprijs. <em>Er staat al … op</em>: volgens de laatste biedopvraging of controleer.</p>"]
    if not trails:
        parts.append("<p class='empty'>Nog geen biedingen vastgelegd.</p>")
        return "\n".join(parts)
    by_id = {l.item_id: (l, label) for l, label, _ in d.all_rows}
    rows = []
    for t in trails:
        found = by_id.get(t.item_id)
        if found:
            l, label = found
            rows.append(f"<tr><td class='pic'>{pg.thumb(l)}</td>{price_cell(l)}{km_cell(l, d)}"
                        f"{listing_cell(l, d, label)}</tr>")
        else:
            when = f"verdwenen {pg.nl_date(t.disappeared_at)}" if t.gone else f"laatst gezien {pg.nl_date(t.last_seen)}"
            link = (f"<a href='{pg.esc(pg.web_link(t.url), quote=True)}' target='_blank' rel='noopener'>{pg.esc(t.title)}</a>"
                    if pg.web_link(t.url) else pg.esc(t.title))
            rows.append(f"<tr><td class='pic'></td><td class='num'>{euro(t.price_eur)}</td><td class='num'>—</td>"
                        f"<td class='what'>{link}<div class='note'>{pg.esc(when)}</div>"
                        f"<div class='mine' data-item='{pg.esc(t.item_id, quote=True)}'>"
                        f"{bid_control(t.item_id, d)}</div></td></tr>")
    parts.append(pg.table([("", ""), ("Prijs", "num"), ("Afstand", "num"), ("Advertentie", "text")], rows))
    return "\n".join(parts)


def note_control(item_id: str, d: Dashboard) -> str:
    """Je eigen notitie bij een advertentie, en (live) een veld om hem te
    zetten. Ingeklapt tot je erop klikt: de meeste rijen hebben er geen, en
    een invulveld per rij maakt Flips onleesbaar."""
    note = d.notes.get(item_id)
    shown = f"<div class='mynote'>{pg.esc(note)}</div>" if note else ""
    if not d.editable:
        return shown
    return (
        f"{shown}<details class='note-edit'><summary>{'notitie wijzigen' if note else 'notitie toevoegen'}"
        "</summary>"
        + pg.act("/notitie", item_id,
              f"<input name='notitie' value='{pg.esc(note or '', quote=True)}' maxlength='{mr.NOTE_MAX_CHARS}' "
              "size='36' aria-label='Notitie' placeholder='bv. gevraagd of €120 kan'>"
              "<button class='quiet'>opslaan</button>", "mark")
        + "</details>"
    )


def bid_note(listing) -> str:
    """Wat de biedopvraging zei: aantal biedingen en minimumbod, met wanneer
    — een bod van de nachtronde kan overdag al hoger zijn."""
    count = getattr(listing, "bid_count", None)
    checked = getattr(listing, "bids_checked_at", None)
    if count is None or not checked:
        return ""
    parts = [f"{count} bieding{'en' if count != 1 else ''}" if count else "nog geen bod"]
    high = getattr(listing, "bid_high", None)
    if count and high is not None and high != listing.price_eur:
        parts.append(f"hoogste {euro(high)}")
    if listing.bid_minimum:
        parts.append(f"min. {euro(listing.bid_minimum)}")
    parts.append(f"opgehaald {local_time(checked)}")
    return " · ".join(parts)


def price_cell(listing, extra: str = "") -> str:
    kind = pc.price_kind(listing)
    note = bid_note(listing)
    return (f"<td class='num' data-sort='{listing.price_eur if listing.price_eur is not None else ''}'>"
            f"{euro(listing.price_eur)}<div class='sub'>{pg.esc(kind)}</div>"
            f"{f'<div class=sub>{pg.esc(note)}</div>' if note else ''}"
            f"{f'<div class=sub>{pg.esc(extra)}</div>' if extra else ''}</td>")


def flips_tiles(d: Dashboard) -> str:
    flip = d.config["flip"]
    flips = d.flips
    best = flips[0] if flips else None
    return pg.tiles([
        ("Flips met winst", str(len(flips)), f"na {euro(flip.get('costs_eur', 0))} verzendkosten per stuk"),
        ("Beste flip", euro(best.computer.profit_eur, sign=True) if best else "—",
         best.computer.model.label if best else "nog niets"),
        ("Samen", euro(sum(l.computer.profit_eur for l in flips)) if flips else "—",
         "als je ze allemaal koopt en verkoopt"),
        ("Zonder prijs", str(len(d.open_bids)), "met een maximaal bod"),
    ])


def flips_away(d: Dashboard) -> str:
    """Hoeveel flips je wegzette, in een eigen div (class away): de live
    pagina vervangt hem na een klik, net als de tegels."""
    away = d.dismissed_flips
    if not away:
        return "<div class='away'></div>"
    return (
        f"<div class='away'><p class='explain'>{len(away)} flip{'s' if len(away) != 1 else ''} weggezet (niet "
        f"waard of gereserveerd): terug te vinden in Alle {pg.esc(d.market.items)} met <em>Toon: weggezet</em>. "
        "Zakt de prijs onder die van toen je hem wegzette, dan staat hij hier weer.</p></div>")


def flips_panel(d: Dashboard) -> str:
    flip = d.config["flip"]
    flips = d.flips
    parts = [flips_tiles(d)]
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
        f"× {str(flip['negotiation_factor']).replace('.', ',')} voor afdingen. Zijn daaronder minstens "
        f"{pc.MIN_FAST} <em>snel verkocht</em> (binnen {pc.FAST_DAYS} dagen weg, of gereserveerd en daarna weg), "
        "dan is het de mediaan van hún laatste vraagprijs, zonder afdingen (\"3 snel verkocht\" onder de "
        "verkoopprijs). De band eronder is de winst "
        "bij het goedkoopste en duurste kwart van die advertenties. Bij <em>huidig bod</em> loopt de prijs "
        "nog op; bij <em>vraagprijs, bieden kan</em> kun je vaak lager uitkomen, maar er kan ook al hoger "
        "geboden zijn: die biedingen staan alleen op de advertentiepagina. Gereserveerde advertenties "
        f"staan hier niet (wel in Alle {d.market.items}) en tellen niet als vergelijkingsprijs zolang ze online staan.</p>"
    )
    parts.append(
        "<p class='explain'>Dit is wat de laatste ronde zag; overdag komen alleen de nieuwste advertenties "
        "langs, de rest in de nachtronde. "
        + ("<strong>controleer</strong> bij een advertentie haalt hem nu op bij Marktplaats: gereserveerd, "
           "biedingen, prijs, en of hij er nog staat.</p>" if d.editable else
           "In de live versie (<code>python dashboard.py --serve</code>) haalt <strong>controleer</strong> bij een "
           "advertentie hem nu op bij Marktplaats: gereserveerd, biedingen, prijs, en of hij er nog staat.</p>")
    )
    parts.append(flips_away(d))
    if flips:
        rows = []
        for l in flips:
            c = l.computer
            rows.append(
                "<tr>"
                f"<td class='pic'>{pg.thumb(l)}</td>"
                f"<td class='num profit' data-sort='{c.profit_eur}'>"
                f"<span class='gain' aria-hidden='true'>▲</span>{euro(c.profit_eur, sign=True)}"
                f"<div class='sub'>{band(c.profit_low_eur, c.profit_high_eur)}</div></td>"
                f"{price_cell(l)}"
                f"<td class='num' data-sort='{c.resale_eur}' title='{pg.esc(c.comp_note, quote=True)}'>{euro(c.resale_eur)}"
                f"<div class='sub'>{pg.esc(comp_text(c))}</div></td>"
                f"{km_cell(l, d)}{listing_cell(l, d, c.model.label, c.reason)}"
                "</tr>"
            )
        parts.append(pg.table([("", ""), ("Winst", "num"), ("Inkoop", "num"), ("Verkoop", "num"),
                            ("Afstand", "num"), ("Advertentie", "text")], rows))
    else:
        parts.append(f"<p class='empty'>Geen {d.market.item} die onder de verwachte verkoopprijs staat.</p>")

    if d.open_bids:
        parts.append("<h3>Zonder prijs — bied maximaal</h3>"
                     "<p class='explain'>Bieden zonder minimum of geen prijs genoemd. Het maximale bod is de "
                     "lage verkoopschatting min verzendkosten: daarboven speel je bij een tegenvaller verlies.</p>")
        rows = [
            "<tr>"
            f"<td class='pic'>{pg.thumb(l)}</td>"
            f"<td class='num' data-sort='{l.computer.max_bid_eur}'><strong>{euro(l.computer.max_bid_eur)}</strong>"
            f"<div class='sub'>verkoop ±{euro(l.computer.resale_eur)}, {pg.esc(comp_text(l.computer))}</div></td>"
            f"<td class='num'>{pg.esc(pc.price_kind(l))}</td>"
            f"{listing_cell(l, d, l.computer.model.label, l.computer.reason)}"
            "</tr>"
            for l in d.open_bids
        ]
        parts.append(pg.table([("", ""), ("Bied max.", "num"), ("Prijs", ""), ("Advertentie", "text")], rows))
    return "\n".join(parts)


def upgrades_tiles(d: Dashboard) -> str:
    base = pc.baseline_model(config=d.config)
    ups = d.upgrades
    own = ups[0].computer.own_resale_eur if ups else None
    nets = [l.computer.net_upgrade_cost_eur for l in ups if l.computer.net_upgrade_cost_eur is not None]
    base_label = base.label if base else "eigen computer"
    return pg.tiles([
        ("Upgrades te koop", str(len(ups)), f"kunnen meer dan je {base_label}"),
        (f"Je {base.model if base else 'computer'} levert op", euro(own) if own is not None else "—",
         ("zelf ingesteld (eigen_verkoopprijs_eur)" if d.config["baseline"].get("eigen_verkoopprijs_eur") is not None
          else "verwachte verkoopprijs") if own is not None else "te weinig vergelijkbare advertenties"),
        ("Goedkoopste, netto", euro(min(nets)) if nets else "—",
         "prijs min wat je eigen computer oplevert (negatief: je houdt geld over)"),
    ])


def upgrades_panel(d: Dashboard) -> str:
    base = pc.baseline_model(config=d.config)
    ups = d.upgrades
    base_label = base.label if base else "eigen computer"
    parts = [upgrades_tiles(d)]
    parts.append(
        "<p class='explain'><strong>+punten</strong> = functiescore min die van je eigen computer "
        f"({pg.esc(base_label)}). Rerouting, plannen op het apparaat en training wegen het zwaarst, knoppen "
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
        changes = "".join(f"<li class='plus'>{pg.esc(g)}</li>" for g in gains)
        changes += "".join(f"<li class='minus'>{pg.esc(x)}</li>" for x in losses)
        unknown = f"<div class='sub'>{len(c.features.unknown)} velden onbekend</div>" if c.features.unknown else ""
        rows.append(
            "<tr>"
            f"<td class='pic'>{pg.thumb(l)}</td>"
            f"<td class='num' data-sort='{c.upgrade_delta}'><strong>+{c.upgrade_delta:.0f}</strong>"
            f"<div class='sub'>score {c.features.score:.0f}</div>{unknown}</td>"
            f"{price_cell(l)}"
            f"<td class='num' data-sort='{c.net_upgrade_cost_eur if c.net_upgrade_cost_eur is not None else ''}'>"
            f"{euro(c.net_upgrade_cost_eur)}</td>"
            f"<td><ul class='changes'>{changes or '<li>zelfde functies, beter bekend</li>'}</ul></td>"
            f"{listing_cell(l, d, c.model.label, c.reason)}"
            "</tr>"
        )
    parts.append(pg.table([("", ""), ("+punten", "num"), ("Prijs", "num"), ("Netto", "num"),
                        ("Wat je erbij krijgt / inlevert", ""), ("Advertentie", "text")], rows))
    return "\n".join(parts)


def search_text(listing, d: Dashboard, label: str) -> str:
    """Waarin het zoekvak van Alle computers zoekt: model, titel en je eigen
    notitie ("120" vindt de advertentie waar je een bod van 120 noteerde)."""
    note = d.notes.get(listing.item_id, "")
    return " ".join(x for x in (label, listing.title, note) if x).lower()


def mark_state(listing, d: Dashboard) -> str:
    """Voor het filter Toon in Alle computers."""
    if d.is_favorite(listing):
        return mr.FAVORITE
    return mr.DISMISSED if d.is_dismissed(listing) else ""


def view_counts(d: Dashboard) -> tuple[int, int]:
    """(te beoordelen, weggezet) in Alle, voor de tabknoppen en Toon."""
    items = d.all_rows
    return sum(1 for l, _, _ in items if d.to_review(l)), sum(1 for l, _, _ in items if d.is_dismissed(l))


# Tabknoppen die Alle openen met een filter (Toon): dezelfde weergaven als op
# /racefietsen, zonder een tweede tabel van duizenden rijen in de pagina.
def view_tab_labels(d: Dashboard) -> dict:
    review, away = view_counts(d)
    return {"beoordelen": f"Te beoordelen ({review})", "weggezet": f"Weggezet ({away})"}


def mark_options(d: Dashboard) -> str:
    """De keuzes van Toon in Alle computers, met hun aantallen."""
    items = d.all_rows
    review, away = view_counts(d)
    notes = sum(1 for l, _, _ in items if l.item_id in d.notes)
    return ("<option value=''>Toon: zonder weggezette</option>"
            f"<option value='beoordelen'>Toon: te beoordelen ({review})</option>"
            f"<option value='{mr.FAVORITE}'>Toon: favorieten ({len(d.favorites)})</option>"
            f"<option value='{mr.DISMISSED}'>Toon: weggezet ({away})</option>"
            f"<option value='notitie'>Toon: met notitie ({notes})</option>"
            "<option value='alles'>Toon: alles</option>")


def all_panel(d: Dashboard) -> str:
    scored = d.market.has_score
    items = d.all_rows
    brands = sorted({label.split(" ")[0] for _, label, c in items if c is not None})
    options = "".join(f"<option value='{pg.esc(b)}'>{pg.esc(b)}</option>" for b in brands)
    parts = [
        "<div class='filters'>"
        "<input type='search' id='all-search' placeholder='Zoek in titel of model' aria-label='Zoeken'>"
        f"<select id='all-brand' aria-label='Merk'><option value=''>Alle merken</option>{options}"
        "<option value='model onbekend'>Model onbekend</option></select>"
        f"<select id='all-mark' aria-label='Toon'>{mark_options(d)}</select>"
        "<label>Max €<input type='number' id='all-pmax' min='0' step='5' aria-label='Maximale prijs'></label>"
        "<label><input type='checkbox' id='all-new'> alleen nieuw</label>"
        "<span class='muted' id='all-count'></span></div>"
    ]
    rows = []
    reasons = d.unknown_reasons()
    for l, label, c in sorted(items, key=lambda i: (i[1] == "model onbekend", i[1], i[0].price_eur or 0)):
        brand = label.split(" ")[0] if c is not None else "model onbekend"
        profit = c.profit_eur if c else None
        delta = c.upgrade_delta if c else None
        score = c.features.score if c else None
        note = c.reason if c else reasons[id(l)]
        rows.append(
            f"<tr data-item='{pg.esc(l.item_id, quote=True)}' "
            f"data-brand='{pg.esc(brand, quote=True)}' data-new='{int(l.item_id in d.new_ids)}' "
            f"data-mark='{mark_state(l, d)}' data-note='{int(l.item_id in d.notes)}' "
            f"data-review='{int(d.to_review(l))}' data-price='{'' if l.price_eur is None else l.price_eur}' "
            f"data-text='{pg.esc(search_text(l, d, label), quote=True)}'>"
            f"<td class='pic'>{pg.thumb(l)}</td>"
            f"{price_cell(l)}"
            f"<td class='num' data-sort='{profit if profit is not None else ''}'>{euro(profit, sign=True)}</td>"
            + (f"<td class='num' data-sort='{delta if delta is not None else ''}'>"
               f"{'—' if delta is None else f'{delta:+.0f}'}</td>"
               f"<td class='num' data-sort='{score if score is not None else ''}'>{'—' if score is None else f'{score:.0f}'}</td>"
               if scored else "")
            + f"{km_cell(l, d)}{listing_cell(l, d, label, note)}"
            "</tr>"
        )
    head = [("", ""), ("Prijs", "num"), ("Winst", "num")]
    if scored:
        head += [("Upgrade", "num"), ("Score", "num")]
    parts.append(pg.table(head + [("Afstand", "num"), ("Advertentie", "text")], rows, "all-table"))
    return "\n".join(parts)


def favorites_panel(d: Dashboard) -> str:
    favs = d.favorites
    how = ("Klik bij een advertentie op <em>☆ favoriet</em> om hem hier te bewaren, of zet hem weg met "
           "<em>niet waard</em> of <em>gereserveerd</em>: dan verdwijnt hij uit Flips"
           + (" en Upgrades" if d.market.has_upgrades else "")
           + " tot de prijs zakt. Bij elke advertentie kun je een <em>notitie</em> kwijt (wat de verkoper "
           f"zei, wat je bood); het zoekvak in Alle {pg.esc(d.market.items)} zoekt er ook in, en "
           "<em>Toon: met notitie</em> laat ze allemaal zien.")
    if not d.editable:
        how = ("Bewaren en wegzetten doe je in de live versie: <code>python dashboard.py --serve</code>. " + how)
    parts = [f"<p class='explain'>{how} Een markering is alleen voor jou: een weggezette advertentie telt "
             "gewoon mee als vergelijkingsprijs.</p>"]
    if favs:
        rows = []
        reasons = d.unknown_reasons()
        for l, label, c in favs:
            mark = d.marks[l.item_id]
            then = (f"bij bewaren {euro(mark.price_eur)}"
                    if mark.price_eur is not None and mark.price_eur != l.price_eur else "")
            note = c.reason if c else reasons[id(l)]
            profit = c.profit_eur if c else None
            rows.append(
                "<tr>"
                f"<td class='pic'>{pg.thumb(l)}</td>"
                f"{price_cell(l, then)}"
                f"<td class='num' data-sort='{profit if profit is not None else ''}'>{euro(profit, sign=True)}</td>"
                f"{listing_cell(l, d, label, note)}"
                "</tr>"
            )
        parts.append(pg.table([("", ""), ("Prijs", "num"), ("Winst", "num"), ("Advertentie", "text")], rows))
    else:
        parts.append("<p class='empty'>Nog geen favorieten.</p>")

    gone = d.gone_favorites
    if gone:
        parts.append(f"<h3>Niet meer online ({len(gone)})</h3><p class='explain'>Verdwenen of al een paar "
                     "dagen niet meer gezien. Verdwenen is niet per se verkocht: een advertentie kan ook "
                     "ingetrokken zijn.</p>")
        rows = []
        for m in gone:
            link = (f"<a href='{pg.esc(m.url, quote=True)}' target='_blank' rel='noopener'>{pg.esc(m.title or m.item_id)}</a>"
                    if m.url else pg.esc(m.title or m.item_id))
            when = (f"verdwenen {pg.nl_date(m.disappeared_at)}" if m.disappeared_at
                    else f"laatst gezien {pg.nl_date(m.last_seen)}")
            remove = (pg.act("/markeer", m.item_id,
                          "<button class='quiet' name='soort' value='geen'>weghalen</button>", "mark")
                      if d.editable else "")
            rows.append(
                "<tr>"
                f"<td class='num' data-sort='{m.current_price_eur if m.current_price_eur is not None else ''}'>"
                f"{euro(m.current_price_eur)}</td>"
                f"<td class='what'>{link}<div class='note'>{pg.esc(when)}</div>{remove}{note_control(m.item_id, d)}</td>"
                "</tr>"
            )
        parts.append(pg.table([("Laatste prijs", "num"), ("Advertentie", "text")], rows))
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
    fast_models = model_fast(d)
    rows = []
    for label, items in sorted(by_model.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        model = items[0].computer.model
        # Geen €0: dat is "gratis" of een ruilaanbod (computers.listed_price()).
        asking = [pc.listed_price(l) for l in items if l.price_is_asking and pc.listed_price(l) is not None]
        median = statistics.median(asking) if asking else None
        resale = per_model.get(label, items[0].computer.resale_eur)
        new_price = model.number("nieuwprijs_eur")
        variants = variant_summary(items)
        fast = fast_models.get(label, [])
        fast_median = statistics.median(fast) if fast else None
        rows.append(
            "<tr>"
            f"<td class='what'><div class='model'>{pg.esc(label)}</div>"
            f"<span class='muted'>{pg.esc(model.get('introductiejaar') or '')}</span>"
            + (f"<div class='sub'>{pg.esc(variants)}</div>" if variants else "")
            + "</td>"
            f"<td class='num' data-sort='{len(items)}'>{len(items)}</td>"
            f"<td class='num' data-sort='{min(asking) if asking else ''}'>{euro(min(asking) if asking else None)}</td>"
            f"<td class='num' data-sort='{median if median is not None else ''}'>{euro(median)}</td>"
            f"<td class='num' data-sort='{len(fast)}'>{len(fast) or ''}"
            + (f"<div class='sub'>mediaan {euro(fast_median)}</div>" if fast else "") + "</td>"
            f"<td class='num' data-sort='{resale if resale is not None else ''}'>"
            f"{euro(resale) if resale is not None else euro(median * factor) if median else '—'}</td>"
            f"<td class='num' data-sort='{new_price if new_price else ''}'>{euro(new_price)}</td>"
            + (f"<td class='num' data-sort='{items[0].computer.features.score}'>{items[0].computer.features.score:.0f}</td>"
               if scored else "")
            + "</tr>"
        )
    intro = ("<p class='explain'>Per model wat er nu te koop staat. <strong>Snel verkocht</strong>: binnen "
             f"{pc.FAST_DAYS} dagen weg, of gereserveerd en daarna weg, met de mediaan van hun laatste vraagprijs. "
             f"<strong>Verwacht verkoop</strong> is die mediaan als het er minstens {pc.MIN_FAST} zijn (wat er "
             "echt betaald is weet je niet, maar dichterbij kom je niet), anders de "
             f"mediaan-vraagprijs × {str(factor).replace('.', ',')}, over alle advertenties van de laatste "
             f"{d.config['flip']['comp_window_days']} dagen (ook verkochte); een flip rekent per uitvoering als "
             "die er genoeg heeft. Onder het model staan de uitvoeringen die nu te koop staan, met hun "
             "mediaan-vraagprijs. Nieuwprijs alleen waar een bron "
             f"hem gaf (<code>{pg.esc(d.market.catalog_path.name)}</code>).</p>")
    head = [("Model", "text"), ("Te koop", "num"), ("Laagste", "num"), ("Mediaan vraag", "num"),
            ("Snel verkocht", "num"), ("Verwacht verkoop", "num"), ("Nieuwprijs", "num")]
    return intro + pg.table(head + ([("Score", "num")] if scored else []), rows)


def _vinted_thumb(item: vn.VintedItem) -> str:
    if not item.row.image_url:
        return "<div class='thumb empty' aria-hidden='true'></div>"
    return (f"<a href='{pg.esc(pg.web_link(item.row.url), quote=True)}' target='_blank' rel='noopener'>"
            f"<img class='thumb' src='{pg.esc(pg.web_link(item.row.image_url), quote=True)}' alt='' loading='lazy'></a>")


def _vinted_cell(item: vn.VintedItem, label: str) -> str:
    new = "<span class='badge'>nieuw</span> " if item.is_new else ""
    extra = [item.row.condition, f"{item.row.favorites} fav." if item.row.favorites is not None else "",
             "zakelijke verkoper" if item.row.is_business else ""]
    muted = " · ".join(x for x in extra if x)
    return (f"<td class='what'><div class='model'>{new}{pg.esc(label)}</div>"
            f"<a href='{pg.esc(pg.web_link(item.row.url), quote=True)}' target='_blank' rel='noopener'>{pg.esc(item.row.title)}</a>"
            f"{f'<span class=muted> · {pg.esc(muted)}</span>' if muted else ''}</td>")


def _ratio(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.2f}".replace(".", ",")


def vinted_panel(d: Dashboard) -> str:
    v = d.vinted
    if v is None:
        # Altijd een tab, ook zonder export: zo is te zien dat de import in een
        # andere database belandde dan deze, in plaats van dat de tab ontbreekt.
        return ("<p class='empty'>Nog geen Vinted-export in deze database "
                f"(<code>{pg.esc(d.db_path)}</code>). Lees er een in met "
                "<code>python vinted.py import productsList_....csv</code> en ververs deze pagina.</p>")
    flip = d.config["flip"]
    flips = v.flips
    parts = [pg.tiles([
        ("Op Vinted", str(len(v.computers)), f"computers met bekend model, export {local_time(v.newest_export)}"),
        ("Vinted ÷ Marktplaats", _ratio(v.median_ratio), "mediaan over de modellen met genoeg vergelijking"),
        ("Koop op Vinted", str(len(flips)), "onder de Marktplaats-verkoopprijs"),
        ("Beste", euro(flips[0].profit_eur, sign=True) if flips else "—",
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
            f"<span class='gain' aria-hidden='true'>▲</span>{euro(i.profit_eur, sign=True)}</td>"
            f"<td class='num' data-sort='{i.cost_eur}'>{euro(i.cost_eur)}"
            f"<div class='sub'>vraagt {euro(i.row.price_eur)}</div></td>"
            f"<td class='num' data-sort='{i.resale_eur}'>{euro(i.resale_eur)}"
            f"<div class='sub'>n={i.mp_count} op Marktplaats</div></td>"
            f"{_vinted_cell(i, i.model.label)}"
            "</tr>"
            for i in flips
        ]
        parts.append("<h3>Koop op Vinted, verkoop op Marktplaats</h3>")
        parts.append(pg.table([("", ""), ("Winst", "num"), ("Je betaalt", "num"), ("Verkoop MP", "num"),
                            ("Advertentie", "text")], rows))
    else:
        parts.append("<p class='empty'>Geen Vinted-advertentie onder de Marktplaats-verkoopprijs.</p>")

    rows = []
    for m in v.models:
        ratio = m.ratio
        rows.append(
            "<tr>"
            f"<td class='what'><div class='model'>{pg.esc(m.model.label)}</div></td>"
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
    parts.append(pg.table([("Model", "text"), ("Vinted", "num"), ("Laagste", "num"), ("Mediaan", "num"),
                        ("MP", "num"), ("Mediaan MP", "num"), ("Verkoop MP", "num"), ("Vinted ÷ MP", "num")], rows))
    counts: dict[str, int] = {}
    for i in v.excluded:
        counts[i.kind] = counts.get(i.kind, 0) + 1
    if counts or v.unknown:
        summary = ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        parts.append(f"<p class='explain'>Niet meegeteld: {len(v.unknown)} zonder bekend model"
                     f"{', ' + pg.esc(summary) if summary else ''} (horloges, trainers, kleding, houders en fietsen "
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
            f"<p class='explain'>Wat níet als {pg.esc(d.market.item)} meetelt, met de reden — om na te kijken dat er "
            f"geen echt {pg.esc(d.market.item)} tussen zit. Bandjes, laders en hoesjes herkent het filter aan hun "
            "plek in de titel: <em>vóór</em> de modelnaam (\"Bandje voor Garmin Fenix 6\") is een accessoire, "
            "<em>erna met</em> \"met\"/\"incl.\"/\"+\" (\"Fenix 6 met siliconen polsband\") een horloge met "
            "extra's. Staat het woord er direct achter (\"Fenix 6 Pro bandje\"), dan beslist de prijs t.o.v. "
            "hetzelfde model. Andere merken en Garmin-producten die geen horloge zijn (weegschaal, "
            f"hartslagband, navigatie) staan hier als <em>overig</em>. Nu: {pg.esc(summary) or 'niets'}.</p>"
        ]
    else:
        parts = [
        "<p class='explain'>Wat níet als computer meetelt, met de reden — om na te kijken dat er geen "
        "echte computer tussen zit. Houders en hoesjes herkent het filter aan hun plek in de titel: "
        "<em>vóór</em> de modelnaam (\"Hoesje voor Garmin 1000\") is een accessoire, <em>erna met</em> "
        "\"met\"/\"incl.\"/\"+\" (\"Edge 530 + stuurmount\") een computer met extra's. Staat het "
        "woord er direct achter (\"Karoo 3 houder nieuw\"), dan beslist de prijs t.o.v. hetzelfde model. "
        f"Nu: {pg.esc(summary) or 'niets'}.</p>"
        ]
    rows = [
        "<tr>"
        f"<td class='pic'>{pg.thumb(l)}</td>"
        f"<td>{pg.esc(kind)}</td>"
        f"<td class='num' data-sort='{l.price_eur if l.price_eur is not None else ''}'>{euro(l.price_eur)}</td>"
        f"<td class='what'><a href='{pg.esc(l.url, quote=True)}' target='_blank' rel='noopener'>{pg.esc(l.title)}</a>"
        f"<div class='note'>{pg.esc(reason)}</div></td>"
        "</tr>"
        for l, kind, reason in rows_data
    ]
    parts.append(pg.table([("", ""), ("Soort", "text"), ("Prijs", "num"), ("Advertentie en reden", "text")], rows))
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
        label = f"{pg.MONTHS[int(mon) - 1]} '{year[2:]}"
        parts.append(
            f"<g><title>{pg.esc(label)}: {pg.esc(euro(value, sign=True))}</title>"
            f"<rect x='{x:.1f}' y='{y:.1f}' width='{bar:.1f}' height='{max(h, 1):.1f}' rx='3' class='bar'/>"
            f"<text x='{x + bar / 2:.1f}' y='{(y - 6) if value >= 0 else (y + h + 14):.1f}' "
            f"class='val'>{pg.esc(euro(value, sign=True))}</text>"
            f"<text x='{x + bar / 2:.1f}' y='{height - 8}' class='lab'>{pg.esc(label)}</text></g>"
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
    parts = [pg.tiles([
        ("Gerealiseerde winst", euro(p.realized_profit_eur, sign=True) if p.sold else "—",
         f"{len(p.sold)} verkocht, samen {euro(p.revenue_eur)} omzet" if p.sold else "nog niets verkocht"),
        ("Op voorraad", str(len(p.stock)), f"{euro(p.invested_in_stock_eur)} erin gestoken" if p.stock else "niets"),
        ("Verwachte winst voorraad", euro(p.expected_stock_profit_eur, sign=True),
         f"na {euro(shipping)} verzendkosten per stuk"),
        ("Gemiddeld verkocht na", f"{p.avg_days_to_sell:.0f} dagen" if p.avg_days_to_sell is not None else "—",
         error or "hoe goed de schatting klopte, verschijnt na je eerste verkopen"),
    ])]
    if d.editable:
        parts.append("<p class='explain'>Alle flips samen, met fietsen, klussenlijsten, investeringen en een "
                     f"Google Sheet: <a href='{pg.FLIPS_PATH}'>Flips</a>.</p>")
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
            link = (f"<a href='{pg.esc(pg.web_link(t.url), quote=True)}' target='_blank' rel='noopener'>{pg.esc(t.title)}</a>"
                    if pg.web_link(t.url) else pg.esc(t.title))
            rows.append(
                "<tr>"
                f"<td class='what'><div class='model'>{pg.esc(t.model or 'model onbekend')}</div>{link}"
                f"{'<div class=note>' + pg.esc(t.notes) + '</div>' if t.notes else ''}{sell}</td>"
                f"<td data-sort='{t.bought_at}'>{pg.esc(pg.nl_date(t.bought_at))}"
                f"<div class='sub'>{t.days_held()} dagen</div></td>"
                f"<td class='num' data-sort='{t.cost_basis_eur}'>{euro(t.cost_basis_eur)}</td>"
                f"<td class='num' data-sort='{s.expected_resale_eur or ''}'>{euro(s.expected_resale_eur)}</td>"
                f"<td class='num' data-sort='{s.expected_profit_eur if s.expected_profit_eur is not None else ''}'>"
                f"{euro(s.expected_profit_eur, sign=True)}</td>"
                "</tr>"
            )
        parts.append(pg.table([("Wat", "text"), ("Gekocht", "text"), ("Inkoop", "num"), ("Verwacht verkoop", "num"),
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
            link = (f"<a href='{pg.esc(pg.web_link(t.url), quote=True)}' target='_blank' rel='noopener'>{pg.esc(t.title)}</a>"
                    if pg.web_link(t.url) else pg.esc(t.title))
            vs = ""
            if t.expected_resale_eur:
                vs = f"<div class='sub'>verwacht {euro(t.expected_resale_eur)}</div>"
            rows.append(
                "<tr>"
                f"<td class='what'><div class='model'>{pg.esc(t.model or 'model onbekend')}</div>{link}{actions}</td>"
                f"<td data-sort='{t.sold_at}'>{pg.esc(pg.nl_date(t.sold_at))}"
                f"<div class='sub'>{t.days_held()} dagen · {pg.esc(t.sold_via or '')}</div></td>"
                f"<td class='num' data-sort='{t.cost_basis_eur}'>{euro(t.cost_basis_eur)}</td>"
                f"<td class='num' data-sort='{t.sell_price_eur}'>{euro(t.sell_price_eur)}"
                f"<div class='sub'>−{euro(t.sell_costs_eur or 0)} kosten</div>{vs}</td>"
                f"<td class='num profit' data-sort='{t.profit_eur}'>{euro(t.profit_eur, sign=True)}</td>"
                "</tr>"
            )
        parts.append(pg.table([("Wat", "text"), ("Verkocht", "text"), ("Inkoop", "num"), ("Verkoopprijs", "num"),
                            ("Winst", "num")], rows))

    if d.editable:
        labels = [m.label for m in d.market.catalog()]
        options = "".join(f"<option>{pg.esc(l)}</option>" for l in labels)
        parts.append(
            "<h3>Zelf toevoegen</h3><p class='explain'>Voor wat je niet via een advertentie hierboven kocht, "
            "zoals een aankoop op Vinted.</p>"
            "<form class='addform' method='post' action='/toevoegen'>"
            f"{hidden(d)}"
            f"<label>Wat<input name='titel' required placeholder='{pg.esc(d.market.example_title, quote=True)}'></label>"
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
    parts = [pg.tiles([
        ("Gegevens", f"{p.days_of_data} dagen", f"sinds {pg.nl_date(p.since.date().isoformat())}" if p.since else "nog niets"),
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
            f"<td class='what'><div class='model'>{pg.esc(m.model)}</div></td>"
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
    parts.append(pg.table([("Model", "text"), ("Gezien", "num"), ("Verdwenen", "num"), ("Dagen online", "num"),
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
            rows.append(f"<tr><td class='what'><div class='model'>{pg.esc(model)}</div></td>{cells}</tr>")
        heads = [("Model", "text")] + [(f"{pg.MONTHS[int(m[5:]) - 1]} '{m[2:4]}", "") for m in p.months]
        parts.append(pg.table(heads, rows))

    if p.weekday_new:
        top = max(v for _, v, _ in p.weekday_new) or 1
        rows = "".join(
            f"<tr><td>{pg.esc(day)}</td><td class='num'>{avg:.1f}".replace(".", ",") + "</td>"
            f"<td><div class='meter' style='width:{avg / top * 100:.0f}%'></div></td>"
            f"<td class='num sub'>{n} dagen</td></tr>"
            for day, avg, n in p.weekday_new)
        parts.append("<h3>Nieuwe advertenties per weekdag</h3><p class='explain'>Gemiddeld per dag, gemeten aan de "
                     "rondes (de eerste ronde telt niet mee). Het uur van plaatsen staat niet in de zoekresultaten; "
                     "voor de gemeten advertenties wel (hieronder, Tijd van plaatsen).</p>"
                     f"<div class='table-wrap'><table><tbody>{rows}</tbody></table></div>")
    parts.append(vw.patterns_html(d.view_patterns or vw.ViewPatterns(), d.market.items))
    return "\n".join(parts)


def bids_label(d: Dashboard) -> str:
    active = sum(1 for t in d.bid_trails() if t.active)
    return f"Mijn biedingen ({active})" if active else "Mijn biedingen"


def tab_list(d: Dashboard) -> list:
    """(naam, label, paneel) per tab; het paneel is een functie, zodat een
    klik in de live versie alleen de tabs opnieuw opbouwt die hij raakt."""
    m = d.market
    computers = len(d.items) + len(d.unknown_items)
    p = d.progress
    mine_label = f"Mijn flips ({euro(p.realized_profit_eur, sign=True)})" if p and p.sold else "Mijn flips"
    tabs = [("flips", f"Flips ({len(d.flips)})", flips_panel)]
    if m.has_upgrades:
        tabs.append(("upgrades", f"Upgrades ({len(d.upgrades)})", upgrades_panel))
    tabs += [
        ("favorieten", f"Favorieten ({len(d.favorites)})", favorites_panel),
        ("biedingen", bids_label(d), bids_panel),
        ("mijn", mine_label, mine_panel),
        ("alle", f"Alle {m.items} ({computers})", all_panel),
        ("markt", "Marktprijzen", market_panel),
    ]
    if m.has_vinted:
        tabs.append(("vinted", f"Vinted ({len(d.vinted.flips)})" if d.vinted else "Vinted", vinted_panel))
    tabs += [
        ("patronen", "Patronen", patterns_panel),
        ("uitgefilterd", f"Uitgefilterd ({len(d.excluded)})", excluded_panel),
    ]
    return tabs


def distance_bar(d: Dashboard) -> str:
    """Het schuifje "max. afstand" en (live) de postcode waar het vanaf meet."""
    if d.home:
        slider = ("<label>Afstand <input type='range' id='km-max' min='5' max='250' step='5' value='250'> "
                  "<output id='km-out'></output></label>"
                  "<label><input type='checkbox' id='km-none' checked> ook zonder plek</label>")
        where = f"hemelsbreed vanaf {pg.esc(d.home.postcode)}"
    else:
        slider, where = "", "vul je postcode in om op afstand te filteren en te sorteren (kolom Afstand)"
    form = (pg.act("/afstand", "postcode",
                f"<input name='postcode' size='7' value='{pg.esc(d.home.postcode if d.home else '', quote=True)}' "
                "placeholder='bv. 3511AB' aria-label='Postcode'><button class='quiet'>opslaan</button>")
            if d.editable else "")
    if not slider and not form:
        return ""
    return f"<div class='filters'>{slider}<span class='muted'>{where}</span>{form}</div>"


# Tabs die de live pagina pas ophaalt als je ze opent (PANEL_PATH, JS
# loadPanel()). Alle computers is met ~2000 rijen, elk met eigen knoppen,
# ruim de helft van de pagina: 5 van de 9 MB en 90.000 van de 145.000
# elementen bij een proefdatabase van twee maanden rondes. De browser las en
# bouwde hem bij elke keer laden en bij elke klik liep het bijwerken er
# doorheen, ook als je alleen Flips bekeek. De eerste tab nooit, en het
# geschreven dashboard.html heeft alles: dat heeft geen server om te vragen.
LAZY_PANELS = ("alle",)
PANEL_PATH = "/paneel"


def render(d: Dashboard, overview_link: Optional[str] = None, lazy: Sequence[str] = ()) -> str:
    """De hele pagina. `lazy`: tabs die leeg blijven (alleen live, zie
    LAZY_PANELS)."""
    m = d.market
    computers = len(d.items) + len(d.unknown_items)
    tabs = [(name, label, None if i and name in lazy else panel(d))
            for i, (name, label, panel) in enumerate(tab_list(d))]
    view_labels = view_tab_labels(d)
    nav = ""
    for i, (name, label, _) in enumerate(tabs):
        if name == "favorieten":
            nav += (f"<button data-panel='alle' data-tab='beoordelen' data-mark='beoordelen'>"
                    f"{pg.esc(view_labels['beoordelen'])}</button>")
        nav += f"<button data-panel='{name}'{' class=active' if i == 0 else ''}>{pg.esc(label)}</button>"
        if name == "alle":
            nav += (f"<button data-panel='alle' data-tab='weggezet' data-mark='{mr.DISMISSED}'>"
                    f"{pg.esc(view_labels['weggezet'])}</button>")
    panels = "".join(
        f"<section class='panel' id='panel-{name}'{'' if i == 0 else ' hidden'}"
        f"{' data-lazy=1' if body is None else ''}>{body or ''}</section>"
        for i, (name, _, body) in enumerate(tabs)
    )
    notices = ""
    if d.message:
        notices += f"<div class='banner' role='status'>{pg.esc(d.message)}</div>"
    if not d.listings:
        notices += (f"<div class='banner'>Nog geen {pg.esc(m.short.lower())} in de database. Draai eerst een ronde: "
                    "<code>python koopjes.py run nacht</code>.</div>")
    link = f" · <a href='{pg.esc(overview_link, quote=True)}'>racefietsen: overzicht</a>" if overview_link else ""
    link += "".join(f" · <a href='{pg.esc(href, quote=True)}'>{pg.esc(label)}</a>" for label, href in d.other_links)
    new = f" ({len(d.new_ids)} nieuw)" if d.new_ids else ""
    live = " · <strong>live</strong> (wijzigingen gaan in koopjes.db)" if d.editable else ""
    meta = (f"Bijgewerkt {datetime.now().strftime('%d-%m-%Y %H:%M')} · {computers} {m.items} te koop{new} "
            f"· laatste ronde {local_time(d.newest_seen)}{link}{live}")
    notices += distance_bar(d)
    return (
        "<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{pg.esc(m.short)}</title><style>{pg.CSS}{pg.SITE_CSS if d.editable else ''}</style></head><body>"
        f"<main data-token='{pg.esc(d.token, quote=True)}' data-markt='{pg.esc(m.key, quote=True)}'>"
        f"{pg.site_nav(m.serve_path) if d.editable else ''}<h1>{pg.esc(m.title)}</h1>"
        f"<div class='meta'>{meta}</div>{notices}"
        f"<nav class='tabs'>{nav}</nav>{panels}"
        f"</main><div id='toast' role='status' hidden></div><script>{pg.LIVE_JS}{pg.JS}</script></body></html>"
    )


def live_update(d: Dashboard, item_id: str, message: str, choice: Optional[str] = None,
                bids_changed: bool = False) -> dict:
    """Wat de live pagina na een klik op favoriet/weg (`choice`: de knop) of
    een notitie (`choice` None) nodig heeft om bij te werken zonder te
    herladen: de badges en knoppen van die advertentie, overal waar hij
    staat; of hij nog in Flips/Upgrades hoort (anders verbergt de pagina
    die rij); zijn filterwaarden in Alle computers; de tegels en
    tablabels; en Favorieten opnieuw opgebouwd (een handvol rijen).

    Flips en Upgrades zelf alleen bij terugzetten: dan hoort er een rij bij
    die er bij het laden niet stond. Die tabs zijn met een paar honderd
    flips samen een megabyte, en de browser deed er een seconde over om ze
    te vervangen."""
    out: dict = {"message": message, "panels": {}, "tabs": {}, "markOptions": mark_options(d),
                 "tiles": {"flips": flips_tiles(d)}, "away": flips_away(d)}
    if d.market.has_upgrades:
        out["tiles"]["upgrades"] = upgrades_tiles(d)
    row = next(((l, label) for l, label, _ in d.all_rows if l.item_id == item_id), None)
    wanted = {"favorieten"}
    if bids_changed:
        # Geaccepteerd maakt een eigen aankoop: Mijn flips (een handvol rijen) mee.
        wanted |= {"biedingen", "mijn"}
    if row is None and item_id in d.bids:
        # Een bod op een advertentie die niet meer online is (alleen in Mijn biedingen).
        out["item"] = {"id": item_id, "badge": "", "mine": bid_control(item_id, d), "mark": "", "note": 0,
                       "text": "", "available": False, "review": 0}
    if row is not None:
        listing, label = row
        out["item"] = {"id": item_id, "badge": mark_badges(listing, d), "mine": own_controls(listing, d),
                       "mark": mark_state(listing, d), "note": int(item_id in d.notes),
                       "text": search_text(listing, d, label), "available": d._available(listing),
                       "review": int(d.to_review(listing))}
        if choice == "geen" and d._available(listing):
            if any(l is listing for l in d.flips) or any(l is listing for l in d.open_bids):
                wanted.add("flips")
            if any(l is listing for l in d.upgrades):
                wanted.add("upgrades")
    out["tabs"].update(view_tab_labels(d))
    for name, label, panel in tab_list(d):
        if name in ("flips", "upgrades", "favorieten", "biedingen", "mijn"):
            out["tabs"][name] = label
        if name in wanted:
            out["panels"][name] = panel(d)
    return out


def write_dashboard(db_path, out_path, overview_link: Optional[str] = None,
                    market: mk.Market = mk.COMPUTERS, other_links: Sequence = ()) -> Dashboard:
    """`other_links`: (label, href) naar de dashboards van de andere markten."""
    d = load_dashboard(db_path, market=market)
    d.other_links = list(other_links)
    Path(out_path).write_text(render(d, overview_link), encoding="utf-8")
    return d


# --- Live: --serve --------------------------------------------------------------


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
        import server  # hier: server.py bouwt op dit bestand

        return server.serve(args.db, args.port, not args.no_browser)
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
