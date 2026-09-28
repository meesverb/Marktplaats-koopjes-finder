"""Patronen: wat de verzamelde fietscomputer-advertenties over langere tijd
zeggen. Rekent op koopjes.db (alleen lezen) en wordt getoond in de tab
Patronen van het dashboard.

Alles leunt op wat de nachtelijke volledige crawl vastlegt: wanneer een
advertentie voor het eerst en het laatst gezien is, wanneer hij verdween
(db.sweep_disappeared, alleen bij een complete crawl) en de prijs bij elke
waarneming (listing_price). Verdwenen is niet verkocht — een advertentie kan
ook ingetrokken of verlopen zijn. Het is een benadering, dezelfde als de
taxatie van de eigen fiets gebruikt (valuation.py, E2), en de pagina zegt
dat erbij. Dichter bij verkocht komt een advertentie die verdween terwijl
hij gereserveerd stond (listing.reserved_at, migratie 9); die worden apart
geteld. Alleen wat een ronde gereserveerd zag telt, dus het is een
ondergrens.

Wat er níet in kan: het uur waarop advertenties geplaatst worden. Marktplaats
geeft "Vandaag"/"Gisteren" als plaatsingsdatum, en first_seen is het moment
van de crawl, niet van plaatsen.
"""
from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import computers as pc

# Zelfde grens als valuation.QUICK_SALE_DAYS: wie binnen twee weken weg is,
# was realistisch geprijsd.
QUICK_DAYS = 14
# Onder deze aantallen is een getal per model ruis; het wordt dan niet getoond.
MIN_PER_MODEL = 5
# Vanaf hier is de gemeten afdingfactor een alternatief voor 0,875
# (valuation.EMPIRICAL_MIN_N gebruikt hetzelfde getal).
MIN_FOR_FACTOR = 20
WEEKDAYS = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")


@dataclass
class Seen:
    """Eén computeradvertentie zoals de database hem kent."""
    item_id: str
    model: str
    first_seen: datetime
    last_seen: datetime
    gone: bool
    days_online: Optional[int]
    first_price: Optional[float]
    last_price: Optional[float]
    reserved: bool = False  # stond gereserveerd bij de laatste waarneming


@dataclass
class ModelPattern:
    model: str
    seen: int
    gone: int
    gone_reserved: int  # waarvan eerst gereserveerd: vrijwel zeker verkocht
    median_days_gone: Optional[float]
    quick_share: Optional[float]  # deel van de verdwenen dat binnen QUICK_DAYS weg was
    median_ask: Optional[float]
    quick_price: Optional[float]  # mediaan laatste prijs van snel verdwenen advertenties
    dropped_share: Optional[float]  # deel dat ooit in prijs zakte

    @property
    def factor(self) -> Optional[float]:
        if self.quick_price is None or not self.median_ask:
            return None
        return self.quick_price / self.median_ask


@dataclass
class Patterns:
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    total: int = 0
    gone: int = 0
    gone_reserved: int = 0
    models: list = field(default_factory=list)  # ModelPattern, meest geziene eerst
    measured_factor: Optional[float] = None
    measured_n: int = 0
    monthly: dict = field(default_factory=dict)  # model -> {JJJJ-MM: (mediaan vraag, n)}
    months: list = field(default_factory=list)
    weekday_new: list = field(default_factory=list)  # (weekdag, gemiddeld nieuw per dag, dagen)
    flip_days: Optional[float] = None  # mediaan dagen online van verdwenen flips
    other_days: Optional[float] = None
    flip_n: int = 0

    @property
    def days_of_data(self) -> int:
        if not self.since or not self.until:
            return 0
        return (self.until - self.since).days


