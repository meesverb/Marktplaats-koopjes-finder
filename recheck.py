"""Eén advertentie nu opnieuw bekijken op Marktplaats: de knop "controleer"
in het live dashboard (`python dashboard.py --serve`).

Het dashboard weet alleen wat de laatste ronde zag, en die kan uren oud zijn.
Overdag bekijkt de ronde `computers` alleen de nieuwste twee pagina's; een
advertentie van een week oud komt alleen in de nachtronde weer langs. Een
Garmin Edge 1040 die overdag gereserveerd werd, stond daardoor tot de
volgende nacht bij Flips. En biedingen op een advertentie met vraagprijs
(MIN_BID) staan alleen op de advertentiepagina zelf, die de ronde voor de
horloges niet ophaalt (bid_lookup fast): een Suunto van €290 waarop al €350
geboden was, rekende als flip met €290.

De advertentiepagina heeft het allemaal: isReserved, de biedingen en de
prijs, en een verdwenen advertentie geeft 410. Dit haalt die pagina op en
schrijft wat erop staat in koopjes.db (db.record_listing_check()), met
dezelfde biedregels als de ronde (racefiets_jev.apply_bid_info()).

Alleen op verzoek, één verzoek per klik, nooit twee tegelijk en nooit sneller
achter elkaar dan de standaard --delay van de ronde. Leest alleen: bieden of
reageren doet de eigenaar zelf.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests

import db
import racefiets_jev as mp

# Wat Marktplaats teruggeeft voor een advertentie die weg is (verkocht,
# ingetrokken of verlopen): 410, gezien op 29-09-2026. 404 voor de zekerheid.
GONE_STATUSES = (404, 410)
# De standaard --delay van racefiets_jev.py: klik je snel een rij knoppen
# af, dan wacht de volgende zo lang als een ronde tussen twee pagina's zou
# doen. Tests zetten hem op 0.
MIN_INTERVAL_S = 1.5
TIMEOUT_S = 15

# De server (ThreadingHTTPServer) handelt elke klik in een eigen thread af;
# het slot houdt de verzoeken aan Marktplaats toch achter elkaar.
_lock = threading.Lock()
_last_request = 0.0


class RecheckError(Exception):
    """Controleren lukte niet; de tekst gaat naar de pagina. Er is dan niets
    opgeslagen."""


@dataclass
class Recheck:
    item_id: str
    title: str
    gone: bool = False
    was_reserved: bool = False
    reserved: bool = False
    price_before: Optional[float] = None
    price: Optional[float] = None
    price_type: str = ""
    asking: Optional[float] = None  # de prijs op de pagina, vóór de biedingen
    bid_count: Optional[int] = None  # None: geen biedadvertentie
    bid_high: Optional[float] = None
    # Alleen met details=True (de knop dossier, dossier.py): wat de pagina
    # verder zegt. page: het listing-object uit window.__CONFIG__ (foto's,
    # verkoper, verzenden); description None: de omschrijving stond niet waar
    # hij stond.
    page: Optional[dict] = None
    description: Optional[str] = None
    attributes: dict = field(default_factory=dict)  # de Kenmerken, {label: waarde}

    def summary(self) -> str:
        """Wat de controle vond, in één zin voor de melding bovenaan."""
        if self.gone:
            return (f"Gecontroleerd: {self.title} staat niet meer op Marktplaats (verkocht of ingetrokken) "
                    "en is uit het dashboard gehaald.")
        parts = []
        if self.reserved:
            parts.append("nog steeds gereserveerd" if self.was_reserved
                         else "gereserveerd, dus weg uit Flips en Zonder prijs")
        elif self.was_reserved:
            parts.append("niet meer gereserveerd")
        if self.bid_count is not None:
            if not self.bid_count:
                parts.append("nog geen bod")
            else:
                bids = f"{self.bid_count} bieding{'en' if self.bid_count != 1 else ''}, hoogste {_euro(self.bid_high)}"
                if self.price_type == "MIN_BID" and self.asking is not None and self.bid_high > self.asking:
                    bids += f", boven de vraagprijs van {_euro(self.asking)}"
                parts.append(bids)
        if self.price != self.price_before:
            parts.append(f"prijs {_euro(self.price_before)} → {_euro(self.price)}")
        if not parts:
            parts.append(f"nog te koop voor {_euro(self.price)}" if self.price is not None
                         else "nog te koop, niets veranderd")
        return f"Gecontroleerd: {self.title} — {'; '.join(parts)}."


def _euro(amount: Optional[float]) -> str:
    if amount is None:
        return "geen prijs"
    return f"€{amount:,.0f}".replace(",", ".")


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": mp.USER_AGENT, "Accept-Language": "nl-NL,nl;q=0.9"})
    return session


def _get(session, url: str):
    global _last_request
    with _lock:
        wait = _last_request + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return session.get(url, timeout=TIMEOUT_S)
        finally:
            _last_request = time.monotonic()


def _structure_error(detail: str) -> RecheckError:
    return RecheckError(f"De advertentiepagina is niet te lezen ({detail}) — Marktplaats heeft waarschijnlijk "
                        "zijn paginastructuur gewijzigd. Er is niets opgeslagen.")


def recheck_listing(db_path, item_id: str, session=None, now: Optional[str] = None,
                    details: bool = False) -> Recheck:
    """Haal de advertentiepagina van `item_id` op en leg vast wat erop staat.
    `details`: ook de volledige omschrijving bewaren (zoals het opzoeken van
    bouwjaren, racebikes.lookup_years()) en de pagina zelf meegeven, voor
    het dossier; hetzelfde ene verzoek. `session` en `now` zijn voor de tests."""
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = db.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT item_id, title, url, price_eur, price_type, bid_high, reserved_at FROM listing "
            "WHERE item_id = ?", (item_id,)
        ).fetchone()
        if row is None or not row["url"]:
            raise RecheckError("Die advertentie staat niet in de database.")
        # De prijs zoals het dashboard hem toonde: daar geldt een eerder bod
        # boven de vraagprijs, ook als een latere ronde de vraagprijs terugschreef.
        before = row["price_eur"]
        if row["price_type"] == "MIN_BID" and row["bid_high"] is not None and (before or 0) < row["bid_high"]:
            before = row["bid_high"]
        result = Recheck(item_id=item_id, title=row["title"] or item_id,
                         was_reserved=row["reserved_at"] is not None, price_before=before)

        try:
            resp = _get(session or make_session(), row["url"])
            if resp.status_code in GONE_STATUSES:
                db.record_listing_gone(conn, item_id, now)
                result.gone = True
                return result
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RecheckError(f"Kon de advertentie niet ophalen bij Marktplaats ({exc}). "
                               "Er is niets opgeslagen.") from None

        try:
            page = mp.listing_page_data(resp.text)
        except mp.ListingPageError as exc:
            raise _structure_error(str(exc)) from None
        if page is None:
            raise _structure_error("geen advertentie in window.__CONFIG__")
        # Een doorverwijzing naar een andere advertentie is geen antwoord op
        # de vraag hoe het met deze staat.
        if page.get("itemId") not in (None, item_id):
            raise RecheckError(f"Marktplaats stuurde door naar een andere advertentie ({page.get('itemId')}). "
                               "Er is niets opgeslagen.")
        missing = [key for key in ("isReserved", "priceInfo") if key not in page]
        if missing:
            raise _structure_error(f"{', '.join(missing)} ontbreekt")

        price, price_type = mp.price_from_info(page.get("priceInfo") or {})
        listing = mp.Listing(
            item_id=item_id, title=result.title, description="", price_eur=price, price_type=price_type,
            city="", date="", condition="", frame_height="", groupset="", groupset_tier=None,
            url=row["url"], price_is_bid=price_type in mp.BID_PRICE_TYPES,
            reserved=page.get("isReserved") is True,
        )
        if listing.price_is_bid:
            bids_info = page.get("bidsInfo")
            if not isinstance(bids_info, dict) or not bids_info:
                raise _structure_error("biedinformatie ontbreekt bij een biedadvertentie")
            mp.apply_bid_info(listing, bids_info)
        stats = mp.page_stats(page)
        if stats:
            listing.page_stats = {**stats, "source": "controleer"}
        db.record_listing_check(conn, listing, now)
        if details:
            result.page = page
            parsed = mp.parse_listing_page(resp.text)
            if parsed is not None:
                result.description, result.attributes = parsed
                db.save_listing_details(conn, {item_id: result.description}, now)
    finally:
        conn.close()

    result.reserved = listing.reserved
    result.price, result.price_type, result.asking = listing.price_eur, price_type, price
    result.bid_count, result.bid_high = listing.bid_count, listing.bid_high
    return result
