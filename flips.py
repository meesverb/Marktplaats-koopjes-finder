"""De flippagina (/flips in `python dashboard.py --serve`): elke flip met wat
erin zit, wat hij moet opbrengen en wat er nog moet gebeuren, en bovenaan
wat alles samen heeft opgeleverd.

Een flip is een rij in `trade` (db.py, migratie 7), dezelfde die Mijn flips
in de dashboards toont: een fietscomputer die je via het dashboard kocht is
hier ook een flip. Wat een fiets meer heeft (migratie 17):

- een fase: voorraad → gekocht → opknappen → te koop → verkocht, met wanneer
  elke fase begon (`trade_stage`), zodat je ziet waar geld blijft staan;
- een klussenlijst (`flip_task`): onderdelen (geschat → gekocht met de echte
  prijs → gedaan), klussen (alleen gedaan) en reizen (OV: vol tarief met
  korting vol / 40% / gratis, de pagina rekent het bedrag uit);
- een doelprijs (laag-hoog), een marktcheck op zoekwoorden, uren, specs,
  biedingen die binnenkomen en foto's.

Gereedschap is een investering: het telt niet mee in de kosten van één flip
(dan lijkt die slechter dan hij is), wel in het netto resultaat bovenaan.

Rekenregels:
- uitgegeven = inkoop + inkoopkosten + wat onderdelen, klussen en reizen van
  deze flip echt kostten (investeringen niet);
- nog gepland = de schatting van onderdelen die nog geen echte prijs hebben;
- verwachte winst = doelprijs − uitgegeven − nog gepland (bij laag en hoog);
- na verkoop: verkoopprijs − verkoopkosten − uitgegeven. Een geschat onderdeel
  dat nooit gekocht is telt dan niet mee.

Eigen aan- en verkopen zijn nooit een vergelijkingsprijs (zie trades.py), en
hier wordt niets geboden of gereageerd: de biedingen zijn die van kopers op
jóuw advertentie, die je zelf overtypt.

    python flips.py                      # het overzicht in de console
    python flips.py import lijst.json    # flips en klussen inlezen (zie flips_import/)
    python flips.py bijwerken aanbod.json   # bestaande klussen: andere winkel, link, prijs
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import db
import trades as tr

HERE = Path(__file__).resolve().parent
PHOTO_DIR = HERE / "flip_fotos"

# Fasen in volgorde. "voorraad": iets dat je hebt (twee paar SPD-pedalen,
# wielen) maar nog niet besloten hebt te verkopen; het telt niet als flip
# tot je het naar "te koop" zet.
STAGES = (
    ("voorraad", "op voorraad"),
    ("gekocht", "gekocht"),
    ("opknappen", "opknappen"),
    ("te_koop", "te koop"),
    ("verkocht", "verkocht"),
)
STAGE_LABELS = dict(STAGES)

# trade.market voor wat bij geen dashboard hoort (markets.py kent alleen
# fietscomputers en sporthorloges). _with_trades() in dashboard.py laat
# deze weg uit Mijn flips, anders stond een fiets tussen de computers.
OWN_MARKETS = {"fietsen": "fiets", "spullen": "spullen"}
MARKET_LABELS = {"fietscomputers": "fietscomputer", "sporthorloges": "sporthorloge", **OWN_MARKETS}

KINDS = ("onderdeel", "klus", "reis")
# OV: wat je betaalt als deel van het volle tarief. 40% korting (daluren
# met een kortingsabonnement), gratis (weekendabonnement).
DISCOUNTS = {"vol": 1.0, "40": 0.6, "gratis": 0.0}
DISCOUNT_LABELS = {"vol": "vol tarief", "40": "40% korting", "gratis": "gratis"}
SOURCES = {"gecontroleerd": "prijs gecontroleerd", "schatting": "schatting"}

# Gratis verzending vanaf dit bedrag per bestelling, per winkel (kleine
# letters, zonder spaties). Uit de boodschappenlijst van 29-09-2026:
# FuturumShop (futurumshop.nl, verzendkostenpagina) en AliExpress Choice
# (droidapp.nl). Verandert een winkel dat, pas het hier aan.
FREE_SHIPPING_FROM = {"futurumshop": 49.0, "aliexpress": 10.0}

# Velden die de pagina en de Sheet mogen wijzigen; al het andere is niet
# van buiten te zetten.
TASK_FIELDS = {"title": str, "shop": str, "url": str, "est_eur": float, "price_eur": float,
               "price_source": str, "investment": bool, "fare_eur": float, "discount": str,
               "bought_at": str, "done_at": str, "notes": str, "kind": str}
FLIP_FIELDS = {"stage": str, "target_low_eur": float, "target_high_eur": float, "hours": float,
               "specs_json": str, "sale_url": str, "comp_words": str}

# Het specs-kaartje, in deze volgorde; ook de basis voor de advertentietekst.
SPEC_FIELDS = (
    ("merk", "Merk en model"), ("jaar", "Bouwjaar"), ("maat", "Framemaat"), ("materiaal", "Frame"),
    ("groep", "Groep"), ("wielen", "Wielen"), ("banden", "Banden"), ("km", "Kilometers"),
    ("extra", "Verder"),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _date(value: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


@dataclass
class Task:
    id: int
    trade_id: Optional[int]
    kind: str
    title: str
    shop: str = ""
    url: str = ""
    est_eur: Optional[float] = None
    price_eur: Optional[float] = None
    price_source: str = ""
    investment: bool = False
    fare_eur: Optional[float] = None
    discount: str = "vol"
    bought_at: str = ""
    done_at: str = ""
    position: int = 0
    notes: str = ""
    updated_at: str = ""

    @property
    def cost_eur(self) -> Optional[float]:
        """Wat het echt kostte; None zolang er alleen een schatting is."""
        if self.kind == "reis":
            if self.fare_eur is None:
                return None
            return round(self.fare_eur * DISCOUNTS.get(self.discount or "vol", 1.0), 2)
        return self.price_eur

    @property
    def planned_eur(self) -> float:
        """De schatting die nog meetelt: alleen zolang er geen echte prijs is."""
        if self.cost_eur is not None or self.est_eur is None:
            return 0.0
        return self.est_eur

    @property
    def done(self) -> bool:
        return bool(self.done_at)

    @property
    def bought(self) -> bool:
        return self.cost_eur is not None or bool(self.bought_at)

    @property
    def status(self) -> str:
        if self.done:
            return "gedaan"
        if self.kind == "onderdeel" and self.bought:
            return "gekocht"
        return "open"

    @property
    def shop_key(self) -> str:
        return "".join((self.shop or "").lower().split())


@dataclass
class Flip:
    trade: tr.Trade
    stage: str = ""
    target_low_eur: Optional[float] = None
    target_high_eur: Optional[float] = None
    hours: Optional[float] = None
    specs: dict = field(default_factory=dict)
    sale_url: str = ""
    comp_words: str = ""
    updated_at: str = ""
    tasks: list = field(default_factory=list)  # Task, zonder investeringen
    tools: list = field(default_factory=list)  # Task met investment, voor deze flip gekocht
    bids: list = field(default_factory=list)  # dict(id, amount_eur, at, note), nieuwste eerst
    photos: list = field(default_factory=list)  # dict(id, file, kind, added_at)
    stage_since: str = ""
    market_check: Optional["MarketCheck"] = None
    # Weergaven en likes van jouw advertentie (views.py, listing_stats), oudste
    # eerst: dict(observed_at, views, favorites, ...). Leeg zonder advertentielink.
    views: list = field(default_factory=list)

    @property
    def id(self) -> int:
        return self.trade.id

    @property
    def sold(self) -> bool:
        return self.trade.sold

    @property
    def kind_label(self) -> str:
        return MARKET_LABELS.get(self.trade.market or "", "fietscomputer")

    @property
    def spent_eur(self) -> float:
        extra = sum(t.cost_eur for t in self.tasks if t.cost_eur is not None)
        return round(self.trade.cost_basis_eur + extra, 2)

    @property
    def planned_eur(self) -> float:
        if self.sold:
            return 0.0
        return round(sum(t.planned_eur for t in self.tasks), 2)

    @property
    def expected_cost_eur(self) -> float:
        return round(self.spent_eur + self.planned_eur, 2)

    @property
    def target(self) -> tuple[Optional[float], Optional[float]]:
        low = self.target_low_eur if self.target_low_eur is not None else self.trade.expected_resale_eur
        high = self.target_high_eur if self.target_high_eur is not None else low
        if low is not None and high is not None and high < low:
            low, high = high, low
        return low, high

    @property
    def target_mid_eur(self) -> Optional[float]:
        low, high = self.target
        if low is None:
            return None
        return round((low + high) / 2, 2)

    def expected_profit(self, price: Optional[float]) -> Optional[float]:
        if price is None:
            return None
        return round(price - self.expected_cost_eur, 2)

    @property
    def profit_eur(self) -> Optional[float]:
        """Na verkoop: de echte winst, met wat er echt is uitgegeven."""
        if not self.sold:
            return None
        return round(self.trade.sell_price_eur - (self.trade.sell_costs_eur or 0.0) - self.spent_eur, 2)

    @property
    def days_in_stage(self) -> Optional[int]:
        start = _date(self.stage_since or self.trade.bought_at)
        end = _date(self.trade.sold_at) if self.sold else date.today()
        if start is None or end is None:
            return None
        return max(0, (end - start).days)

    @property
    def per_hour_eur(self) -> Optional[float]:
        profit = self.profit_eur if self.sold else self.expected_profit(self.target_mid_eur)
        if profit is None or not self.hours:
            return None
        return round(profit / self.hours, 2)

    @property
    def top_bid(self) -> Optional[dict]:
        return max(self.bids, key=lambda b: b["amount_eur"], default=None)


@dataclass
class MarketCheck:
    words: str
    n: int
    median_eur: Optional[float]
    low_eur: Optional[float]
    high_eur: Optional[float]


@dataclass
class Totals:
    realized_eur: float = 0.0
    sold: int = 0
    revenue_eur: float = 0.0
    stock: int = 0  # flips die nog lopen (zonder voorraad)
    stock_spent_eur: float = 0.0
    stock_expected_eur: Optional[float] = None  # verwachte winst op het midden van de doelprijs
    tools_spent_eur: float = 0.0
    tools_planned_eur: float = 0.0
    hours: float = 0.0
    per_hour_eur: Optional[float] = None
    avg_days: Optional[float] = None

    @property
    def net_eur(self) -> float:
        return round(self.realized_eur - self.tools_spent_eur, 2)


@dataclass
class FlipBook:
    flips: list  # Flip, alle, ook voorraad
    tools: list  # Task: alle investeringen, ook die bij een flip horen
    totals: Totals

    def by_stage(self, stage: str) -> list:
        return [f for f in self.flips if f.stage == stage]

    def get(self, trade_id: int) -> Optional[Flip]:
        return next((f for f in self.flips if f.id == trade_id), None)


# --- Lezen -----------------------------------------------------------------------


def _tables(conn) -> set:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _open_readonly(db_path) -> Optional[sqlite3.Connection]:
    if not Path(db_path).exists():
        return None
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def task_from_row(row) -> Task:
    d = dict(row)
    return Task(
        id=d["id"], trade_id=d["trade_id"], kind=d["kind"], title=d["title"], shop=d["shop"] or "",
        url=d["url"] or "", est_eur=d["est_eur"], price_eur=d["price_eur"], price_source=d["price_source"] or "",
        investment=bool(d["investment"]), fare_eur=d["fare_eur"], discount=d["discount"] or "vol",
        bought_at=d["bought_at"] or "", done_at=d["done_at"] or "", position=d["position"] or 0,
        notes=d["notes"] or "", updated_at=d["updated_at"] or "",
    )


def derived_stage(trade: tr.Trade, stored: Optional[str]) -> str:
    if trade.sold:
        return "verkocht"
    if stored and stored in STAGE_LABELS and stored != "verkocht":
        return stored
    return "te_koop" if (trade.market or "") not in OWN_MARKETS else "gekocht"


def sale_item_id(url: str) -> Optional[str]:
    """Het advertentienummer (m1234567890) uit de link naar jouw advertentie."""
    import re
    found = re.search(r"/(m\d{6,})", url or "")
    return found.group(1) if found else None


def load_book(db_path, with_market_check: bool = True) -> FlipBook:
    """Alles voor /flips. Alleen lezen; een database van vóór migratie 17
    geeft de trades zonder klussen."""
    trades = tr.load_trades(db_path)
    conn = _open_readonly(db_path)
    extra, tasks, bids, photos, stages, stats = {}, [], [], [], {}, {}
    try:
        if conn is not None and "flip" in _tables(conn):
            extra = {r["trade_id"]: dict(r) for r in conn.execute("SELECT * FROM flip")}
            tasks = [task_from_row(r) for r in conn.execute(
                "SELECT * FROM flip_task WHERE deleted_at IS NULL ORDER BY position, id")]
            bids = [dict(r) for r in conn.execute("SELECT * FROM flip_bid ORDER BY at DESC, id DESC")]
            photos = [dict(r) for r in conn.execute("SELECT * FROM flip_photo ORDER BY id")]
            for r in conn.execute("SELECT trade_id, stage, at FROM trade_stage ORDER BY at, id"):
                stages.setdefault(r["trade_id"], []).append((r["stage"], r["at"]))
            stats = db.list_stats(conn)
    finally:
        if conn is not None:
            conn.close()

    flips = []
    for t in trades:
        x = extra.get(t.id, {})
        try:
            specs = json.loads(x.get("specs_json") or "{}")
        except ValueError:
            specs = {}
        stage = derived_stage(t, x.get("stage"))
        since = next((at for s, at in reversed(stages.get(t.id, [])) if s == stage), "")
        if stage == "verkocht":
            since = t.sold_at or since
        f = Flip(trade=t, stage=stage, target_low_eur=x.get("target_low_eur"),
                 target_high_eur=x.get("target_high_eur"), hours=x.get("hours"), specs=specs,
                 sale_url=x.get("sale_url") or "", comp_words=x.get("comp_words") or "",
                 updated_at=x.get("updated_at") or "", stage_since=since)
        f.tasks = [k for k in tasks if k.trade_id == t.id and not k.investment]
        f.tools = [k for k in tasks if k.trade_id == t.id and k.investment]
        f.bids = [b for b in bids if b["trade_id"] == t.id]
        f.photos = [p for p in photos if p["trade_id"] == t.id]
        f.views = stats.get(sale_item_id(f.sale_url) or "", [])
        flips.append(f)
    if with_market_check:
        own = {t.item_id for t in trades if t.item_id}
        for f in flips:
            if f.comp_words:
                f.market_check = market_check(db_path, f.comp_words, exclude=own)
    tools = [k for k in tasks if k.investment]
    return FlipBook(flips, tools, totals(flips, tools))


def totals(flips: list, tools: list) -> Totals:
    t = Totals()
    sold = [f for f in flips if f.sold]
    running = [f for f in flips if not f.sold and f.stage != "voorraad"]
    t.sold, t.stock = len(sold), len(running)
    t.realized_eur = round(sum(f.profit_eur for f in sold), 2)
    t.revenue_eur = round(sum(f.trade.sell_price_eur for f in sold), 2)
    t.stock_spent_eur = round(sum(f.spent_eur for f in running), 2)
    expected = [f.expected_profit(f.target_mid_eur) for f in running]
    known = [e for e in expected if e is not None]
    t.stock_expected_eur = round(sum(known), 2) if known else None
    t.tools_spent_eur = round(sum(k.cost_eur for k in tools if k.cost_eur is not None), 2)
    t.tools_planned_eur = round(sum(k.planned_eur for k in tools), 2)
    t.hours = round(sum(f.hours or 0 for f in flips), 2)
    sold_hours = sum(f.hours or 0 for f in sold)
    if sold_hours:
        t.per_hour_eur = round(sum(f.profit_eur for f in sold if f.hours) / sold_hours, 2)
    days = [f.trade.days_held() for f in sold if f.trade.days_held() is not None]
    t.avg_days = round(statistics.mean(days), 1) if days else None
    return t


def market_check(db_path, words: str, exclude=frozenset(), days: int = 180) -> Optional[MarketCheck]:
    """De vraagprijzen van advertenties met al deze woorden in titel of
    tekst, gezien in de laatste `days` dagen. Vraagprijzen, geen
    verkoopprijzen: een richting naast je eigen doelprijs, niet meer.
    Biedadvertenties zonder vraagprijs tellen niet mee (die prijs loopt op)."""
    terms = [w.lower() for w in words.split() if w.strip()]
    conn = _open_readonly(db_path)
    if conn is None or not terms:
        return None
    try:
        if "listing" not in _tables(conn):
            return None
        columns = {r[1] for r in conn.execute("PRAGMA table_info(listing)")}
        asking = ("(price_is_asking = 1 OR (price_is_asking IS NULL AND is_bid = 0))"
                  if "price_is_asking" in columns else "is_bid = 0")
        where = " AND ".join("instr(lower(coalesce(title, '') || ' ' || coalesce(description, '')), ?) > 0"
                             for _ in terms)
        rows = conn.execute(
            f"SELECT item_id, price_eur FROM listing WHERE price_eur IS NOT NULL AND price_eur > 0 AND {asking} "
            f"AND last_seen >= date('now', ?) AND {where}",
            (f"-{int(days)} day", *terms)).fetchall()
    finally:
        conn.close()
    prices = sorted(r["price_eur"] for r in rows if r["item_id"] not in exclude)
    if not prices:
        return MarketCheck(words, 0, None, None, None)
    q = statistics.quantiles(prices, n=4) if len(prices) >= 4 else [prices[0], None, prices[-1]]
    return MarketCheck(words, len(prices), round(statistics.median(prices), 2), q[0], q[-1])


def basket(tasks: list) -> list:
    """De onderdelen die nog gekocht moeten worden, per winkel:
    [(winkel, [Task], subtotaal, tekort tot gratis verzending of None)]."""
    shops: dict = {}
    for t in tasks:
        if t.kind != "onderdeel" or t.bought or t.done:
            continue
        shops.setdefault(t.shop or "winkel onbekend", []).append(t)
    out = []
    for shop, items in shops.items():
        subtotal = round(sum(t.est_eur or 0 for t in items), 2)
        threshold = FREE_SHIPPING_FROM.get("".join(shop.lower().split()))
        short = round(threshold - subtotal, 2) if threshold is not None and subtotal < threshold else None
        out.append((shop, items, subtotal, short))
    return sorted(out, key=lambda x: -x[2])


def ad_draft(f: Flip) -> str:
    """Een begin voor je verkoopadvertentie, alleen uit wat je zelf invulde:
    de specs en de onderdelen die gemonteerd zijn. Je plaatst hem zelf."""
    s = f.specs
    head = s.get("merk") or f.trade.title
    lines = [f"Te koop: {head}" + (f", maat {s['maat']}" if s.get("maat") else "") + "."]
    for key, label in SPEC_FIELDS:
        if key in ("merk", "maat", "extra") or not s.get(key):
            continue
        lines.append(f"- {label}: {s[key]}")
    new = [t.title for t in f.tasks if t.kind == "onderdeel" and t.done]
    if new:
        lines.append("")
        lines.append("Onlangs vervangen: " + ", ".join(new) + ".")
    if s.get("extra"):
        lines.append("")
        lines.append(s["extra"])
    lines.append("")
    lines.append("Ophalen, proefrit kan.")
    return "\n".join(lines)


# --- Schrijven -------------------------------------------------------------------


def _flip_row(conn, trade_id: int) -> None:
    conn.execute("INSERT OR IGNORE INTO flip (trade_id, updated_at) VALUES (?, ?)", (trade_id, now_iso()))


def create_flip(conn, *, title: str, market: str, bought_at: str, buy_price_eur: float,
                buy_costs_eur: float = 0.0, url: Optional[str] = None, item_id: Optional[str] = None,
                stage: str = "gekocht", target_low_eur: Optional[float] = None,
                target_high_eur: Optional[float] = None, comp_words: str = "", specs: Optional[dict] = None,
                notes: str = "") -> int:
    if stage not in STAGE_LABELS or stage == "verkocht":
        raise ValueError(f"onbekende fase {stage!r}")
    trade_id = db.add_trade(conn, title=title, bought_at=bought_at, buy_price_eur=buy_price_eur,
                            buy_costs_eur=buy_costs_eur, url=url, item_id=item_id, notes=notes, market=market)
    conn.execute(
        "INSERT INTO flip (trade_id, stage, target_low_eur, target_high_eur, specs_json, comp_words, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (trade_id, stage, target_low_eur, target_high_eur, json.dumps(specs or {}, ensure_ascii=False),
         comp_words, now_iso()))
    conn.execute("INSERT INTO trade_stage (trade_id, stage, at) VALUES (?, ?, ?)",
                 (trade_id, stage, bought_at if stage in ("gekocht", "voorraad") else now_iso()))
    conn.commit()
    return trade_id


def _trade_exists(conn, trade_id: int) -> bool:
    return conn.execute("SELECT 1 FROM trade WHERE id = ?", (trade_id,)).fetchone() is not None


def set_stage(conn, trade_id: int, stage: str) -> bool:
    """Naar een andere fase (niet verkocht: dat gaat met sell(), want daar
    hoort een prijs bij). Terug uit verkocht haalt de verkoop weg."""
    if stage not in STAGE_LABELS or stage == "verkocht" or not _trade_exists(conn, trade_id):
        return False
    db.unsell_trade(conn, trade_id)
    _flip_row(conn, trade_id)
    conn.execute("UPDATE flip SET stage = ?, updated_at = ? WHERE trade_id = ?", (stage, now_iso(), trade_id))
    conn.execute("INSERT INTO trade_stage (trade_id, stage, at) VALUES (?, ?, ?)", (trade_id, stage, now_iso()))
    conn.commit()
    return True


def sell(conn, trade_id: int, *, sold_at: str, price_eur: float, costs_eur: float = 0.0, via: str = "") -> bool:
    if not db.sell_trade(conn, trade_id, sold_at=sold_at, sell_price_eur=price_eur, sell_costs_eur=costs_eur,
                         sold_via=via):
        return False
    _flip_row(conn, trade_id)
    conn.execute("UPDATE flip SET stage = 'verkocht', updated_at = ? WHERE trade_id = ?", (now_iso(), trade_id))
    conn.execute("INSERT INTO trade_stage (trade_id, stage, at) VALUES (?, 'verkocht', ?)", (trade_id, sold_at))
    conn.commit()
    return True


def _coerce(kind, value):
    if value is None or value == "":
        return None
    if kind is bool:
        return 1 if value in (True, 1, "1", "true", "ja", "on") else 0
    if kind is float:
        return round(float(value), 2)
    return str(value).strip()


def update_flip(conn, trade_id: int, updated_at: Optional[str] = None, **values) -> bool:
    """Doelprijs, uren, specs, verkooplink, zoekwoorden. Fase via set_stage()."""
    if not _trade_exists(conn, trade_id):
        return False
    unknown = set(values) - set(FLIP_FIELDS) - {"title", "buy_price_eur", "buy_costs_eur", "notes"}
    if unknown or "stage" in values:
        raise ValueError(f"onbekende velden: {sorted(unknown | ({'stage'} & set(values)))}")
    _flip_row(conn, trade_id)
    own = {k: _coerce(FLIP_FIELDS[k], v) for k, v in values.items() if k in FLIP_FIELDS}
    if own:
        sets = ", ".join(f"{k} = ?" for k in own)
        conn.execute(f"UPDATE flip SET {sets}, updated_at = ? WHERE trade_id = ?",
                     (*own.values(), updated_at or now_iso(), trade_id))
    base = {k: v for k, v in values.items() if k in ("title", "buy_price_eur", "buy_costs_eur", "notes")}
    for k, v in base.items():
        value = _coerce(float, v) if k.endswith("_eur") else (v or "").strip()
        if k == "title" and not value:
            continue
        conn.execute(f"UPDATE trade SET {k} = ? WHERE id = ?", (value if value is not None else 0.0, trade_id))
    if base:
        conn.execute("UPDATE flip SET updated_at = ? WHERE trade_id = ?", (updated_at or now_iso(), trade_id))
    conn.commit()
    return True


def add_task(conn, trade_id: Optional[int], *, kind: str, title: str, updated_at: Optional[str] = None,
             **values) -> int:
    if kind not in KINDS:
        raise ValueError(f"onbekende soort {kind!r}")
    if not title.strip():
        raise ValueError("een klus heeft een naam nodig")
    if trade_id is not None and not _trade_exists(conn, trade_id):
        raise ValueError("onbekende flip")
    unknown = set(values) - set(TASK_FIELDS)
    if unknown:
        raise ValueError(f"onbekende velden: {sorted(unknown)}")
    clean = {k: _coerce(TASK_FIELDS[k], v) for k, v in values.items()}
    if clean.get("discount") is not None and clean["discount"] not in DISCOUNTS:
        raise ValueError(f"onbekende korting {clean['discount']!r}")
    position = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM flip_task WHERE trade_id IS ?",
                            (trade_id,)).fetchone()[0]
    cols = ["trade_id", "kind", "title", "position", "updated_at", *clean]
    cur = conn.execute(
        f"INSERT INTO flip_task ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        (trade_id, kind, title.strip(), position, updated_at or now_iso(), *clean.values()))
    conn.commit()
    return cur.lastrowid


def update_task(conn, task_id: int, updated_at: Optional[str] = None, **values) -> bool:
    """Eén of meer velden. Een echte prijs invullen zet hem op gekocht
    (vandaag), tenzij er al een datum stond."""
    unknown = set(values) - set(TASK_FIELDS)
    if unknown:
        raise ValueError(f"onbekende velden: {sorted(unknown)}")
    clean = {k: _coerce(TASK_FIELDS[k], v) for k, v in values.items()}
    if "kind" in clean and clean["kind"] not in KINDS:
        raise ValueError(f"onbekende soort {clean['kind']!r}")
    if clean.get("discount") is not None and clean["discount"] not in DISCOUNTS:
        raise ValueError(f"onbekende korting {clean['discount']!r}")
    if "title" in clean and not clean["title"]:
        raise ValueError("een klus heeft een naam nodig")
    row = conn.execute("SELECT bought_at FROM flip_task WHERE id = ? AND deleted_at IS NULL", (task_id,)).fetchone()
    if row is None:
        return False
    if clean.get("price_eur") is not None and not row[0] and "bought_at" not in clean:
        clean["bought_at"] = date.today().isoformat()
    if not clean:
        return True
    sets = ", ".join(f"{k} = ?" for k in clean)
    conn.execute(f"UPDATE flip_task SET {sets}, updated_at = ? WHERE id = ?",
                 (*clean.values(), updated_at or now_iso(), task_id))
    conn.commit()
    return True


def delete_task(conn, task_id: int) -> bool:
    cur = conn.execute("UPDATE flip_task SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                       (now_iso(), now_iso(), task_id))
    conn.commit()
    return cur.rowcount > 0


def task_trade(conn, task_id: int) -> Optional[int]:
    row = conn.execute("SELECT trade_id FROM flip_task WHERE id = ?", (task_id,)).fetchone()
    return row[0] if row else None


def add_bid(conn, trade_id: int, amount_eur: float, note: str = "", at: Optional[str] = None) -> int:
    if not _trade_exists(conn, trade_id):
        raise ValueError("onbekende flip")
    cur = conn.execute("INSERT INTO flip_bid (trade_id, amount_eur, at, note) VALUES (?, ?, ?, ?)",
                       (trade_id, round(amount_eur, 2), at or now_iso(), note.strip()))
    conn.commit()
    return cur.lastrowid


def delete_bid(conn, bid_id: int) -> Optional[int]:
    row = conn.execute("SELECT trade_id FROM flip_bid WHERE id = ?", (bid_id,)).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM flip_bid WHERE id = ?", (bid_id,))
    conn.commit()
    return row[0]


PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic"}
MAX_PHOTO_BYTES = 15_000_000


def add_photo(conn, trade_id: int, data: bytes, content_type: str, kind: str = "voor",
              photo_dir: Path = PHOTO_DIR) -> int:
    """Bewaart de foto in flip_fotos/<flip>/ (niet in git, niet in de
    database: foto's zijn megabytes) en onthoudt hem in `flip_photo`."""
    if not _trade_exists(conn, trade_id):
        raise ValueError("onbekende flip")
    ext = PHOTO_TYPES.get(content_type.split(";")[0].strip().lower())
    if ext is None:
        raise ValueError("alleen jpg, png, webp of heic")
    if not data or len(data) > MAX_PHOTO_BYTES:
        raise ValueError("de foto is leeg of groter dan 15 MB")
    kind = kind if kind in ("voor", "na") else "voor"
    folder = Path(photo_dir) / str(int(trade_id))
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    name = f"{kind}-{stamp}{ext}"
    (folder / name).write_bytes(data)
    cur = conn.execute("INSERT INTO flip_photo (trade_id, file, kind, added_at) VALUES (?, ?, ?, ?)",
                       (trade_id, f"{int(trade_id)}/{name}", kind, now_iso()))
    conn.commit()
    return cur.lastrowid


def delete_photo(conn, photo_id: int, photo_dir: Path = PHOTO_DIR) -> Optional[int]:
    row = conn.execute("SELECT trade_id, file FROM flip_photo WHERE id = ?", (photo_id,)).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM flip_photo WHERE id = ?", (photo_id,))
    conn.commit()
    try:
        (Path(photo_dir) / row[1]).unlink()
    except OSError:
        pass
    return row[0]


def photo_path(conn_or_path, photo_id: int, photo_dir: Path = PHOTO_DIR) -> Optional[tuple[Path, str]]:
    """(bestand, content-type) van een foto, of None. Alleen bestanden die
    in `flip_photo` staan: de naam komt nooit uit de URL."""
    conn = _open_readonly(conn_or_path)
    if conn is None:
        return None
    try:
        if "flip_photo" not in _tables(conn):
            return None
        row = conn.execute("SELECT file FROM flip_photo WHERE id = ?", (photo_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    path = Path(photo_dir) / row["file"]
    types = {v: k for k, v in PHOTO_TYPES.items()}
    return path, types.get(path.suffix.lower(), "application/octet-stream")


# --- Inlezen uit een bestand -----------------------------------------------------

# Nederlandse sleutels in het bestand (de eigenaar schrijft het), Engelse
# kolommen in de database.
IMPORT_TASK_KEYS = {"soort": "kind", "titel": "title", "winkel": "shop", "url": "url", "geschat": "est_eur",
                    "prijs": "price_eur", "bron": "price_source", "investering": "investment",
                    "tarief": "fare_eur", "korting": "discount", "gekocht_op": "bought_at",
                    "gedaan_op": "done_at", "notitie": "notes"}


def _task_values(item: dict) -> tuple[str, str, dict]:
    unknown = set(item) - set(IMPORT_TASK_KEYS)
    if unknown:
        raise ValueError(f"onbekende sleutels in klus {item.get('titel')!r}: {sorted(unknown)}")
    values = {IMPORT_TASK_KEYS[k]: v for k, v in item.items()}
    return values.pop("kind", "onderdeel"), values.pop("title", ""), values


def import_file(conn, path) -> list[str]:
    """Flips, hun klussen en losse investeringen uit een JSON-bestand (zie
    flips_import/cube_peloton_pro.json). Een flip met dezelfde titel of
    link die er al is wordt overgeslagen, net als een investering met
    dezelfde naam: twee keer inlezen dubbelt niets."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    done = []
    existing = {(r["title"], r["url"]) for r in db.list_trades(conn)}
    titles = {t for t, _ in existing}
    urls = {u for _, u in existing if u}
    for item in data.get("flips", []):
        if item["titel"] in titles or (item.get("url") and item["url"] in urls):
            done.append(f"overgeslagen (staat er al): {item['titel']}")
            continue
        trade_id = create_flip(
            conn, title=item["titel"], market=item.get("markt", "fietsen"), bought_at=item["gekocht_op"],
            buy_price_eur=float(item["prijs"]), buy_costs_eur=float(item.get("kosten", 0.0)),
            url=item.get("url"), item_id=item.get("advertentie"), stage=item.get("fase", "gekocht"),
            target_low_eur=item.get("doel_laag"), target_high_eur=item.get("doel_hoog"),
            comp_words=item.get("zoekwoorden", ""), specs=item.get("specs"), notes=item.get("notitie", ""))
        for task in item.get("klussen", []):
            kind, title, values = _task_values(task)
            add_task(conn, trade_id, kind=kind, title=title, **values)
        done.append(f"ingelezen: {item['titel']} ({len(item.get('klussen', []))} klussen)")
    have = {r[0] for r in conn.execute(
        "SELECT title FROM flip_task WHERE trade_id IS NULL AND deleted_at IS NULL")}
    for task in data.get("investeringen", []):
        kind, title, values = _task_values(task)
        if title in have:
            continue
        values["investment"] = True
        add_task(conn, None, kind=kind, title=title, **values)
        done.append(f"investering: {title}")
    return done


UPDATE_KEYS = {"titel", "winkel", "url", "geschat", "bron", "notitie"}


def update_file(conn, path) -> list[str]:
    """Bestaande klussen bijwerken met een beter aanbod: winkel, link,
    geschatte prijs, bron, notitie (zie flips_import/cube_bike24.json).
    import_file() kan dat niet: die slaat een flip over die er al is.

    Een regel wordt gevonden aan zijn titel, binnen de flip met de titel
    onder "flip" (of bij "investeringen" onder de losse investeringen). Wat
    al gekocht is (een echte prijs) blijft staan: dan is het aanbod te laat.
    Wat niet gevonden wordt, zegt de uitvoer; er komt niets bij."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    trades = {r["title"]: r["id"] for r in db.list_trades(conn)}
    done = []

    def apply(trade_id: Optional[int], items: list, where: str) -> None:
        rows = conn.execute("SELECT * FROM flip_task WHERE trade_id IS ? AND deleted_at IS NULL", (trade_id,))
        tasks = {r["title"]: task_from_row(r) for r in rows}
        for item in items:
            unknown = set(item) - UPDATE_KEYS
            if unknown:
                raise ValueError(f"onbekende sleutels bij {item.get('titel')!r}: {sorted(unknown)}")
            task = tasks.get(item.get("titel", ""))
            if task is None:
                done.append(f"niet gevonden in {where}: {item.get('titel')!r}")
                continue
            if task.price_eur is not None:
                done.append(f"al gekocht, niet bijgewerkt: {task.title}")
                continue
            values = {IMPORT_TASK_KEYS[k]: v for k, v in item.items() if k != "titel"}
            update_task(conn, task.id, **values)
            done.append(f"bijgewerkt: {task.title}"
                        + (f" → {values['shop']} {euro(values['est_eur'])}" if "est_eur" in values else ""))

    for entry in data.get("flips", []):
        trade_id = trades.get(entry.get("flip", ""))
        if trade_id is None:
            done.append(f"flip niet gevonden: {entry.get('flip')!r}")
            continue
        apply(trade_id, entry.get("klussen", []), entry["flip"])
    if data.get("investeringen"):
        apply(None, data["investeringen"], "investeringen")
    return done


# --- Console ---------------------------------------------------------------------


def euro(amount: Optional[float]) -> str:
    return "—" if amount is None else f"€{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def print_book(book: FlipBook) -> None:
    t = book.totals
    print(f"Verdiend: {euro(t.realized_eur)} op {t.sold} verkocht · investeringen {euro(t.tools_spent_eur)} "
          f"· netto {euro(t.net_eur)}")
    print(f"Lopend: {t.stock} flips, {euro(t.stock_spent_eur)} erin, verwachte winst {euro(t.stock_expected_eur)}")
    for f in book.flips:
        low, high = f.target
        profit = (euro(f.profit_eur) if f.sold else
                  f"{euro(f.expected_profit(low))} – {euro(f.expected_profit(high))} verwacht")
        print(f"  [{STAGE_LABELS[f.stage]}] {f.trade.title}: uitgegeven {euro(f.spent_eur)}, "
              f"gepland {euro(f.planned_eur)}, winst {profit}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Je flips: wat erin zit, wat ze opbrengen, wat er nog moet.")
    parser.add_argument("--db", default="koopjes.db")
    sub = parser.add_subparsers(dest="command")
    imp = sub.add_parser("import", help="flips en klussen inlezen uit een JSON-bestand")
    imp.add_argument("file")
    upd = sub.add_parser("bijwerken", help="bestaande klussen bijwerken (winkel, link, prijs) uit een JSON-bestand")
    upd.add_argument("file")
    args = parser.parse_args(argv)
    if args.command == "bijwerken":
        if not Path(args.db).exists():
            print(f"Database {args.db} bestaat niet.", file=sys.stderr)
            return 1
        conn = db.connect(args.db)
        try:
            for line in update_file(conn, args.file):
                print(line)
        except (ValueError, KeyError) as exc:
            print(f"Niet bijgewerkt: {exc}", file=sys.stderr)
            return 1
        finally:
            conn.close()
        return 0
    if args.command == "import":
        conn = db.connect(args.db)
        try:
            for line in import_file(conn, args.file):
                print(line)
        except (ValueError, KeyError) as exc:
            print(f"Niet ingelezen: {exc}", file=sys.stderr)
            return 1
        finally:
            conn.close()
        return 0
    if not Path(args.db).exists():
        print(f"Database {args.db} bestaat niet.", file=sys.stderr)
        return 1
    print_book(load_book(args.db))
    return 0


if __name__ == "__main__":
    sys.exit(main())