def _time(value) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def load_seen(db_path, config: Optional[dict] = None) -> list[Seen]:
    """Alle computers (geen accessoires) die ooit in de categorie gezien zijn,
    ook de verdwenen."""
    if not db_path or not Path(db_path).exists():
        return []
    catalog = pc._default_catalog()
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        # Alleen-lezen migreert niet; een database van vóór migratie 9 heeft
        # reserved_at nog niet.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(listing)")}
        reserved = "l.reserved_at" if "reserved_at" in columns else "NULL"
        rows = conn.execute(
            "SELECT l.item_id, l.title, l.description, l.url, l.first_seen, l.last_seen, l.disappeared_at, "
            f"l.days_online, l.price_eur, {reserved}, "
            "(SELECT p.price_eur FROM listing_price p WHERE p.item_id = l.item_id "
            " ORDER BY p.observed_at LIMIT 1) AS first_price "
            "FROM listing l WHERE l.url LIKE ?",
            ("%/fietsaccessoires-fietscomputers/%",),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    seen = []
    for item_id, title, description, url, first, last, gone_at, days, price, reserved_at, first_price in rows:
        verdict = pc.classify_title(title, catalog)
        if verdict is None or verdict.kind != "computer" or pc.WITHOUT_DEVICE_RE.search(description or ""):
            continue
        first_t, last_t = _time(first), _time(last)
        if first_t is None or last_t is None:
            continue
        seen.append(Seen(item_id, verdict.model.label, first_t, last_t, gone_at is not None, days,
                         first_price if first_price is not None else price, price, reserved_at is not None))
    return seen


def compute(seen: list[Seen], config: Optional[dict] = None) -> Patterns:
    config = config or pc.default_config()
    flip = config["flip"]
    p = Patterns()
    if not seen:
        return p
    p.since = min(s.first_seen for s in seen)
    p.until = max(s.last_seen for s in seen)
    p.total, p.gone = len(seen), sum(s.gone for s in seen)
    p.gone_reserved = sum(s.gone and s.reserved for s in seen)

    by_model: dict[str, list[Seen]] = {}
    for s in seen:
        by_model.setdefault(s.model, []).append(s)

    ratios = []
    flip_days, other_days = [], []
    for model, items in by_model.items():
        asks = [s.first_price for s in items if s.first_price]
        median_ask = statistics.median(asks) if asks else None
        gone = [s for s in items if s.gone and s.days_online is not None]
        quick = [s for s in gone if s.days_online <= QUICK_DAYS and s.last_price]
        priced = [s for s in items if s.first_price and s.last_price]
        mp_ = ModelPattern(
            model=model,
            seen=len(items),
            gone=len(gone),
            gone_reserved=sum(s.reserved for s in gone),
            median_days_gone=statistics.median(s.days_online for s in gone) if len(gone) >= MIN_PER_MODEL else None,
            quick_share=len(quick) / len(gone) if len(gone) >= MIN_PER_MODEL else None,
            median_ask=median_ask,
            quick_price=statistics.median(s.last_price for s in quick) if len(quick) >= MIN_PER_MODEL else None,
            dropped_share=(sum(s.last_price < s.first_price for s in priced) / len(priced)
                           if len(priced) >= MIN_PER_MODEL else None),
        )
        p.models.append(mp_)
        if median_ask:
            ratios += [s.last_price / median_ask for s in quick]
            # Achteraf: was dit bij de eerste waarneming een flip (volgens de
            # mediaan over de hele periode — een benadering, want toen was de
            # mediaan misschien anders)?
            threshold = median_ask * flip["negotiation_factor"] - flip.get("costs_eur", 0.0)
            for s in gone:
                if s.first_price:
                    (flip_days if s.first_price < threshold else other_days).append(s.days_online)
    p.models.sort(key=lambda m: (-m.seen, m.model))

    if len(ratios) >= MIN_FOR_FACTOR:
        p.measured_factor, p.measured_n = statistics.median(ratios), len(ratios)
    else:
        p.measured_n = len(ratios)
    if flip_days:
        p.flip_days, p.flip_n = statistics.median(flip_days), len(flip_days)
    if other_days:
        p.other_days = statistics.median(other_days)

    monthly: dict[str, dict[str, list]] = {}
    for s in seen:
        if s.first_price:
            monthly.setdefault(s.model, {}).setdefault(s.first_seen.strftime("%Y-%m"), []).append(s.first_price)
    p.months = sorted({m for months in monthly.values() for m in months})[-6:]
    p.monthly = {
        model: {m: (statistics.median(v), len(v)) for m, v in months.items() if m in p.months}
        for model, months in monthly.items()
    }

    # Nieuw per weekdag. De eerste dag telt niet: dan vindt de crawl alles
    # wat er al stond, niet wat die dag nieuw was.
    first_day = p.since.date()
    per_day: dict[date, int] = {}
    for s in seen:
        day = s.first_seen.date()
        if day != first_day:
            per_day[day] = per_day.get(day, 0) + 1
    crawl_days = [first_day + timedelta(days=i) for i in range(1, (p.until.date() - first_day).days + 1)]
    for weekday in range(7):
        days = [d for d in crawl_days if d.weekday() == weekday]
        if days:
            p.weekday_new.append((WEEKDAYS[weekday], sum(per_day.get(d, 0) for d in days) / len(days), len(days)))
    return p


def load_patterns(db_path, config: Optional[dict] = None) -> Patterns:
    return compute(load_seen(db_path, config), config)
