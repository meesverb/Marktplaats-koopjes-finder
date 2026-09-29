"""Eigen markeringen op advertenties: favoriet, of weg (niet waard,
gereserveerd), zodat je in het dashboard niet steeds dezelfde advertenties
langsloopt. En een eigen notitie bij elke advertentie.

De markeringen staan in de tabel `listing_mark` (db.py, migratie 12), de
notities in `listing_note` (migratie 15). Los van elkaar: een notitie gaat
over de advertentie (wat de verkoper zei, wat je bood), een markering is je
oordeel erover. Weghalen van de markering laat de notitie staan. Beide
worden gezet via de live versie van het dashboard (`python dashboard.py
--serve`); het geschreven dashboard.html toont ze alleen.

Een markering is het oordeel van de eigenaar, geen marktwaarneming: een
weggezette advertentie telt gewoon mee als vergelijkingsprijs, want de
vraagprijs is net zo echt als die van elke andere. Weg betekent weg uit
Flips, Upgrades en Zonder prijs (ook in `python watches.py`); in Alle
computers staat hij nog, achter het filter Toon.

Weg is niet voor altijd: zakt de prijs onder die van het moment van
wegzetten, dan komt de advertentie terug, met een regel erbij. Behalve
"geen racefiets" (PERMANENT_REASONS): dat verandert niet met de prijs. "Niet waard
voor €150" zegt niets over €110, en een verkoper die na een afgesprongen
reservering de prijs verlaagt, wil je ook zien.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import db

FAVORITE = "favoriet"
DISMISSED = "weg"
# De redenen om weg te zetten, zoals op de knoppen. Een nieuwe reden is een
# nieuw woord hier; de tabel slaat hem als tekst op.
REASONS = ("niet waard", "gereserveerd")
# Op /racefietsen meer (de eigenaar, 29-09-2026): bij een fiets is "niet
# waard" vaak specifieker te zeggen, en dat is later terug te lezen in
# listing_mark (welke fietsen, en waarom).
BIKE_REASONS = REASONS + ("niet doorverkoopbaar", "te hoge vraagprijs", "slechte staat", "geen racefiets")
ALL_REASONS = BIKE_REASONS
# Deze komen niet terug als de prijs zakt: een frame of een e-bike wordt
# geen racefiets door goedkoper te worden.
PERMANENT_REASONS = frozenset({"geen racefiets"})
# Een notitie is een geheugensteun, geen verslag.
NOTE_MAX_CHARS = 500


@dataclass
class Mark:
    item_id: str
    mark: str
    marked_at: str
    reason: Optional[str] = None
    price_eur: Optional[float] = None  # de prijs toen hij gemarkeerd werd
    # Wat `listing` er nu van weet; ook voor een advertentie die niet meer
    # actief is (een verdwenen favoriet).
    title: Optional[str] = None
    url: Optional[str] = None
    current_price_eur: Optional[float] = None
    last_seen: Optional[str] = None
    disappeared_at: Optional[str] = None

    @property
    def favorite(self) -> bool:
        return self.mark == FAVORITE

    @property
    def label(self) -> str:
        if self.favorite:
            return "favoriet"
        return f"weggezet ({self.reason})" if self.reason else "weggezet"


FIELDS = {f for f in Mark.__dataclass_fields__}


def load_marks(db_path) -> dict[str, Mark]:
    """{item_id: Mark}, alleen lezen. Geen database, of een van vóór migratie
    12: geen markeringen."""
    if not db_path or not Path(db_path).exists():
        return {}
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = db.list_marks(conn)
    finally:
        conn.close()
    return {r["item_id"]: Mark(**{k: v for k, v in r.items() if k in FIELDS}) for r in rows}


def load_notes(db_path) -> dict[str, str]:
    """{item_id: notitie}, alleen lezen. Geen database: geen notities."""
    if not db_path or not Path(db_path).exists():
        return {}
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        return db.list_notes(conn)
    finally:
        conn.close()


def price_dropped(mark: Mark, listing) -> bool:
    """Staat de advertentie nu lager dan toen hij gemarkeerd werd? Zonder
    prijs aan een van beide kanten (bieden, of weggezet toen er nog geen
    prijs stond) valt er niets te vergelijken. Bij een reden die niet van de
    prijs afhangt (PERMANENT_REASONS) telt een lagere prijs niet."""
    if mark.reason in PERMANENT_REASONS:
        return False
    return (mark.price_eur is not None and listing.price_eur is not None
            and listing.price_eur < mark.price_eur)


def is_dismissed(mark: Optional[Mark], listing) -> bool:
    """Weggezet, en de prijs is sindsdien niet gezakt."""
    return mark is not None and mark.mark == DISMISSED and not price_dropped(mark, listing)
