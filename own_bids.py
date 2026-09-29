"""De biedingen die de eigenaar zelf op Marktplaats deed: bedrag, datum en
hoe het ervoor staat. Vastgelegd via de knop "bod" in `python dashboard.py
--serve` (racefietsen, fietscomputers, sporthorloges), bewaard in `own_bid`
(db.py, migratie 18).

Het script biedt nooit zelf en reageert nergens op (CLAUDE.md): wat hier
staat, heeft de eigenaar op Marktplaats gedaan en daarna overgetypt.

Elk bod is een eigen regel, zodat de geschiedenis blijft staan (eerst €250,
toen €280). Het laatste bod op een advertentie is het bod dat telt: zijn
status is de status van de advertentie in Mijn biedingen. Een nieuw bod
laat de oude staan zoals ze waren.

Geaccepteerd = gekocht: de advertentie gaat meteen naar /flips (een fiets als
flip in de fase gekocht, een computer of horloge onder zijn eigen markt), met
het bod als inkoopprijs, en `trade_id` wijst ernaar. Terug naar een andere
status laat die flip staan; die haal je op /flips weg als de koop toch niet
doorging.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import db

OPEN = "open"
ACCEPTED = "geaccepteerd"
# In de volgorde van de knoppen. Een nieuwe status is een nieuw woord hier.
STATUSES = (OPEN, "overboden", "afgewezen", ACCEPTED, "ingetrokken")
# Waarmee je nog iets moet: bovenaan in Mijn biedingen.
ACTIVE = {OPEN, "overboden"}


@dataclass
class Bid:
    id: int
    item_id: str
    amount_eur: float
    bid_at: str
    status: str
    status_at: str
    trade_id: Optional[int] = None


@dataclass
class BidTrail:
    """Alle eigen biedingen op één advertentie, oudste eerst, met wat de
    database nu van die advertentie weet."""
    item_id: str
    bids: list = field(default_factory=list)  # Bid
    title: str = ""
    url: str = ""
    price_eur: Optional[float] = None
    bid_high: Optional[float] = None  # het hoogste bod dat de laatste opvraging zag
    bid_count: Optional[int] = None
    last_seen: str = ""
    disappeared_at: Optional[str] = None
    reserved_at: Optional[str] = None

    @property
    def latest(self) -> Bid:
        return self.bids[-1]

    @property
    def status(self) -> str:
        return self.latest.status

    @property
    def active(self) -> bool:
        return self.status in ACTIVE

    @property
    def gone(self) -> bool:
        return self.disappeared_at is not None

    @property
    def outbid(self) -> bool:
        """Staat er op Marktplaats een hoger bod dan het jouwe (volgens de
        laatste opvraging)?"""
        return self.bid_high is not None and self.bid_high > self.latest.amount_eur


def load(db_path) -> dict[str, BidTrail]:
    """{item_id: BidTrail}, alleen lezen. Geen database of van vóór 18: leeg."""
    if not db_path or not Path(db_path).exists():
        return {}
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = db.list_own_bids(conn)
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    trails: dict[str, BidTrail] = {}
    for r in rows:
        trail = trails.get(r["item_id"])
        if trail is None:
            trail = trails[r["item_id"]] = BidTrail(
                r["item_id"], title=r["title"] or r["item_id"], url=r["url"] or "",
                price_eur=r["current_price_eur"], bid_high=r["bid_high"], bid_count=r["bid_count"],
                last_seen=r["last_seen"] or "", disappeared_at=r["disappeared_at"], reserved_at=r["reserved_at"])
        trail.bids.append(Bid(r["id"], r["item_id"], r["amount_eur"], r["bid_at"], r["status"], r["status_at"],
                              r["trade_id"]))
    return trails


def ordered(trails: dict[str, BidTrail]) -> list[BidTrail]:
    """Lopend eerst, daarna de rest; binnen elke groep het nieuwste bod eerst."""
    newest_first = sorted(trails.values(), key=lambda t: (t.latest.bid_at, t.latest.id), reverse=True)
    return sorted(newest_first, key=lambda t: not t.active)  # sorted() is stabiel


def place(conn: sqlite3.Connection, item_id: str, amount_eur: float, bid_at: Optional[str] = None) -> int:
    if amount_eur <= 0:
        raise ValueError("een bod moet meer dan €0 zijn")
    if conn.execute("SELECT 1 FROM listing WHERE item_id = ?", (item_id,)).fetchone() is None:
        raise ValueError("onbekende advertentie")
    return db.add_own_bid(conn, item_id, amount_eur, bid_at)


def latest_bid(conn: sqlite3.Connection, item_id: str) -> Optional[Bid]:
    row = conn.execute(
        "SELECT id, item_id, amount_eur, bid_at, status, status_at, trade_id FROM own_bid "
        "WHERE item_id = ? ORDER BY bid_at DESC, id DESC LIMIT 1", (item_id,)).fetchone()
    return None if row is None else Bid(*row)


def set_status(conn: sqlite3.Connection, item_id: str, status: str, *, market: str,
               expected_resale_eur: Optional[float] = None, today: Optional[str] = None) -> tuple[Bid, Optional[int]]:
    """Zet de status van het laatste bod. Geaccepteerd maakt (één keer) een
    flip aan in /flips; geeft (bod, trade_id van die flip of None)."""
    import flips as fl

    if status not in STATUSES:
        raise ValueError(f"onbekende status {status!r}")
    bid = latest_bid(conn, item_id)
    if bid is None:
        raise ValueError("op deze advertentie heb je nog geen bod vastgelegd")
    trade_id = None
    if status == ACCEPTED and bid.trade_id is None:
        row = conn.execute("SELECT title, url FROM listing WHERE item_id = ?", (item_id,)).fetchone()
        title, url = (row[0], row[1]) if row else (item_id, None)
        existing = conn.execute("SELECT id FROM trade WHERE item_id = ?", (item_id,)).fetchone()
        if existing is not None:
            trade_id = existing[0]  # al gekocht via Gekocht of /flips: niet dubbel
        else:
            trade_id = fl.create_flip(conn, title=title or item_id, market=market,
                                      bought_at=today or date.today().isoformat(), buy_price_eur=bid.amount_eur,
                                      url=url, item_id=item_id, stage="gekocht",
                                      target_low_eur=expected_resale_eur,
                                      notes=f"bod van €{bid.amount_eur:.0f} geaccepteerd")
    db.set_own_bid_status(conn, bid.id, status, trade_id)
    return latest_bid(conn, item_id), trade_id
