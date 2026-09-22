"""SQLite storage for koopjes.db.

Fase 1a of PLAN_FIETSWAARDE.md built this module standalone. Fase 1b wires it
into racefiets_jev.py, which now writes to koopjes.db on every run (unless
--no-db) alongside the CSV/JSON files it already wrote — nothing about their
format changes. What's here:

- the schema from PLAN_FIETSWAARDE.md §5, applied via connect()
- import_legacy(), which migrates the three existing on-disk files that carry
  real data (seen_listings.json, reference_prices.csv,
  reference_price_history.csv) into the new tables. bargains_log.csv is
  deliberately left out: the plan keeps it as a pure derived export, and
  writing scored/derived listing fields back into the DB would make later
  valuations circular.
- sync_listings(), which upserts a crawl's own listings (query, url, price
  type, ...) straight into `listing`/`listing_price` — richer than what
  import_legacy() can recover from seen_listings.json alone.
- record_crawl_run() and sweep_disappeared(), which back E2 in §6: the sweep
  must only run after a full crawl (`--pages 0`) of the same query.
- export_csv(), which writes the `model` table back out in
  reference_prices.csv's column format, so reference_overview.py and
  check_reference_overlaps.py (both of which read that format through
  racefiets_jev.load_reference_data()) keep working unchanged.

Never write a derived valuation back into listing_price or component_price —
those two tables are raw observations only, and a valuation feeding back into
its own evidence would drift away from the market within weeks.
"""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
from datetime import datetime, timezone

# Each entry is one migration's DDL, applied in order. Add new entries to
# extend the schema; never edit an already-shipped one, or a DB created under
# the old version won't match what CURRENT_VERSION claims it has.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE crawl_run (
        id INTEGER PRIMARY KEY,
        query TEXT NOT NULL,
        pages_requested INTEGER,
        pages_fetched INTEGER,
        listing_count INTEGER,
        started_at TEXT,
        finished_at TEXT
    );

    CREATE TABLE listing (
        item_id TEXT PRIMARY KEY,
        title TEXT,
        description TEXT,
        price_eur REAL,
        price_type TEXT,
        is_bid INTEGER NOT NULL DEFAULT 0,
        city TEXT,
        posted_date TEXT,
        condition TEXT,
        frame_height TEXT,
        url TEXT,
        query TEXT,
        first_seen TEXT,
        last_seen TEXT,
        disappeared_at TEXT,
        days_online INTEGER
    );

    -- Raw observations only — never a derived/taxated price. See module docstring.
    CREATE TABLE listing_price (
        id INTEGER PRIMARY KEY,
        item_id TEXT NOT NULL REFERENCES listing(item_id),
        observed_at TEXT NOT NULL,
        price_eur REAL NOT NULL,
        UNIQUE (item_id, observed_at)
    );

    -- kind: 'bike' | 'frameset' | 'groupset' | 'wheelset' | 'computer' |
    --       'powermeter' | 'other'. UNIQUE(kind, pattern) is what makes
    --       import_legacy() idempotent for this table.
    CREATE TABLE model (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,
        brand TEXT,
        model TEXT,
        variant TEXT,
        year_from INTEGER,
        year_to INTEGER,
        pattern TEXT NOT NULL,
        original_price_eur REAL,
        specs_json TEXT,
        score TEXT,
        notes TEXT,
        source_url TEXT,
        UNIQUE (kind, pattern)
    );

    -- Many-to-many: one listing can match several models (bike + powermeter +
    -- computer in the same ad). Left empty by fase 1a — populating it is
    -- fase 2's job (dropping the `break` in apply_reference_data).
    CREATE TABLE listing_model (
        listing_id TEXT NOT NULL REFERENCES listing(item_id),
        model_id INTEGER NOT NULL REFERENCES model(id),
        matched_on TEXT,
        confidence REAL,
        PRIMARY KEY (listing_id, model_id)
    );

    -- key: frame_material, brake_type, speeds, groupset_tier, electronic,
    --      wheel_type, model_year, weight_kg, has_powermeter, has_computer, ...
    CREATE TABLE spec (
        id INTEGER PRIMARY KEY,
        listing_id TEXT NOT NULL REFERENCES listing(item_id),
        key TEXT NOT NULL,
        value TEXT,
        source TEXT,
        confidence REAL
    );

    CREATE TABLE owned_item (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,
        label TEXT NOT NULL,
        model_id INTEGER REFERENCES model(id),
        acquired_price_eur REAL,
        specs_json TEXT,
        notes TEXT
    );

    CREATE TABLE valuation (
        id INTEGER PRIMARY KEY,
        subject_type TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        scenario TEXT,
        low_eur REAL,
        mid_eur REAL,
        high_eur REAL,
        confidence TEXT,
        method_version TEXT,
        created_at TEXT
    );

    -- kind: 'comp' | 'parts' | 'retail' | 'depreciation' | 'adjustment'
    CREATE TABLE valuation_evidence (
        id INTEGER PRIMARY KEY,
        valuation_id INTEGER NOT NULL REFERENCES valuation(id),
        kind TEXT NOT NULL,
        ref_id TEXT,
        ref_url TEXT,
        price_eur REAL,
        weight REAL,
        note TEXT
    );

    -- Raw observations only, same rule as listing_price. See module docstring.
    CREATE TABLE component_price (
        id INTEGER PRIMARY KEY,
        model_id INTEGER NOT NULL REFERENCES model(id),
        observed_at TEXT,
        price_eur REAL,
        source_url TEXT,
        note TEXT
    );

    CREATE TABLE watchlist (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        query TEXT NOT NULL,
        filters_json TEXT,
        active INTEGER NOT NULL DEFAULT 1
    );
    """,
]


def connect(path: str) -> sqlite3.Connection:
    """Open (creating if needed) the koopjes.db at `path` and bring it up to
    the latest schema version."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "version INTEGER NOT NULL, applied_at TEXT NOT NULL)"
    )
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = row["v"] or 0
    if current > len(MIGRATIONS):
        # Slicing past the end is empty, so without this the older code would
        # just carry on against a schema it doesn't know, and write into
        # tables that may since have changed shape.
        raise RuntimeError(
            f"deze database staat op schemaversie {current}, maar deze versie van "
            f"db.py kent er maar {len(MIGRATIONS)}. Werk de code bij in plaats van "
            "met een nieuwere database te werken."
        )
    for version, ddl in enumerate(MIGRATIONS[current:], start=current + 1):
        conn.executescript(ddl)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
    conn.commit()


