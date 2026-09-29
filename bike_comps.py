"""De vergelijkingslijst voor de eigen fiets: welke advertenties meetellen in
de taxatie van de fiets uit `mijn_fiets.md`.

Waarom een lijst en geen regel: de Giant Defy is een modellijn, geen model.
Onder die naam verkoopt Giant sinds 2009 aluminium (Aluxx, Defy 0-5),
instapcarbon (Composite), Advanced, Advanced Pro, Advanced SL en vanaf 2015
schijfremfietsen, en verkopers schrijven meestal alleen "Giant Defy carbon".
De automatische ladder in valuation.py (zelfde model → modelfamilie →
segment) liet daardoor Advanced Pro's en andere merken meetellen. De eigenaar
kijkt zelf, per advertentie: meenemen of niet (tabel `comp_choice`, migratie
16), op de live pagina /fiets van `python dashboard.py --serve`.

Wat er in de lijst staat: elke advertentie uit de categorie racefietsen van
de laatste 180 dagen (ook verdwenen: dat zijn de fietsen die weggingen) met
de modelfamilie ("defy") in de tekst, behalve als het materiaal bekend is en
niet dat van de eigen fiets. Het materiaal komt van het referentiemodel
(reference_bikes.csv: Defy 0-5 en Aluxx zijn aluminium, Composite en
Advanced carbon) en anders van de tekst of de kenmerken van de verkoper
(tabel `spec`; heeft een advertentie daar niets, dan de tekst hier) —
dezelfde volgorde als valuation.candidate_material(). Zegt niets iets, dan
staat hij erin als "materiaal onbekend": dan beslist de eigenaar.

Wat meetelt: alleen wat hij meenam, en alleen met een vraagprijs. Een
bied-advertentie waarop al geboden is staat in de lijst, maar haar prijs is
een tussenstand en telt niet mee (zelfde regel als
valuation.fetch_comp_candidates()). Niets meegenomen is geen taxatie; dan
rekent de upgrade-finder met verkoopprijs_handmatig uit mijn_fiets.md.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import db
import racefiets_jev as mp
import valuation as val

MEE = val.COMP_TAKEN
NIET = "niet"
CHOICES = (MEE, NIET)


@dataclass
class Row:
    item_id: str
    title: str
    url: str
    price_eur: Optional[float]
    price_type: str
    city: str
    frame_height: str
    image_urls: str
    first_seen: Optional[str]
    last_seen: Optional[str]
    disappeared_at: Optional[str]
    days_online: Optional[int]
    reserved: bool
    bid_count: Optional[int]
    bid_high: Optional[float]
    # "carbon" (of wat de eigen fiets is), of None: niet bekend.
    material: Optional[str]
    year: Optional[int]
    # Waarmee reference_bikes.csv hem herkende ("Giant Defy Advanced").
    model_label: str
    # Telt mee in de taxatie als hij meegenomen is: een vraagprijs.
    counts: bool
    choice: Optional[str] = None

    @property
    def gone(self) -> bool:
        return self.disappeared_at is not None

    @property
    def why_not(self) -> str:
        """Waarom zijn prijs niet meetelt, of leeg als hij wel meetelt."""
        if self.counts:
            return ""
        if self.price_eur is None or self.price_eur <= 0:
            return "geen prijs"
        return "al geboden: de prijs is een tussenstand"


def _columns(conn: sqlite3.Connection) -> set:
    return {r[1] for r in conn.execute("PRAGMA table_info(listing)")}


def _bike_labels(conn: sqlite3.Connection, item_ids: list[str]) -> dict[str, str]:
    """Per advertentie het referentiemodel waarmee hij herkend is. Hangen er
    meer aan (het patroon voor "Giant Defy (overig)" raakt elke Defy), dan
    het specifiekste: het eerste zonder "(overig)"."""
    found: dict[str, list[str]] = {}
    for start in range(0, len(item_ids), 500):
        chunk = item_ids[start:start + 500]
        rows = conn.execute(
            "SELECT lm.listing_id, m.model FROM listing_model lm JOIN model m ON m.id = lm.model_id "
            f"WHERE m.kind = 'bike' AND lm.listing_id IN ({','.join('?' * len(chunk))}) ORDER BY m.id",
            chunk,
        ).fetchall()
        for row in rows:
            if row[1]:
                found.setdefault(row[0], []).append(row[1])
    return {
        item_id: next((l for l in labels if "(overig)" not in l), labels[0])
        for item_id, labels in found.items()
    }


def load_rows(conn: sqlite3.Connection, subject: val.Subject, *,
              window_days: int = val.DEFAULT_COMP_WINDOW_DAYS,
              as_of: Optional[datetime] = None) -> list[Row]:
    """De lijst voor /fiets, met de keuze van de eigenaar erbij."""
    words = [w.lower() for w in subject.family_patterns if w]
    if not words:
        return []
    columns = _columns(conn)
    full = "full_description" if "full_description" in columns else "NULL"
    optional = {
        "reserved_at": "reserved_at" if "reserved_at" in columns else "NULL",
        "bid_count": "bid_count" if "bid_count" in columns else "NULL",
        "bid_high": "bid_high" if "bid_high" in columns else "NULL",
        "price_is_asking": "price_is_asking" if "price_is_asking" in columns else "NULL",
    }
    # LIKE is in SQLite hoofdletterongevoelig voor ASCII; de familie is één
    # los woord ("defy"), net als bij trede 2 van de ladder.
    text_match = " OR ".join(
        f"title LIKE ? OR description LIKE ? OR {full} LIKE ?" for _ in words
    )
    params: list = [p for w in words for p in (f"%{w}%",) * 3]
    sql = (
        "SELECT item_id, title, description, price_eur, price_type, is_bid, city, frame_height, url, "
        f"image_urls, first_seen, last_seen, disappeared_at, days_online, {full} AS full_description, "
        + ", ".join(f"{expr} AS {name}" for name, expr in optional.items())
        + f" FROM listing WHERE ({text_match})"
    )
    as_of = as_of or datetime.now(timezone.utc)
    if window_days > 0:
        sql += " AND (last_seen IS NULL OR last_seen >= ?)"
        params.append((as_of - timedelta(days=window_days)).isoformat(timespec="seconds"))
    rows = [
        r for r in conn.execute(sql, params).fetchall()
        # Een los frame of een onderdeel is geen vergelijking voor een
        # complete fiets (zelfde regel als valuation._is_complete_bike).
        if mp.category_from_url(r["url"] or "") in (None, mp.ROAD_BIKE_CATEGORY)
    ]
    ids = [r["item_id"] for r in rows]
    specs = db.read_listing_specs(conn)
    materials = val.reference_materials(conn)
    labels = _bike_labels(conn, ids)
    choices = db.list_comp_choices(conn)

    found = []
    for r in rows:
        spec = specs.get(r["item_id"], {})
        if not spec:
            # Nog nooit specs vastgelegd (een rij van vóór fase 2, of een
            # ronde zonder): dan dezelfde lezing van de tekst hier.
            spec = mp.extract_specs(f"{r['title'] or ''} {r['full_description'] or r['description'] or ''}")
        material = materials.get(r["item_id"]) or spec.get("frame_material") or None
        if subject.frame_material and material and material != subject.frame_material:
            continue
        year = spec.get("model_year")
        price = r["price_eur"]
        asking = r["price_is_asking"]
        counts = bool(price and price > 0 and (asking == 1 or (asking is None and not r["is_bid"])))
        days = r["days_online"]
        if days is None and r["disappeared_at"] is None:
            days = val._derive_days_online(r["first_seen"], as_of)
        found.append(Row(
            item_id=r["item_id"],
            title=r["title"] or "",
            url=r["url"] or "",
            price_eur=price,
            price_type=r["price_type"] or "",
            city=r["city"] or "",
            frame_height=r["frame_height"] or "",
            image_urls=r["image_urls"] or "",
            first_seen=r["first_seen"],
            last_seen=r["last_seen"],
            disappeared_at=r["disappeared_at"],
            days_online=days,
            reserved=r["reserved_at"] is not None,
            bid_count=r["bid_count"],
            bid_high=r["bid_high"],
            material=material,
            year=int(year) if year and str(year).isdigit() else val.title_year(r["title"] or ""),
            model_label=labels.get(r["item_id"], ""),
            counts=counts,
            choice=choices.get(r["item_id"]),
        ))
    return found


def open_readonly(db_path) -> Optional[sqlite3.Connection]:
    """Alleen lezen, zonder de database aan te maken of te migreren."""
    if not db_path or not Path(db_path).exists():
        return None
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn
