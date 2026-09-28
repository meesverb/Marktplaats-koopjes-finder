"""Vinted naast Marktplaats: exports van Vinted-zoekresultaten inlezen in
koopjes.db, en per advertentie uitrekenen wat hij op Marktplaats opbrengt.

    python vinted.py import productsList_2026-09-28T14-57-35-028Z.csv ...
    python vinted.py                # per model Vinted tegen Marktplaats, en de flips
    python vinted.py --flips 25

Een export is een CSV die de eigenaar zelf maakt van een zoekopdracht op
Vinted (kolommen "Item Title", "Item Price", "Item Service Fee", ...). Dit
script haalt zelf niets op bij Vinted en reageert nergens op. De tab Vinted in
dashboard.html toont hetzelfde.

Drie regels die niet vanzelf spreken:

- Vinted-prijzen tellen nooit mee als vergelijkingsprijs voor Marktplaats. De
  verwachte verkoopprijs komt alleen uit Marktplaats (db_comparables(), zelfde
  regels als de tab Flips); Vinted staat in een eigen tabel (db.py,
  migratie 8).
- Een advertentie die niet in een nieuwe export staat, is niet verdwenen of
  verkocht: een export is één zoekopdracht, geen volledige crawl. "Actief" is
  alleen: gezien in een export van de laatste `active_days`.
- Wat je betaalt is de vraagprijs plus de kopersbescherming uit de export zelf
  plus verzending (`vinted.shipping_eur` in computer_scoring.json). Afdingen
  kan op Vinted ook, maar dat zit er niet in.
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

import computers as pc
import db

HERE = Path(__file__).resolve().parent
# De database van koopjes.py (naast schedule.json), ongeacht de map waarin je
# het commando typt. De exports staan meestal in Downloads, en "koopjes.db"
# relatief aan die map gaf daar stilletjes een tweede, lege database.
DEFAULT_DB = str(HERE / "koopjes.db")
NOT_AVAILABLE = "Not Available"
REQUIRED_COLUMNS = ("Item Title", "Item Price", "Item Service Fee", "Item Total Price", "Item Currency", "Item URL")
# Alleen een http(s)-adres: de URL komt als link in het dashboard.
ITEM_ID_RE = re.compile(r"^https?://[^\s'\"<>]*/items/(\d+)")
# "productsList_2026-09-28T14-57-35-028Z.csv": het tijdstip van de export, UTC.
EXPORT_TIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})")
NEW_CONDITIONS = ("Nieuw met prijskaartje", "Nieuw zonder prijskaartje")
DEFAULTS = {"shipping_eur": 4.5, "max_price_eur": 1000}

# Vinted zoekt niet binnen een categorie. In de exports van 28-09-2026 (Garmin
# en Wahoo, 867 rijen) stonden ook Wahoo Rival- en Garmin-horloges, Kickr-
# trainers, Speedplay-pedalen, autonavigatie en wielerkleding. De kleding valt
# al af in classify_unknown() (geen fietscomputerwoord), de Kickr ook; de rest
# hier. "Rival" alleen na Elemnt/Element: SRAM Rival is een groepset.
NOT_A_COMPUTER_RE = re.compile(
    r"\b[eé]l[eé]?m[eé]?n?t\s+rival\b|\b(?:forerunner|fenix|vivoactive|venu|instinct|smartwatch|watch|montre|reloj"
    r"|rel[oó]gio|orologio|\w*uhr|\w*horloge|rodillo|rullo|kick\s?core|speedplay|powerlink|p[eé]dal\w*"
    r"|drive\s?smart|gps\s?64\w*|trackr|zaino)\b",
    re.I,
)
# Zonder bekend model: houders, sensoren, accupacks en onderdelen in de talen
# van de export ("Garmin Edge Out-Front", "Sensore cadenza cadence Wahoo",
# "Garmin Edge Battery Pack", "Compteur capteur ceinture Garmin", "Ricambi
# Wahoo"). Met een bekend model beslist computers.classify_title(), dat de
# houderwoorden in die talen ook kent.
ACCESSORY_RE = re.compile(
    r"\b(?:out-?front|sensore|capteur|ceinture|cadenza|batterie|battery|ricambi)\b",
    re.I,
)
# Defect, in de talen die in de export voorkomen ("Wahoo element bolt bloccato").
REPAIR_RE = re.compile(
    r"\b(?:bloccato|defekt\w*|d[eé]fectueux|cass[eé]e?|rotto|averiado|non\s+funziona|ne\s+fonctionne\s+pas"
    r"|pour\s+pi[eè]ces|per\s+ricambi|para\s+piezas)\b",
    re.I,
)
# "Garmin Edge 1030 (senza GPS)" (€149): de doos of houder, niet het apparaat.
WITHOUT_DEVICE_RE = re.compile(
    r"\b(?:senza|sin|sans|ohne|without)\s+(?:(?:il|el|le|la|the)\s+)?(?:gps|computer|compteur|garmin|wahoo)\b",
    re.I,
)


class ExportError(ValueError):
    """Een bestand dat geen Vinted-export is zoals dit script die kent."""


@dataclass
class VintedRow:
    item_id: str
    title: str
    price_eur: float
    fee_eur: Optional[float]
    total_eur: Optional[float]
    brand: str = ""
    size: str = ""
    condition: str = ""
    favorites: Optional[int] = None
    url: str = ""
    image_url: str = ""
    seller_id: str = ""
    is_business: bool = False


# --- Inlezen -----------------------------------------------------------------


def _value(row: dict, key: str) -> str:
    value = (row.get(key) or "").strip()
    return "" if value == NOT_AVAILABLE else value


def _amount(row: dict, key: str, where: str) -> Optional[float]:
    text = _value(row, key)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        raise ExportError(f"{where}: {key}={text!r} is geen bedrag. Is het formaat van de export veranderd?") from None


def read_export(path) -> tuple[list[VintedRow], dict[str, int]]:
    """De advertenties in één export, en per reden hoeveel rijen er zijn
    overgeslagen. Een bestand zonder de verwachte kolommen stopt met een
    melding in plaats van half ingelezen te worden."""
    name = Path(path).name
    with open(path, newline="", encoding=db.CSV_READ_ENCODING) as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ExportError(
                f"{name} is geen Vinted-export zoals dit script die kent: kolom "
                f"{', '.join(repr(c) for c in missing)} ontbreekt."
            )
        rows, skipped = [], {}
        for line, row in enumerate(reader, start=2):
            where = f"{name} regel {line}"
            currency = _value(row, "Item Currency")
            found = ITEM_ID_RE.search(row.get("Item URL") or "")
            price = _amount(row, "Item Price", where)
            reason = ("andere munt dan EUR" if currency and currency != "EUR"
                      else "geen advertentienummer in de URL" if not found
                      else "geen prijs" if price is None else "")
            if reason:
                skipped[reason] = skipped.get(reason, 0) + 1
                continue
            photos = [p.strip() for p in _value(row, "All Photos").split(",")
                      if re.match(r"^https?://[^\s'\"<>]+$", p.strip())]
            favorites = _value(row, "Item Favorites")
            rows.append(VintedRow(
                item_id=found.group(1),
                title=_value(row, "Item Title").replace("\n", " "),
                price_eur=price,
                fee_eur=_amount(row, "Item Service Fee", where),
                total_eur=_amount(row, "Item Total Price", where),
                brand=_value(row, "Item Brand"),
                size=_value(row, "Item Size"),
                condition=_value(row, "Item Status"),
                favorites=int(favorites) if favorites.isdigit() else None,
                url=_value(row, "Item URL"),
                image_url=photos[0] if photos else "",
                seller_id=_value(row, "Seller ID"),
                is_business=_value(row, "Is Business Seller") == "Yes",
            ))
    return rows, skipped


def export_time(path, at: Optional[str] = None) -> str:
    """Wanneer de export gemaakt is: `at`, anders het tijdstip in de
    bestandsnaam, anders de wijzigingstijd van het bestand."""
    if at:
        moment = datetime.fromisoformat(at)
        if moment.tzinfo is None:
            moment = moment.astimezone()
        return moment.astimezone(timezone.utc).isoformat(timespec="seconds")
    found = EXPORT_TIME_RE.search(Path(path).name)
    if found:
        day, hh, mm, ss = found.groups()
        return f"{day}T{hh}:{mm}:{ss}+00:00"
    mtime = datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc)
    return mtime.isoformat(timespec="seconds")


@dataclass
class ImportResult:
    file: str
    exported_at: str
    rows: int = 0
    new: int = 0
    updated: int = 0
    repriced: int = 0
    skipped: dict = field(default_factory=dict)


def import_export(conn: sqlite3.Connection, path, at: Optional[str] = None) -> ImportResult:
    """Eén export in `vinted_listing` en `vinted_price`. Twee keer dezelfde
    export inlezen verandert niets; een oudere export na een nieuwere
    overschrijft de nieuwere prijs en titel niet."""
    rows, skipped = read_export(path)
    when = export_time(path, at)
    result = ImportResult(Path(path).name, when, rows=len(rows), skipped=skipped)
    for r in rows:
        values = {
            "item_id": r.item_id, "title": r.title, "price_eur": r.price_eur, "fee_eur": r.fee_eur,
            "total_eur": r.total_eur, "brand": r.brand, "size": r.size, "condition": r.condition,
            "favorites": r.favorites, "url": r.url, "image_url": r.image_url, "seller_id": r.seller_id,
            "is_business": 1 if r.is_business else 0, "when": when, "file": result.file,
        }
        old = conn.execute(
            "SELECT price_eur, first_exported_at, last_exported_at FROM vinted_listing WHERE item_id = ?",
            (r.item_id,),
        ).fetchone()
        if old is None:
            conn.execute(
                "INSERT INTO vinted_listing (item_id, title, price_eur, fee_eur, total_eur, brand, size, "
                "condition, favorites, url, image_url, seller_id, is_business, first_exported_at, "
                "last_exported_at, export_file) VALUES (:item_id, :title, :price_eur, :fee_eur, :total_eur, "
                ":brand, :size, :condition, :favorites, :url, :image_url, :seller_id, :is_business, :when, "
                ":when, :file)",
                values,
            )
            result.new += 1
        elif when >= old["last_exported_at"]:
            conn.execute(
                "UPDATE vinted_listing SET title = :title, price_eur = :price_eur, fee_eur = :fee_eur, "
                "total_eur = :total_eur, brand = :brand, size = :size, condition = :condition, "
                "favorites = :favorites, url = :url, image_url = COALESCE(NULLIF(:image_url, ''), image_url), "
                "seller_id = :seller_id, is_business = :is_business, last_exported_at = :when, "
                "export_file = :file, first_exported_at = MIN(first_exported_at, :when) WHERE item_id = :item_id",
                values,
            )
            result.updated += 1
            if old["price_eur"] != r.price_eur and when > old["last_exported_at"]:
                result.repriced += 1
        else:
            conn.execute(
                "UPDATE vinted_listing SET first_exported_at = MIN(first_exported_at, :when) WHERE item_id = :item_id",
                values,
            )
            result.updated += 1
        conn.execute(
            "INSERT OR IGNORE INTO vinted_price (item_id, exported_at, price_eur) VALUES (?, ?, ?)",
            (r.item_id, when, r.price_eur),
        )
    conn.commit()
    return result


# --- Indelen en vergelijken ------------------------------------------------------


def settings(config: dict) -> dict:
    return {**DEFAULTS, **config.get("vinted", {})}


def classify(row: VintedRow, catalog: Sequence[pc.ComputerModel], mp_prices: dict,
             config: dict) -> tuple[Optional[pc.ComputerModel], str, str]:
    """(model of None, soort, reden), met dezelfde soorten als het dashboard.
    Eerst wat alleen op Vinted voorkomt, daarna classify_title() en
    classify_unknown() uit computers.py; bij twijfel beslist de prijs tegen de
    Marktplaats-mediaan van het model (computers._resolve_doubt())."""
    for kind, regex, label in (("overig", NOT_A_COMPUTER_RE, "geen fietscomputer"),
                               ("defect", REPAIR_RE, "defect"),
                               ("accessoire", WITHOUT_DEVICE_RE, "zonder het apparaat")):
        found = regex.search(row.title)
        if found:
            return None, kind, f"{label} ('{found.group(0)}')"
    limit = settings(config)["max_price_eur"]
    if row.price_eur > limit:
        return None, "overig", f"€{row.price_eur:.0f}: boven €{limit:.0f}, een fiets of set, geen losse computer"
    verdict = pc.classify_title(row.title, catalog)
    if verdict is None:
        found = ACCESSORY_RE.search(row.title)
        if found:
            return None, "accessoire", f"geen computer ('{found.group(0)}')"
        kind, reason = pc.classify_unknown(row.title)
        return None, kind, reason
    if verdict.kind == "twijfel":
        clean = list(mp_prices.get(verdict.model.label, {}).values())
        kind, reason = pc._resolve_doubt(row, verdict.model, clean, verdict.reason, config)
        return verdict.model, kind, reason
    return verdict.model, verdict.kind, verdict.reason


@dataclass
class VintedItem:
    row: VintedRow
    model: Optional[pc.ComputerModel]
    kind: str
    reason: str
    first_exported_at: str
    last_exported_at: str
    is_new: bool = False
    cost_eur: Optional[float] = None  # vraagprijs + kopersbescherming + verzending
    resale_eur: Optional[float] = None  # verwachte verkoopprijs op Marktplaats
    mp_count: int = 0
    profit_eur: Optional[float] = None  # na ook de verzending bij het doorverkopen

    @property
    def is_computer(self) -> bool:
        return self.kind == "computer"


@dataclass
class ModelRow:
    model: pc.ComputerModel
    vinted: list  # vraagprijzen op Vinted, nu actief
    marktplaats: list  # vraagprijzen op Marktplaats, laatste comp_window_days
    resale_eur: Optional[float]  # Marktplaats: verwachte verkoopprijs

    @property
    def vinted_median(self) -> float:
        return statistics.median(self.vinted)

    @property
    def mp_median(self) -> Optional[float]:
        return statistics.median(self.marktplaats) if self.marktplaats else None

    @property
    def ratio(self) -> Optional[float]:
        """Vinted-mediaan ÷ Marktplaats-mediaan; pas vanaf min_comps op
        Marktplaats, anders zegt het getal weinig."""
        return self.vinted_median / self.mp_median if self.resale_eur is not None and self.mp_median else None


@dataclass
class VintedView:
    items: list  # VintedItem, alleen actief
    models: list  # ModelRow
    newest_export: str
    shipping_eur: float
    costs_eur: float

    @property
    def computers(self) -> list:
        return [i for i in self.items if i.is_computer and i.model]

    @property
    def unknown(self) -> list:
        return [i for i in self.items if i.is_computer and not i.model]

    @property
    def excluded(self) -> list:
        return [i for i in self.items if not i.is_computer]

    @property
    def flips(self) -> list:
        found = [i for i in self.computers if i.profit_eur is not None and i.profit_eur > 0]
        return sorted(found, key=lambda i: -i.profit_eur)

    @property
    def median_ratio(self) -> Optional[float]:
        ratios = [m.ratio for m in self.models if m.ratio is not None]
        return statistics.median(ratios) if ratios else None


def _parse_time(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _read_rows(db_path) -> list:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM vinted_listing").fetchall()
    except sqlite3.OperationalError:
        # Een database van vóór migratie 8: nog nooit een export ingelezen.
        return []
    finally:
        conn.close()


def load_view(db_path, config: Optional[dict] = None) -> Optional[VintedView]:
    """Wat er volgens de laatste exports op Vinted te koop staat, naast
    Marktplaats. None als er nog geen export is ingelezen."""
    config = config or pc.default_config()
    if not db_path or not Path(db_path).exists():
        return None
    rows = _read_rows(db_path)
    seen = [t for t in (_parse_time(r["last_exported_at"]) for r in rows) if t]
    if not seen:
        return None
    newest = max(seen)
    active_since = newest - timedelta(days=config["dashboard"]["active_days"])
    new_since = newest - timedelta(hours=config["dashboard"]["new_hours"])
    flip = config["flip"]
    shipping = settings(config)["shipping_eur"]
    costs = flip.get("costs_eur", 0.0)

    catalog = pc._default_catalog()
    mp_prices = pc.db_comparables(db_path, catalog, flip["comp_window_days"])
    resale = {
        label: pc._resale_band(list(prices.values()), flip["negotiation_factor"])[1]
        for label, prices in mp_prices.items()
        if len(prices) >= flip["min_comps"]
    }

    items = []
    for r in rows:
        last = _parse_time(r["last_exported_at"])
        if last is None or last < active_since:
            continue
        row = VintedRow(
            item_id=r["item_id"], title=r["title"], price_eur=r["price_eur"], fee_eur=r["fee_eur"],
            total_eur=r["total_eur"], brand=r["brand"] or "", size=r["size"] or "", condition=r["condition"] or "",
            favorites=r["favorites"], url=r["url"] or "", image_url=r["image_url"] or "",
            seller_id=r["seller_id"] or "", is_business=bool(r["is_business"]),
        )
        model, kind, reason = classify(row, catalog, mp_prices, config)
        first = _parse_time(r["first_exported_at"])
        item = VintedItem(row, model, kind, reason, r["first_exported_at"], r["last_exported_at"],
                          is_new=bool(first and first >= new_since))
        if item.is_computer and model:
            if row.fee_eur is not None:
                item.cost_eur = round(row.price_eur + row.fee_eur + shipping, 2)
            item.mp_count = len(mp_prices.get(model.label, {}))
            item.resale_eur = resale.get(model.label)
            if item.cost_eur is not None and item.resale_eur is not None:
                item.profit_eur = round(item.resale_eur - costs - item.cost_eur, 2)
        items.append(item)
    if items and all(i.is_new for i in items):
        # De eerste export: alles is "nieuw", en dan zegt het label niets.
        for i in items:
            i.is_new = False

    by_model: dict[str, list] = {}
    for i in items:
        if i.is_computer and i.model:
            by_model.setdefault(i.model.label, []).append(i)
    models = [
        ModelRow(its[0].model, sorted(i.row.price_eur for i in its),
                 sorted(mp_prices.get(label, {}).values()), resale.get(label))
        for label, its in by_model.items()
    ]
    models.sort(key=lambda m: (-len(m.vinted), m.model.label))
    return VintedView(items, models, newest.isoformat(timespec="minutes"), shipping, costs)


# --- Console -----------------------------------------------------------------------


def _euro(amount: Optional[float]) -> str:
    return "—" if amount is None else f"€{amount:.0f}"


def _local(iso: str) -> str:
    moment = _parse_time(iso)
    return moment.astimezone().strftime("%d-%m-%Y %H:%M") if moment else iso


def print_view(view: Optional[VintedView], flips: int = 15) -> None:
    if view is None:
        print("Nog geen Vinted-export in de database. Lees er een in met: python vinted.py import <export.csv>")
        return
    print(f"Vinted naast Marktplaats · laatste export {_local(view.newest_export)} · "
          f"{len(view.computers)} computers met bekend model, {len(view.unknown)} zonder, "
          f"{len(view.excluded)} uitgefilterd")
    print()
    print(f"{'Model':28} {'Vinted':>6} {'laagste':>8} {'mediaan':>8} {'MP':>4} {'mediaan':>8} {'verkoop':>8} {'V÷MP':>5}")
    for m in view.models:
        ratio = f"{m.ratio:.2f}".replace(".", ",") if m.ratio is not None else "—"
        print(f"{m.model.label:28} {len(m.vinted):>6} {_euro(m.vinted[0]):>8} {_euro(m.vinted_median):>8} "
              f"{len(m.marktplaats):>4} {_euro(m.mp_median):>8} {_euro(m.resale_eur):>8} {ratio:>5}")
    print()
    cents = lambda amount: f"€{amount:.2f}".replace(".", ",")
    print(f"Koop op Vinted, verkoop op Marktplaats: vraagprijs + kopersbescherming + "
          f"{cents(view.shipping_eur)} verzending, bij verkoop nog {cents(view.costs_eur)} eraf.")
    if not view.flips:
        print("  Geen advertentie onder de Marktplaats-verkoopprijs.")
    for i in view.flips[:flips]:
        print(f"  {'+' + _euro(i.profit_eur):>6}  {i.model.label:24} vraagt {_euro(i.row.price_eur):>5}, "
              f"je betaalt {_euro(i.cost_eur):>5}, verkoopt ±{_euro(i.resale_eur)} (n={i.mp_count})  "
              f"{i.row.condition}  {i.row.url}")


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["import"]:
        parser = argparse.ArgumentParser(prog="vinted.py import", description="Vinted-exports in koopjes.db inlezen.")
        parser.add_argument("files", nargs="+", help="een of meer Vinted-exports (CSV)")
        parser.add_argument("--db", default=DEFAULT_DB, help=f"database (standaard {DEFAULT_DB})")
        parser.add_argument("--at", help="tijdstip van de export (ISO), als het niet in de bestandsnaam staat")
        args = parser.parse_args(argv[1:])
        target = Path(args.db).resolve()
        existed = target.exists()
        conn = db.connect(str(target))
        print(f"Database: {target}")
        if not existed:
            print("Let op: die database bestond nog niet en is nu nieuw aangemaakt. Het dashboard ziet deze "
                  "Vinted-data alleen als het dezelfde database gebruikt.")
        try:
            for path in args.files:
                try:
                    r = import_export(conn, path, args.at)
                except (ExportError, OSError) as exc:
                    print(f"Fout: {exc}", file=sys.stderr)
                    return 1
                skipped = "".join(f", {n} overgeslagen ({why})" for why, n in r.skipped.items())
                print(f"{r.file} ({_local(r.exported_at)}): {r.rows} advertenties, {r.new} nieuw, "
                      f"{r.updated} al bekend ({r.repriced} met een andere prijs){skipped}")
        finally:
            conn.close()
        print("Bekijk ze met: python vinted.py, of in de tab Vinted van python dashboard.py")
        return 0
    parser = argparse.ArgumentParser(description="Vinted naast Marktplaats: per model en de flips.")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"database (standaard {DEFAULT_DB})")
    parser.add_argument("--flips", type=int, default=15, help="hoeveel flips tonen (standaard 15)")
    args = parser.parse_args(argv)
    print_view(load_view(args.db), args.flips)
    return 0


if __name__ == "__main__":
    sys.exit(main())