def _import_seen_listings(conn: sqlite3.Connection, path: str) -> int:
    """seen_listings.json -> listing + listing_price."""
    try:
        with open(path, encoding="utf-8") as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0

    if not isinstance(history, dict):
        # Valid JSON, wrong shape (hand-edited, or another file under this
        # name). racefiets_jev.load_history() treats that as "no history";
        # do the same rather than dying on .items().
        print(
            f"warning: {path} bevat geen advertentie-geschiedenis "
            f"({type(history).__name__}); overgeslagen.",
            file=sys.stderr,
        )
        return 0

    for item_id, entry in history.items():
        conn.execute(
            """
            INSERT INTO listing (item_id, title, price_eur, first_seen, last_seen)
            VALUES (:item_id, :title, :price_eur, :first_seen, :last_seen)
            ON CONFLICT(item_id) DO UPDATE SET
                title = excluded.title,
                price_eur = excluded.price_eur,
                first_seen = excluded.first_seen,
                last_seen = excluded.last_seen
            """,
            {
                "item_id": item_id,
                "title": entry.get("title", ""),
                "price_eur": entry.get("last_price"),
                "first_seen": entry.get("first_seen", ""),
                "last_seen": entry.get("last_seen", ""),
            },
        )
        last_price = entry.get("last_price")
        last_seen = entry.get("last_seen")
        if last_price is not None and last_seen:
            conn.execute(
                "INSERT OR IGNORE INTO listing_price (item_id, observed_at, price_eur) "
                "VALUES (?, ?, ?)",
                (item_id, last_seen, last_price),
            )
    return len(history)


