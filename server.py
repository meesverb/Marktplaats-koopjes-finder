"""De live server van `python dashboard.py --serve`: één adres (127.0.0.1)
voor alle pagina's, met het token tegen andere sites, de routes
(DashboardHandler), de acties achter de knoppen (ACTIONS: gekocht,
markeren, notitie, controleer, bieden, postcode, Mijn flips) en de cache
die het zware rekenwerk onthoudt tot een ronde de database verandert
(LiveCache, keep_warm).

De pagina's zelf staan in dashboard.py (de markten), racebikes.py,
bike_page.py, flips_page.py, start_page.py en upgrade_test.py.
"""
from __future__ import annotations

import hmac
import json
import secrets
import sqlite3
import sys
import threading
import webbrowser
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote, unquote, urlsplit

import bike_comps as bc
import bike_page as bp
import computers as pc
import dashboard as dash
import db
import distance as dm
import dossier as ds
import flips as fl
import flips_page as fp
import flips_sheets as fs
import launcher
import markets as mk
import marks as mr
import own_bids as ob
import pages as pg
import racebikes as rb
import recheck as rc
import report
import spares as sp
import start_page as st
import upgrade as up
import upgrade_test as ut
from util import euro
import valuation as val


def data_stamp(db_path, trades: bool = True) -> Optional[tuple]:
    """Wat verandert zodra een ronde, de knop controleer, een eigen aan- of
    verkoop of een Vinted-import de database raakt; een markering, notitie
    of keuze op /fiets niet. Elke ronde zet last_seen op het moment van de
    ronde, de verdwijn-sweep telt in disappeared_at, controleer zet
    checked_at. None: niet vast te stellen (dan onthoudt de server niets)."""
    if not Path(db_path).exists():
        return None
    conn = db.connect_readonly(db_path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        parts = [tuple(conn.execute(
            "SELECT COUNT(*), MAX(last_seen), COUNT(disappeared_at), MAX(checked_at), "
            "MAX(bids_checked_at) FROM listing").fetchone())]
        # /racefietsen rekent niet met de eigen aankopen (die komen per klik
        # vers, racebikes.load_fresh()): een geaccepteerd bod hoeft daar niet
        # alles opnieuw te laten rekenen.
        if "trade" in tables and trades:
            parts.append(tuple(conn.execute(
                "SELECT COUNT(*), MAX(id), COUNT(sold_at), TOTAL(sell_price_eur) FROM trade").fetchone()))
        if "vinted_listing" in tables:
            parts.append(tuple(conn.execute(
                "SELECT COUNT(*), MAX(last_exported_at) FROM vinted_listing").fetchone()))
        # Een meting van weergaven en likes (views.py) verandert Patronen.
        if "listing_stats" in tables:
            parts.append(tuple(conn.execute("SELECT COUNT(*), MAX(observed_at) FROM listing_stats").fetchone()))
        return tuple(parts)
    except sqlite3.Error:
        return None  # een database van vóór migratie 14 (checked_at): gewoon elke keer opnieuw
    finally:
        conn.close()


class LiveCache:
    """Het zware deel van elk dashboard, per markt onthouden zolang
    data_stamp() en de instellingen hetzelfde blijven. Een klik op favoriet
    of weg bouwde de hele pagina opnieuw op: ruim een seconde rekenen voor
    ~2800 computers, en een pagina van megabytes die de browser opnieuw
    moest lezen. Nu rekent alleen de eerste keer na een ronde; de klik zelf
    stuurt een paar stukjes pagina terug (live_update)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._base: dict = {}
        self._comps: dict = {}
        # Eén opbouw tegelijk per pagina: een tweede verzoek (of warm())
        # wacht op de lopende in plaats van hem nog eens te doen.
        self._building: dict = {}

    def _build_lock(self, key) -> threading.Lock:
        with self._lock:
            return self._building.setdefault(key, threading.Lock())

    def comps(self, db_path) -> Optional[list]:
        """De vergelijkingskandidaten voor de taxatie op /fiets
        (valuation.fetch_comp_candidates): elke advertentie met een
        vraagprijs, dus duizenden. Een keuze meenemen/niet verandert ze
        niet, een ronde wel. None: geen database."""
        if not Path(db_path).exists():
            return None
        stamp = data_stamp(db_path)
        where = str(Path(db_path).resolve())
        # Rekenen onder de bouwsleutel, niet onder _lock: anders wachtte elk
        # ander verzoek (ook naar een dashboard) tot dit klaar was.
        with self._build_lock(("comps", where)):
            with self._lock:
                cached = self._comps.get(where)
            if cached is not None and stamp is not None and cached[0] == stamp:
                return cached[1]
            conn = bc.open_readonly(db_path)
            try:
                found = val.fetch_comp_candidates(conn)
            finally:
                conn.close()
            with self._lock:
                self._comps[where] = (stamp, found)
            return found

    def racebikes(self, db_path, intake_path) -> "rb.Base":
        """Het zware deel van /racefietsen (racebikes.build_base()): flip,
        waardescore en upgrade per fiets. Een markering of bod verandert het
        niet, een ronde of controleer wel. Een nieuwe regel op /upgrade
        rekent alleen het upgradeoordeel opnieuw (racebikes.rescore())."""
        stamp = data_stamp(db_path, trades=False)
        rule = up.rule_stamp(db_path)
        key = ("racefietsen", str(Path(db_path).resolve()), str(intake_path))
        with self._build_lock(key):
            with self._lock:
                cached = self._base.get(key)
            if cached is not None and stamp is not None and cached[0] == stamp:
                if cached[2] != rule:
                    rb.rescore(cached[1], db_path, intake_path, self.comps(db_path))
                    with self._lock:
                        self._base[key] = (stamp, cached[1], rule)
                return cached[1]
            comps = self.comps(db_path)
            base = rb.build_base(db_path, intake_path, comps)
            with self._lock:
                self._base[key] = (stamp, base, rule)
            return base

    def upgrade_bikes(self, db_path, intake_path) -> list:
        """De fietsen van /upgrade (upgrade_test.load_bikes()): de actieve
        van /racefietsen plus wat je beoordeelde en niet meer te koop is. Het
        lezen van de tekst (Prepared) onthouden zolang de database niet
        verandert; oordelen en bouwjaren komen altijd vers."""
        base = self.racebikes(db_path, intake_path)
        stamp = data_stamp(db_path, trades=False)
        where = ("upgrade", str(Path(db_path).resolve()))
        with self._lock:
            cached = self._base.get(where)
            if cached is None or cached[0] != stamp or stamp is None:
                cached = (stamp, {})
                self._base[where] = cached
        with base.lock:
            listings = [r.listing for r in base.rows]
        return ut.load_bikes(db_path, listings, prepared=cached[1])

    def dashboard(self, db_path, market: mk.Market) -> dash.Dashboard:
        config = pc.default_config()
        key = (data_stamp(db_path), json.dumps(config, sort_keys=True, default=str))
        where = (str(Path(db_path).resolve()), market.key)
        with self._build_lock(where):
            with self._lock:
                cached = self._base.get(where)
            if cached is not None and key[0] is not None and cached[0] == key:
                base = cached[1]
            else:
                base = dash.load_base(db_path, config, market)
                with self._lock:
                    self._base[where] = (key, base)
        # Markeringen, notities, biedingen, metingen en afstanden zijn goedkoop
        # en veranderen per klik: die altijd vers, op een kopie, zodat twee
        # verzoeken elkaar niet raken.
        return replace(base, **dash.fresh_parts(db_path))

    def warm(self, db_path, intake_path) -> None:
        """Alvast rekenen wat een paginabezoek anders laat wachten: de
        dashboards en /racefietsen (enkele seconden bij ~14.000 fietsen)."""
        for market in mk.MARKETS.values():
            self.dashboard(db_path, market)
        self.racebikes(db_path, intake_path)


# Hoe vaak de server kijkt of een ronde klaar is om alvast te rekenen.
WARM_EVERY_S = 60


def keep_warm(cache: LiveCache, db_path, intake_path, stop: threading.Event, every: float = WARM_EVERY_S) -> None:
    """Na het starten, en na elke ronde zodra de database een keer `every`
    seconden niet veranderde (tijdens een ronde verandert hij steeds):
    LiveCache.warm(), zodat de eerste klik na een ronde niet wacht. Leest
    alleen; een fout (bv. een database van een oudere versie) laat de
    pagina's gewoon zelf rekenen."""
    warmed, previous = None, None
    while not stop.is_set():
        stamp = data_stamp(db_path) if Path(db_path).exists() else None
        if stamp is not None and stamp != warmed and (warmed is None or stamp == previous):
            try:
                cache.warm(db_path, intake_path)
                warmed = stamp
            except Exception:  # noqa: BLE001 — alleen vooruitwerken; de pagina rekent anders zelf
                warmed = stamp
        previous = stamp
        stop.wait(every)


# Als een ander proces koopjes.db langer dan db.BUSY_TIMEOUT_S vasthoudt (een
# ronde die schrijft): liever dit op de pagina dan een traceback in de
# terminal en een knop die niets lijkt te doen (de eigenaar, 02-10-2026).
DB_BUSY = ("De database is even bezet (waarschijnlijk loopt er een ronde); er is niets opgeslagen. "
           "Probeer het over een minuut opnieuw.")


def db_busy(exc: Exception) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and ("locked" in str(exc) or "busy" in str(exc))


def action_bought(db_path, form: dict) -> str:
    item_id = form.get("item_id", "")
    price = pg.parse_euro(form.get("prijs"), "Inkoopprijs")
    market = mk.by_key(form.get("markt"))
    d = dash.load_dashboard(db_path, market=market)
    listing = next((l for l in d.listings if l.item_id == item_id), None)
    if listing is None:
        raise pg.FormError("Die advertentie staat niet (meer) in het dashboard; voeg hem zelf toe onder Mijn flips.")
    if item_id in d.bought:
        raise pg.FormError(f"'{listing.title}' staat al in Mijn flips.")
    c = listing.computer
    conn = db.connect(str(db_path))
    try:
        db.add_trade(conn, title=listing.title, bought_at=pg.parse_day(form.get("datum")), buy_price_eur=price,
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
            raise pg.FormError("Die advertentie had geen markering.")
        return "Markering weggehaald."
    if choice != mr.FAVORITE and choice not in mr.ALL_REASONS:
        raise pg.FormError(f"Onbekende keuze '{choice}'.")
    if form.get("markt") == rb.MARKET_KEY:
        # Een racefiets, of een los onderdeel uit de weergave Onderdelen (spares.py).
        listing = rb.find_listing(db_path, item_id) or sp.find_listing(db_path, item_id)
    else:
        market = mk.by_key(form.get("markt"))
        config = pc.default_config()
        listings, _, _ = dash.load_active_listings(db_path, market.categories, config["dashboard"])
        listing = next((l for l in listings if l.item_id == item_id), None)
    if listing is None:
        raise pg.FormError("Die advertentie staat niet (meer) in het dashboard.")
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


def action_note(db_path, form: dict) -> str:
    """Een notitie bij een advertentie die de crawl kent, ook een die niet
    meer online is (een verdwenen favoriet). Leeg wist hem."""
    item_id = form.get("item_id", "")
    # Eén regel: een Enter uit een geplakte chat wordt een spatie.
    note = " ".join((form.get("notitie") or "").split())
    if len(note) > mr.NOTE_MAX_CHARS:
        raise pg.FormError(f"De notitie is te lang ({len(note)} tekens, hooguit {mr.NOTE_MAX_CHARS}).")
    conn = db.connect(str(db_path))
    try:
        if note and conn.execute("SELECT 1 FROM listing WHERE item_id = ?", (item_id,)).fetchone() is None:
            raise pg.FormError("Onbekende advertentie.")
        db.set_note(conn, item_id, note)
    finally:
        conn.close()
    return "Notitie opgeslagen." if note else "Notitie gewist."


def action_check(db_path, form: dict) -> str:
    """Eén advertentie nu ophalen bij Marktplaats (recheck.py) en vastleggen
    wat erop staat. Na de klik bouwt de pagina opnieuw op uit koopjes.db,
    dus een gereserveerde flip staat er dan niet meer."""
    try:
        return rc.recheck_listing(db_path, form.get("item_id", "")).summary()
    except rc.RecheckError as exc:
        raise pg.FormError(str(exc)) from None


def action_bid(db_path, form: dict) -> str:
    """Een bod dat je zelf op Marktplaats deed, vastleggen (own_bids.py). Het
    script biedt nooit zelf."""
    item_id = form.get("item_id", "")
    amount = pg.parse_euro(form.get("bedrag"), "Bod")
    conn = db.connect(str(db_path))
    try:
        ob.place(conn, item_id, amount, bid_at=None)
        title = (conn.execute("SELECT title FROM listing WHERE item_id = ?", (item_id,)).fetchone() or [item_id])[0]
    except ValueError as exc:
        raise pg.FormError(str(exc)) from None
    finally:
        conn.close()
    return f"Bod van {euro(amount)} vastgelegd op {title}."


def expected_resale(db_path, form: dict, item_id: str) -> tuple[str, Optional[float]]:
    """(markt voor /flips, verwachte verkoopprijs) bij een geaccepteerd bod:
    een racefiets is een fiets op /flips, met de flipschatting van
    /racefietsen; een computer of horloge zijn eigen markt, met de
    verkoopprijs van zijn model."""
    if form.get("markt") == rb.MARKET_KEY:
        return rb.FLIP_MARKET, rb.resale_for(db_path, item_id)
    market = mk.by_key(form.get("markt"))
    d = dash.load_dashboard(db_path, market=market)
    listing = next((l for l in d.listings if l.item_id == item_id), None)
    c = listing.computer if listing is not None else None
    return market.key, (c.resale_eur if c is not None else None)


def action_bid_status(db_path, form: dict) -> str:
    item_id, status = form.get("item_id", ""), form.get("status", "")
    if status not in ob.STATUSES:
        raise pg.FormError(f"Onbekende status '{status}'.")
    market, resale = expected_resale(db_path, form, item_id) if status == ob.ACCEPTED else ("", None)
    conn = db.connect(str(db_path))
    try:
        bid, trade_id = ob.set_status(conn, item_id, status, market=market or rb.FLIP_MARKET,
                                      expected_resale_eur=resale)
    except ValueError as exc:
        raise pg.FormError(str(exc)) from None
    finally:
        conn.close()
    if status == ob.ACCEPTED and trade_id is not None:
        return f"Geaccepteerd voor {euro(bid.amount_eur)}: hij staat nu op /flips (fase gekocht)."
    return f"Bod van {euro(bid.amount_eur)}: {status}."


def action_postcode(db_path, form: dict) -> str:
    """De eigen postcode voor de afstanden (distance.py): één zoekverzoek aan
    Marktplaats om hem te plaatsen. Leeg wist hem."""
    text = (form.get("postcode") or "").strip()
    conn = db.connect(str(db_path))
    try:
        if not text:
            dm.save_home(conn, None)
            return "Postcode gewist; de pagina's tonen geen afstand meer."
        try:
            home = dm.locate_postcode(text)
        except dm.LocateError as exc:
            raise pg.FormError(str(exc)) from None
        dm.save_home(conn, home)
    finally:
        conn.close()
    return f"Afstanden gemeten vanaf {home.postcode}."


def action_add(db_path, form: dict) -> str:
    title = (form.get("titel") or "").strip()
    if not title:
        raise pg.FormError("Vul in wat het is.")
    model = form.get("model") or None
    target = mk.by_key(form.get("markt"))
    if model and model not in target.labels():
        raise pg.FormError(f"Onbekend model '{model}'.")
    price = pg.parse_euro(form.get("prijs"), "Inkoopprijs")
    costs = pg.parse_euro(form.get("kosten"), "Kosten", required=False) or 0.0
    market = (pc.market_resale(db_path, catalog=target.catalog(), categories=target.comp_categories)
              if model else {})
    conn = db.connect(str(db_path))
    try:
        db.add_trade(conn, title=title, bought_at=pg.parse_day(form.get("datum")), buy_price_eur=price,
                     buy_costs_eur=costs, model=model, expected_resale_eur=market.get(model),
                     notes=(form.get("notitie") or "").strip(), market=target.key)
    finally:
        conn.close()
    return f"Toegevoegd: {title} voor {euro(price)}."


def action_sold(db_path, form: dict) -> str:
    trade_id = pg.parse_id(form.get("id"))
    price, costs, via, sold_at, _ = fp.parse_sale(db_path, form, trade_id, "Onbekende regel.")
    conn = db.connect(str(db_path))
    try:
        if not db.sell_trade(conn, trade_id, sold_at=sold_at, sell_price_eur=price,
                             sell_costs_eur=costs, sold_via=via):
            raise pg.FormError("Onbekende regel.")
    finally:
        conn.close()
    return f"Verkocht voor {euro(price)}."


def action_unsell(db_path, form: dict) -> str:
    conn = db.connect(str(db_path))
    try:
        if not db.unsell_trade(conn, pg.parse_id(form.get("id"))):
            raise pg.FormError("Onbekende regel.")
    finally:
        conn.close()
    return "Terug naar voorraad."


def action_delete(db_path, form: dict) -> str:
    conn = db.connect(str(db_path))
    try:
        if not db.delete_trade(conn, pg.parse_id(form.get("id"))):
            raise pg.FormError("Onbekende regel.")
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
    "/notitie": action_note,
    "/controleer": action_check,
    "/bod": action_bid,
    "/bod/status": action_bid_status,
    "/afstand": action_postcode,
}


# Na deze acties terug naar de tab waar je klikte (het formulier zegt welke);
# na de rest naar Mijn flips, waar je ziet wat je vastlegde.
STAY_ON_TAB = {"/markeer", "/notitie", "/controleer", "/bod", "/bod/status", "/afstand"}


# Deze kunnen zonder herladen (live_update); de rest verandert te veel.
LIVE_ACTIONS = {"/markeer", "/notitie", "/bod", "/bod/status"}


# Op /racefietsen gaat ook controleer zonder herladen: de pagina tekent de
# fiets zelf opnieuw (racebikes.bike_update()).
RACE_LIVE_ACTIONS = LIVE_ACTIONS | {"/controleer"}


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
    intake_path = str(bp.INTAKE_PATH)
    photo_dir = fl.PHOTO_DIR
    launched: dict = {}  # de ronde die deze server startte: {"proc": Popen, "slot": naam}
    launch_lock = threading.Lock()
    files_dir = dash.HERE  # waar koopjes.py het overzicht en de rapporten schrijft
    sheets_config = fp.SHEETS_CONFIG
    cache: LiveCache = LiveCache()
    server_version = "koopjes-dashboard"

    def _origins(self) -> set:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self._origins()

    def _send_bytes(self, code: int, data: bytes, content_type: str, cache: str = "no-store",
                    headers: tuple = ()) -> None:
        """Eén antwoord met een body; `headers` zijn extra (naam, waarde)-paren."""
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            for name, value in headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # De browser verbrak de verbinding terwijl de pagina nog onderweg
            # was (ververst, gesloten, of twee keer geopend). Op Windows gaf dat
            # een traceback met WinError 10053 in het venster, terwijl er niets
            # mis is: de volgende aanvraag werkt gewoon.
            self.close_connection = True

    def _send(self, code: int, body: str, content_type: str = "text/plain; charset=utf-8") -> None:
        self._send_bytes(code, body.encode("utf-8"), content_type)

    def _back(self, message: str, market: mk.Market = mk.COMPUTERS, tab: str = "mijn",
              path: Optional[str] = None) -> None:
        # Alleen een tabnaam; iets anders (leeg, of wat een andere site
        # meestuurt) opent de eerste tab.
        anchor = f"#{tab}" if tab.isascii() and tab.isalpha() and tab.islower() else ""
        self.send_response(303)
        self.send_header("Location", (path or market.serve_path) + "?melding=" + quote(message) + anchor)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        path = "/" if url.path == "/index.html" else url.path.rstrip("/") or "/"
        market = next((m for m in mk.MARKETS.values() if m.serve_path == path), None)
        is_photo = path.startswith(fp.FLIPS_PHOTO_PATH + "/")
        is_file = path.startswith(pg.FILES_PATH + "/")
        pages = (pg.BIKE_PATH, pg.FLIPS_PATH, pg.START_PATH, pg.START_PATH + "/status", rb.PATH, dash.PANEL_PATH, rb.COMPS_PATH,
                 ut.PATH, ut.CSV_PATH)
        if path == "/favicon.ico":
            # De browser vraagt hem zelf bij elke eerste pagina; zonder dit
            # stond er een 404 in de console van elke pagina.
            self.send_response(204)
            self.send_header("Cache-Control", "max-age=86400")
            return self.end_headers()
        if market is None and path not in pages and not (is_photo or is_file):
            return self._send(404, "Niet gevonden")
        if not self._host_ok():
            return self._send(403, "Alleen via 127.0.0.1")
        message = parse_qs(url.query).get("melding", [""])[0][:300]
        if is_photo:
            return self._send_photo(path[len(fp.FLIPS_PHOTO_PATH) + 1:])
        if is_file:
            return self._send_file(unquote(path[len(pg.FILES_PATH) + 1:]))
        if path == pg.START_PATH:
            return self._send(200, st.render_start(self.db_path, self.files_dir, message, self.token,
                                                self._running_round()), "text/html; charset=utf-8")
        if path == pg.START_PATH + "/status":

            config = st.load_schedule(self.files_dir)
            return self._json({"running": bool(self._running_round()),
                               "log": launcher.log_tail(config) if config else ""})
        if path == dash.PANEL_PATH:
            return self._send_panel(parse_qs(url.query))
        if path == rb.COMPS_PATH:
            base = self.cache.racebikes(self.db_path, self.intake_path)
            return self._json(rb.comps_update(base, parse_qs(url.query).get("id", [""])[0]))
        if path in (ut.PATH, ut.CSV_PATH):
            return self._upgrade_page(path, message)
        if path == rb.PATH:
            base = self.cache.racebikes(self.db_path, self.intake_path)
            return self._send(200, rb.render(base, rb.load_fresh(self.db_path), self.token, message),
                              "text/html; charset=utf-8")
        if path == pg.FLIPS_PATH:
            book = fl.load_book(self.db_path)
            return self._send(200, fp.render_flips(book, self.token, message,
                                                sheets=fs.panel(self.sheets_config)),
                              "text/html; charset=utf-8")
        if market is None:
            view = bp.load_bike_view(self.db_path, self.intake_path, self.cache)
            return self._send(200, bp.render_bike(view, self.token, message),
                              "text/html; charset=utf-8")
        d = self._live_dashboard(market)
        d.other_links = []  # de balk bovenaan (site_nav) heeft ze allemaal
        d.message = message
        self._send(200, dash.render(d, lazy=dash.LAZY_PANELS), "text/html; charset=utf-8")

    def _upgrade_context(self) -> tuple:
        """(eigen fiets met de opgeslagen regel, probleem, fietsen) voor /upgrade."""
        owner, problem = report.load_owner_context(self.intake_path, self.db_path,
                                                   comps=self.cache.comps(self.db_path))
        bikes = self.cache.upgrade_bikes(self.db_path, self.intake_path) if owner is not None else []
        return owner, problem, bikes

    def _upgrade_page(self, path: str, message: str) -> None:
        owner, problem, bikes = self._upgrade_context()
        if path == ut.PATH:
            return self._send(200, ut.render(owner, problem, bikes, up.load_rule(self.db_path)[1], self.token,
                                             message), "text/html; charset=utf-8")
        if owner is None:
            return self._send(404, f"Geen eigen fiets: {problem}")
        self._send_bytes(200, ut.csv_download(owner, bikes, problem).encode("utf-8"), "text/csv; charset=utf-8",
                         headers=(("Content-Disposition", 'attachment; filename="upgrade_uitdraai.csv"'),))

    def _upgrade_post(self, path: str, form: dict) -> None:
        """De acties van /upgrade, altijd JSON: een oordeel, een regel
        doorrekenen, opslaan of terugzetten, zoeken, of één fiets uitleggen."""
        if not hmac.compare_digest(form.get("token", ""), self.token):
            return self._json({"message": "De pagina was verouderd; er is niets opgeslagen. Probeer het opnieuw.",
                               "reload": True})
        try:
            owner, problem, bikes = self._upgrade_context()
            if owner is None:
                return self._json({"message": f"Geen eigen fiets: {problem}", "error": True})
            if path == ut.LABEL_PATH:
                return self._json(ut.label_action(self.db_path, bikes, form))
            if path == ut.TRY_PATH:
                return self._json(ut.try_rule(owner, bikes, form))
            if path == ut.RULE_PATH:
                return self._json(ut.rule_action(self.db_path, owner, bikes, form))
            if path == ut.SEARCH_PATH:
                return self._json(ut.search_action(owner, bikes, form))
            return self._json(ut.explain_action(owner, bikes, form))
        except sqlite3.OperationalError as exc:
            if not db_busy(exc):
                raise
            self._json({"message": DB_BUSY, "error": True})

    def _live_dashboard(self, market: mk.Market) -> dash.Dashboard:
        d = self.cache.dashboard(self.db_path, market)
        d.editable, d.token = True, self.token
        return d

    def _send_panel(self, query: dict) -> None:
        """Eén tab van een live dashboard, voor een tab die de pagina pas
        ophaalt als je hem opent (LAZY_PANELS)."""
        market = mk.MARKETS.get(query.get("markt", [""])[0])
        name = query.get("naam", [""])[0]
        if market is None:
            return self._send(404, "Niet gevonden")
        d = self._live_dashboard(market)
        panel = next((panel for key, _, panel in dash.tab_list(d) if key == name), None)
        if panel is None:
            return self._send(404, "Niet gevonden")
        self._send(200, panel(d), "text/html; charset=utf-8")

    def _running_round(self) -> str:
        """Het slot dat deze server startte en nog loopt, "ja" voor een
        andere ronde (de taakplanner), of "" als er niets draait."""

        proc, slot = self.launched.get("proc"), self.launched.get("slot", "")
        if proc is not None and proc.poll() is None:
            return slot
        config = st.load_schedule(self.files_dir)
        return "ja" if config is not None and launcher.is_running(config) else ""

    def _start_round(self, path: str, form: dict) -> None:

        if not hmac.compare_digest(form.get("token", ""), self.token):
            return self._back("De pagina was verouderd; er is niets gestart. Probeer het opnieuw.", tab="",
                              path=pg.START_PATH)
        slot = form.get("item_id", "")
        config = st.load_schedule(self.files_dir)
        with self.launch_lock:
            try:
                if config is None:
                    raise launcher.LaunchError("Geen schedule.json gevonden.")
                if self._running_round():
                    raise launcher.LaunchError("Er draait al een ronde; wacht tot die klaar is.")
                self.launched.update(proc=launcher.start(config, slot), slot=slot)
                message = f"Ronde '{slot}' gestart."
            except launcher.LaunchError as exc:
                message = f"Niet gestart: {exc}"
        self._back(message, tab="", path=pg.START_PATH)

    def _send_file(self, name: str) -> None:
        if name in st.LIVE_INSTEAD:
            self.send_response(302)
            self.send_header("Location", st.LIVE_INSTEAD[name])
            self.send_header("Content-Length", "0")
            return self.end_headers()
        path = st.served_file(self.files_dir, name)
        if path is None:
            return self._send(404, "Niet gevonden")
        data = path.read_bytes()
        if path.suffix.lower() == ".html":
            data = st.with_file_nav(data)
        self._send_bytes(200, data, st.FILE_TYPES.get(path.suffix.lower(), "text/plain; charset=utf-8"))

    def _send_photo(self, ident: str) -> None:
        try:
            found = fl.photo_path(self.db_path, int(ident), self.photo_dir)
        except ValueError:
            found = None
        if found is None or not found[0].is_file():
            return self._send(404, "Niet gevonden")
        self._send_bytes(200, found[0].read_bytes(), found[1], cache="private, max-age=86400")

    def _upload_photo(self, url) -> None:
        """Eén foto als ruwe body (FLIPS_JS), het geheim in een kop: een
        formulier mag hier maar 10 kB zijn."""
        if not hmac.compare_digest(self.headers.get("X-Token", ""), self.token):
            return self._json({"message": "De pagina was verouderd; er is niets opgeslagen.", "reload": True})
        length = int(self.headers.get("Content-Length") or 0)
        if length > fl.MAX_PHOTO_BYTES:
            return self._send(413, "Te groot")
        data = self.rfile.read(length)
        query = parse_qs(url.query)
        try:
            trade_id = int(query.get("flip", [""])[0])
        except ValueError:
            return self._json({"message": "Niet opgeslagen: onbekende flip."})
        conn = db.connect(self.db_path)
        try:
            fl.add_photo(conn, trade_id, data, self.headers.get("Content-Type", ""),
                         query.get("soort", ["voor"])[0], self.photo_dir)
        except ValueError as exc:
            return self._json({"message": f"Niet opgeslagen: {exc}."})
        finally:
            conn.close()
        self._json(fp.flips_update(fl.load_book(self.db_path), trade_id, "Foto opgeslagen."))

    def _flip_post(self, path: str, form: dict) -> None:
        live = self.headers.get("X-Live") == "1" and path not in fp.FLIP_RELOAD
        if not hmac.compare_digest(form.get("token", ""), self.token):
            message = "De pagina was verouderd; er is niets opgeslagen. Probeer het opnieuw."
            if live:
                return self._json({"message": message, "reload": True})
            return self._back(message, path=pg.FLIPS_PATH)
        try:
            message, trade_id = fp.FLIP_ACTIONS[path](self.db_path, form, self)
            failed = False
        except pg.FormError as exc:
            message, trade_id, failed = f"Niet opgeslagen: {exc}", None, True
        except sqlite3.OperationalError as exc:
            if not db_busy(exc):
                raise
            message, trade_id, failed = DB_BUSY, None, True
        if not live:
            anchor = f"#flip-{trade_id}" if trade_id is not None and not failed else ""
            self.send_response(303)
            self.send_header("Location", pg.FLIPS_PATH + "?melding=" + quote(message) + anchor)
            self.send_header("Content-Length", "0")
            return self.end_headers()
        if failed:
            return self._json({"message": message})
        data = fp.flips_update(fl.load_book(self.db_path), trade_id, message)
        if path == "/flips/sync":
            data["changed"] = "overgenomen" in message and not message.startswith("Sheet: niets")
            data["status"] = message
            if form.get("auto") == "1" and not data["changed"]:
                data["message"] = ""
        self._json(data)

    def _race_model(self, path: str, form: dict) -> None:
        """Een eigen koppeling op /racefietsen (model, klopt, bouwjaar,
        ontkoppelen, nieuw model) of een regel (toepassen, nee, weg): altijd
        JSON, en alleen de fietsen die het raakt opnieuw
        (racebikes.refresh()) in de onthouden berekening — de hele pagina
        opnieuw kost met ~14.000 fietsen enkele seconden."""
        if not hmac.compare_digest(form.get("token", ""), self.token):
            return self._json({"message": "De pagina was verouderd; er is niets opgeslagen. Probeer het opnieuw.",
                               "reload": True})
        try:
            base = self.cache.racebikes(self.db_path, self.intake_path)
            update = rb.rule_update if path == rb.RULE_PATH else rb.model_update
            self._json(update(base, self.db_path, form))
        except sqlite3.OperationalError as exc:
            if not db_busy(exc):
                raise
            self._json({"message": DB_BUSY})

    def _dossier(self, path: str, form: dict) -> None:
        """De knop dossier op /racefietsen (dossier.py): de advertentie ophalen
        zoals controleer, dan alles over die ene fiets als tekst om aan Claude
        te geven, met de bijgewerkte kaart erbij."""
        if not hmac.compare_digest(form.get("token", ""), self.token):
            return self._json({"message": "De pagina was verouderd; er is niets opgeslagen. Probeer het opnieuw.",
                               "reload": True})
        item_id = form.get("item_id", "")
        try:
            checked, problem, message = ds.fetch(self.db_path, item_id)
            # Na het ophalen: controleer veranderde de database, dus dit
            # rekent opnieuw, net als na de knop controleer.
            base = self.cache.racebikes(self.db_path, self.intake_path)
            text = ds.build(base, self.db_path, item_id, self.intake_path, checked, problem)
            data = rb.bike_update(base, rb.load_fresh(self.db_path), item_id, message)
        except ds.DossierError as exc:
            return self._json({"message": f"Geen dossier: {exc}"})
        except sqlite3.OperationalError as exc:
            if not db_busy(exc):
                raise
            return self._json({"message": DB_BUSY})
        data["dossier"] = text
        self._json(data)

    def _reserve(self, path: str, form: dict) -> None:
        """De gekozen soorten onderdelen op /racefietsen (spares.py)."""
        if not hmac.compare_digest(form.get("token", ""), self.token):
            return self._json({"message": "De pagina was verouderd; er is niets opgeslagen.", "reload": True})
        try:
            self._json(rb.reserve_update(self.db_path, form))
        except sqlite3.OperationalError as exc:
            if not db_busy(exc):
                raise
            self._json({"message": DB_BUSY})

    def do_POST(self) -> None:
        origin = self.headers.get("Origin")
        if not self._host_ok() or (origin and urlsplit(origin).netloc not in self._origins()):
            return self._send(403, "Alleen via 127.0.0.1")
        url = urlsplit(self.path)
        path = url.path
        if path == fp.FLIPS_PHOTO_PATH:
            return self._upload_photo(url)
        routes = {pg.START_PATH + "/ronde": self._start_round, rb.RESERVE_PATH: self._reserve, ds.PATH: self._dossier,
                  rb.MODEL_PATH: self._race_model, rb.RULE_PATH: self._race_model,
                  **dict.fromkeys(fp.FLIP_ACTIONS, self._flip_post), **dict.fromkeys(ut.POST_PATHS, self._upgrade_post)}
        action = bp.action_choice if path == bp.BIKE_CHOICE_PATH else ACTIONS.get(path)
        if path not in routes and action is None:
            return self._send(404, "Niet gevonden")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_FORM_BYTES:
            return self._send(413, "Te groot")
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        form = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
        if path in routes:
            return routes[path](path, form)
        market = mk.by_key(form.get("markt"))
        race = form.get("markt") == rb.MARKET_KEY
        back = pg.BIKE_PATH if path == bp.BIKE_CHOICE_PATH else rb.PATH if race else None
        tab = form.get("tab", "") if path in STAY_ON_TAB else ("" if back else "mijn")
        # Van de pagina zelf, zonder herladen (fetch met deze kop): het
        # antwoord is JSON met de stukjes die veranderden.
        live = self.headers.get("X-Live") == "1" and (
            path in (RACE_LIVE_ACTIONS if race else LIVE_ACTIONS) or path == bp.BIKE_CHOICE_PATH)
        if not hmac.compare_digest(form.get("token", ""), self.token):
            # Een verouderde pagina (programma opnieuw gestart) of een
            # andere site: niets doen, alleen de verse pagina tonen.
            message = "De pagina was verouderd; er is niets opgeslagen. Probeer het opnieuw."
            if live:
                return self._json({"message": message, "reload": True})
            return self._back(message, market, tab, back)
        try:
            message = action(self.db_path, form)
            failed = False
        except pg.FormError as exc:
            message, failed = f"Niet opgeslagen: {exc}", True
        except sqlite3.OperationalError as exc:
            if not db_busy(exc):
                raise
            message, failed = DB_BUSY, True
        if not live:
            return self._back(message, market, tab, back)
        item_id = form.get("item_id", "")
        if failed:
            return self._json({"message": message})
        if race:
            base = self.cache.racebikes(self.db_path, self.intake_path)
            data = rb.bike_update(base, rb.load_fresh(self.db_path), item_id, message)
            if path == "/bod/status":
                # Geaccepteerd zet de fiets op /flips: Mijn flips meteen bij.
                data["flips"] = list(rb.own_flips_html(self.db_path))
            return self._json(data)
        if back:
            view = bp.load_bike_view(self.db_path, self.intake_path, self.cache)
            return self._json(bp.bike_update(view, item_id, message))
        d = self._live_dashboard(market)
        self._json(dash.live_update(d, item_id, message, form.get("soort") if path == "/markeer" else None,
                               bids_changed=path.startswith("/bod")))

    def _json(self, data: dict) -> None:
        self._send(200, json.dumps(data), "application/json; charset=utf-8")

    def log_message(self, format: str, *args) -> None:
        pass  # geen regel per verzoek in de terminal


def make_server(db_path, port: int = 8765, intake_path=bp.INTAKE_PATH, photo_dir=None,
                sheets_config=None, files_dir=None) -> ThreadingHTTPServer:
    """De server, klaar om te draaien (serve_forever). Migreert de database
    eerst, zodat de tabellen `trade`, `listing_mark`, `listing_note` en
    `comp_choice` bestaan."""
    db.connect(str(db_path)).close()
    attrs = {"db_path": str(db_path), "token": secrets.token_urlsafe(24), "intake_path": str(intake_path),
             "cache": LiveCache(), "launched": {}, "launch_lock": threading.Lock()}
    if photo_dir is not None:
        attrs["photo_dir"] = Path(photo_dir)
    if sheets_config is not None:
        attrs["sheets_config"] = str(sheets_config)
    if files_dir is not None:
        attrs["files_dir"] = Path(files_dir)
    handler = type("Handler", (DashboardHandler,), attrs)
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def serve(db_path, port: int, open_browser: bool) -> int:
    try:
        httpd = make_server(db_path, port)
    except OSError as exc:
        print(f"Kan niet starten op poort {port}: {exc}. Probeer --port met een ander getal.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    print(f"Alles live op {url}{pg.START_PATH} (fietscomputers {url}/, sporthorloges {url}/horloges, mijn fiets "
          f"{url}/fiets, flips {url}/flips, rapporten via de startpagina) — stoppen met Ctrl+C.")
    if open_browser:
        webbrowser.open(url + pg.START_PATH)
    stop = threading.Event()
    handler = httpd.RequestHandlerClass
    threading.Thread(target=keep_warm, args=(handler.cache, handler.db_path, handler.intake_path, stop),
                     daemon=True, name="warm").start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nGestopt.")
    finally:
        stop.set()
        httpd.server_close()
    return 0
