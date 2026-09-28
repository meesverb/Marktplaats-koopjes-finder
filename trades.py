"""Mijn flips: wat de eigenaar zelf kocht en verkocht, en hoe het gaat.

De gegevens staan in de tabel `trade` (db.py, migratie 7) en worden ingevoerd
via het dashboard (`python dashboard.py --serve`). Dit bestand rekent alleen:
winst per verkoop, wat er nog op voorraad ligt en wat dat naar verwachting
oplevert, de doorlooptijd, winst per maand, en hoe ver de schatting van het
dashboard bij de aankoop ernaast zat — dat laatste is de eerste échte meting
van de onderhandelingsfactor (0,875) die nu nog een aanname is.

Eigen aan- en verkopen zijn geen marktwaarnemingen: ze tellen nergens mee als
vergelijkingsprijs.
"""
from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import db


@dataclass
class Trade:
    id: int
    title: str
    bought_at: str
    buy_price_eur: float
    buy_costs_eur: float = 0.0
    item_id: Optional[str] = None
    url: Optional[str] = None
    model: Optional[str] = None
    expected_resale_eur: Optional[float] = None
    sold_at: Optional[str] = None
    sell_price_eur: Optional[float] = None
    sell_costs_eur: float = 0.0
    sold_via: Optional[str] = None
    notes: Optional[str] = None
    market: Optional[str] = None  # migratie 10; zie markets.trade_market()

    @property
    def sold(self) -> bool:
        return self.sold_at is not None and self.sell_price_eur is not None

    @property
    def cost_basis_eur(self) -> float:
        return self.buy_price_eur + (self.buy_costs_eur or 0.0)

    @property
    def profit_eur(self) -> Optional[float]:
        if not self.sold:
            return None
        return round(self.sell_price_eur - (self.sell_costs_eur or 0.0) - self.cost_basis_eur, 2)

    def days_held(self, today: Optional[date] = None) -> Optional[int]:
        start = _date(self.bought_at)
        end = _date(self.sold_at) if self.sold else (today or date.today())
        if start is None or end is None:
            return None
        return (end - start).days


def _date(value: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


FIELDS = {f for f in Trade.__dataclass_fields__}


def from_row(row: dict) -> Trade:
    return Trade(**{k: v for k, v in row.items() if k in FIELDS})


def load_trades(db_path) -> list[Trade]:
    """Alleen lezen. Geen database, of een van vóór migratie 7: geen trades."""
    if not db_path or not Path(db_path).exists():
        return []
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        return [from_row(r) for r in db.list_trades(conn)]
    finally:
        conn.close()


@dataclass
class StockItem:
    trade: Trade
    expected_resale_eur: Optional[float]  # nu, uit de markt; anders wat bij aankoop verwacht werd
    expected_profit_eur: Optional[float]


@dataclass
class Progress:
    sold: list  # Trade, laatst verkocht eerst
    stock: list  # StockItem
    realized_profit_eur: float = 0.0
    revenue_eur: float = 0.0
    invested_in_stock_eur: float = 0.0
    expected_stock_profit_eur: Optional[float] = None
    avg_days_to_sell: Optional[float] = None
    # Gemiddeld (verkocht − verwacht) / verwacht, over verkopen met een
    # verwachting; positief = je verkoopt boven de schatting.
    estimate_error: Optional[float] = None
    estimate_n: int = 0
    monthly: list = field(default_factory=list)  # [(JJJJ-MM, winst)]

    @property
    def has_any(self) -> bool:
        return bool(self.sold or self.stock)


def progress(trades: list[Trade], market: dict, shipping_eur: float) -> Progress:
    """`market`: {modellabel: verwachte verkoopprijs nu}. `shipping_eur` gaat af
    van de verwachte winst op voorraad, net als bij een flip."""
    sold = sorted((t for t in trades if t.sold), key=lambda t: (t.sold_at, t.id), reverse=True)
    stock = []
    for t in (t for t in trades if not t.sold):
        resale = market.get(t.model) if t.model else None
        if resale is None:
            resale = t.expected_resale_eur
        profit = None if resale is None else round(resale - shipping_eur - t.cost_basis_eur, 2)
        stock.append(StockItem(t, resale, profit))

    p = Progress(sold=sold, stock=stock)
    p.realized_profit_eur = round(sum(t.profit_eur for t in sold), 2)
    p.revenue_eur = round(sum(t.sell_price_eur for t in sold), 2)
    p.invested_in_stock_eur = round(sum(s.trade.cost_basis_eur for s in stock), 2)
    known = [s.expected_profit_eur for s in stock if s.expected_profit_eur is not None]
    p.expected_stock_profit_eur = round(sum(known), 2) if known else None
    days = [t.days_held() for t in sold if t.days_held() is not None]
    p.avg_days_to_sell = round(statistics.mean(days), 1) if days else None
    errors = [(t.sell_price_eur - t.expected_resale_eur) / t.expected_resale_eur
              for t in sold if t.expected_resale_eur]
    if errors:
        p.estimate_error, p.estimate_n = statistics.mean(errors), len(errors)
    months: dict[str, float] = {}
    for t in sold:
        months[t.sold_at[:7]] = months.get(t.sold_at[:7], 0.0) + t.profit_eur
    p.monthly = [(m, round(v, 2)) for m, v in sorted(months.items())]
    return p