def _import_reference_prices(conn: sqlite3.Connection, path: str) -> int:
    """reference_prices.csv -> model.

    The free-text `specs` column and the `better_than_baseline` flag don't
    have their own columns on `model` (that table is shared with bike/part
    models that don't have either concept), so both go into specs_json as
    {"specs": ..., "better_than_baseline": ...}. export_csv() reverses this.
    """
    try:
        with open(path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        return 0

    count = 0
    for row in rows:
        pattern = (row.get("pattern") or "").strip()
        if not pattern:
            continue
        label = (row.get("label") or pattern).strip()
        original_price_raw = (row.get("original_price_eur") or "").strip()
        try:
            original_price = float(original_price_raw) if original_price_raw else None
        except ValueError:
            # reference_prices.csv is maintained by hand, so this column will
            # hold "ca. 300" or "?" sooner or later. One unreadable cell must
            # not abort the migration of the whole file.
            print(
                f"warning: {path}: onleesbare nieuwprijs {original_price_raw!r} bij "
                f"patroon {pattern!r} — als leeg geïmporteerd",
                file=sys.stderr,
            )
            original_price = None
        better = (row.get("better_than_baseline") or "").strip().lower() in (
            "1", "true", "yes", "ja",
        )
        specs_json = json.dumps(
            {"specs": (row.get("specs") or "").strip(), "better_than_baseline": better}
        )
        conn.execute(
            """
            INSERT INTO model (kind, model, pattern, original_price_eur, specs_json, score)
            VALUES ('other', :model, :pattern, :original_price_eur, :specs_json, :score)
            ON CONFLICT(kind, pattern) DO UPDATE SET
                model = excluded.model,
                original_price_eur = excluded.original_price_eur,
                specs_json = excluded.specs_json,
                score = excluded.score
            """,
            {
                "model": label,
                "pattern": pattern,
                "original_price_eur": original_price,
                "specs_json": specs_json,
                "score": (row.get("score") or "").strip(),
            },
        )
        count += 1
    return count


def _import_reference_price_history(conn: sqlite3.Connection, path: str) -> int:
    """reference_price_history.csv -> listing_price.

    A row can reference an item_id that isn't in `listing` yet (the history
    file can be older or younger than the seen_listings.json snapshot given
    to import_legacy()), so this inserts a minimal listing stub first rather
    than letting the foreign key fail.
    """
    try:
        with open(path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        return 0

    count = 0
    for row in rows:
        item_id = (row.get("item_id") or "").strip()
        observed_at = (row.get("date") or "").strip()
        price_raw = (row.get("price_eur") or "").strip()
        if not item_id or not observed_at or not price_raw:
            continue
        try:
            price_eur = float(price_raw)
        except ValueError:
            continue

        conn.execute(
            "INSERT INTO listing (item_id, title) VALUES (?, ?) "
            "ON CONFLICT(item_id) DO NOTHING",
            (item_id, (row.get("title") or "").strip()),
        )
        conn.execute(
            "INSERT OR IGNORE INTO listing_price (item_id, observed_at, price_eur) "
            "VALUES (?, ?, ?)",
            (item_id, observed_at, price_eur),
        )
        count += 1
    return count


def import_legacy(
    conn: sqlite3.Connection,
    *,
    seen_listings_path: str = "seen_listings.json",
    reference_prices_path: str = "reference_prices.csv",
    reference_price_history_path: str = "reference_price_history.csv",
) -> dict[str, int]:
    """Migrate the three legacy on-disk files into the schema above.

    Safe to call more than once (on repeated runs, or a rerun of the same
    files): rows are upserted by their natural key rather than duplicated.
    Missing files are treated the same way the existing loaders in
    racefiets_jev.py treat them — as "nothing to import yet", not an error.
    """
    counts = {
        "listings_from_history": _import_seen_listings(conn, seen_listings_path),
        "models_from_reference": _import_reference_prices(conn, reference_prices_path),
        "prices_from_reference_history": _import_reference_price_history(
            conn, reference_price_history_path
        ),
    }
    conn.commit()
    return counts


def record_crawl_run(
    conn: sqlite3.Connection,
    *,
    query: str,
    pages_requested: int,
    pages_fetched: "int | None",
    listing_count: int,
    started_at: str,
    finished_at: str,
) -> int:
    """Log one crawl in `crawl_run` and return its id. This is what the
    disappearance sweep (E2 in PLAN_FIETSWAARDE.md §6) needs to tell a
    shallow crawl from a full one — sweep_disappeared() must only run after
    a full crawl of the same query, never a `--pages 3` one."""
    cur = conn.execute(
        """
        INSERT INTO crawl_run (query, pages_requested, pages_fetched, listing_count,
                                started_at, finished_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (query, pages_requested, pages_fetched, listing_count, started_at, finished_at),
    )
    conn.commit()
    return cur.lastrowid


def sync_listings(conn: sqlite3.Connection, query: str, listings, observed_at: str) -> None:
    """Upsert this run's listings into `listing`, and record one
    `listing_price` observation per priced listing. A listing that reappears
    after being marked disappeared has its disappeared_at cleared — it's
    back."""
    for listing in listings:
        conn.execute(
            """
            INSERT INTO listing (item_id, title, description, price_eur, price_type, is_bid,
                                  city, posted_date, condition, frame_height, url, query,
                                  first_seen, last_seen)
            VALUES (:item_id, :title, :description, :price_eur, :price_type, :is_bid,
                    :city, :posted_date, :condition, :frame_height, :url, :query,
                    :first_seen, :last_seen)
            ON CONFLICT(item_id) DO UPDATE SET
                title = excluded.title,
                description = excluded.description,
                price_eur = excluded.price_eur,
                price_type = excluded.price_type,
                is_bid = excluded.is_bid,
                city = excluded.city,
                posted_date = excluded.posted_date,
                condition = excluded.condition,
                frame_height = excluded.frame_height,
                url = excluded.url,
                query = excluded.query,
                last_seen = excluded.last_seen,
                disappeared_at = NULL
            """,
            {
                "item_id": listing.item_id,
                "title": listing.title,
                "description": listing.description,
                "price_eur": listing.price_eur,
                "price_type": listing.price_type,
                "is_bid": 1 if listing.price_is_bid else 0,
                "city": listing.city,
                "posted_date": listing.date,
                "condition": listing.condition,
                "frame_height": listing.frame_height,
                "url": listing.url,
                "query": query,
                "first_seen": listing.first_seen or observed_at,
                "last_seen": observed_at,
            },
        )
        if listing.price_eur is not None:
            conn.execute(
                "INSERT OR IGNORE INTO listing_price (item_id, observed_at, price_eur) "
                "VALUES (?, ?, ?)",
                (listing.item_id, observed_at, listing.price_eur),
            )
    conn.commit()


def sweep_disappeared(
    conn: sqlite3.Connection, query: str, seen_item_ids, observed_at: str
) -> int:
    """Mark every listing for `query` that isn't in `seen_item_ids` and isn't
    already marked as disappeared. Call this only after a full crawl
    (`--pages 0`) of that exact query — a shallow crawl only sees the first
    few pages, and would otherwise mark everything past that depth as gone.
    Returns how many rows were newly marked."""
    rows = conn.execute(
        "SELECT item_id, first_seen FROM listing WHERE query = ? AND disappeared_at IS NULL",
        (query,),
    ).fetchall()

    count = 0
    for row in rows:
        if row["item_id"] in seen_item_ids:
            continue
        days_online = None
        first_seen = row["first_seen"]
        if first_seen:
            try:
                delta = _parse_iso(observed_at) - _parse_iso(first_seen)
                days_online = delta.days
            except ValueError:
                days_online = None
        conn.execute(
            "UPDATE listing SET disappeared_at = ?, days_online = ? WHERE item_id = ?",
            (observed_at, days_online, row["item_id"]),
        )
        count += 1
    conn.commit()
    return count


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_price(value) -> str:
    """Write a whole number back as "110", not "110.0". SQLite hands back a
    REAL, so without this every priced row in reference_prices.csv changes
    the moment the file is exported — a diff full of noise in a file that is
    maintained (and reviewed) by hand."""
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return str(float(value))


def export_csv(conn: sqlite3.Connection, path: str) -> int:
    """Write the `model` table back out as reference_prices.csv's exact
    column format (pattern,label,original_price_eur,specs,score,
    better_than_baseline), so racefiets_jev.load_reference_data() — and
    therefore reference_overview.py and check_reference_overlaps.py — can
    still read it. Returns the number of rows written."""
    rows = conn.execute(
        "SELECT pattern, model, original_price_eur, specs_json, score FROM model ORDER BY id"
    ).fetchall()

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["pattern", "label", "original_price_eur", "specs", "score", "better_than_baseline"]
        )
        for row in rows:
            extra = json.loads(row["specs_json"] or "{}")
            writer.writerow(
                [
                    row["pattern"],
                    row["model"],
                    _format_price(row["original_price_eur"]),
                    extra.get("specs", ""),
                    row["score"] or "",
                    "1" if extra.get("better_than_baseline") else "0",
                ]
            )
    return len(rows)
