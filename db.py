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
- save_watchlist()/get_watchlist()/list_watchlists()/delete_watchlist(), the
  named searches of fase 8. racefiets_jev.py decides which filters exist and
  how a watchlist run is kept apart from the regular queries.
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


# A CSV saved from Excel starts with a UTF-8 BOM, which otherwise ends up in
# the first column's name and makes every row look like it is missing that
# column. Same reasoning as racefiets_jev.CSV_READ_ENCODING.
CSV_READ_ENCODING = "utf-8-sig"

# The `kind` values from PLAN_FIETSWAARDE.md §5. A reference file may say
# which one a row is (fase 7's bike files do); anything else is a typo, and a
# typo'd kind would quietly start its own UNIQUE(kind, pattern) namespace.
MODEL_KINDS = ("bike", "frameset", "groupset", "wheelset", "computer", "powermeter", "other")

# Same values racefiets_jev.extract_specs() writes for frame_material, so a
# reference model's material and one read from a listing's text compare
# directly.
FRAME_MATERIALS = ("carbon", "aluminium", "staal", "titanium")


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
        # The version row goes in the same script as the schema it belongs
        # to, wrapped in one transaction. executescript() commits whatever is
        # pending before it runs and leaves the DDL committed too, so an
        # INSERT afterwards could be lost while the tables were already on
        # disk — and the next start would then re-run a migration against
        # tables that exist, leaving the database unopenable (the DDL has no
        # IF NOT EXISTS, deliberately: a migration that half-applied is worth
        # noticing, not papering over). SQLite rolls CREATE TABLE back like
        # any other statement, so schema and version now land together or not
        # at all. Both values in the INSERT are ours, not input: a version
        # number from enumerate() and a timestamp we just formatted.
        applied_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # rstrip/";": a migration string whose last statement forgets its
        # semicolon would otherwise run straight into the INSERT below, and
        # the syntax error would point at the wrong line.
        statements = ddl.strip().rstrip(";") + ";"
        try:
            conn.executescript(
                "BEGIN;\n"
                + statements
                + "\nINSERT INTO schema_version (version, applied_at) "
                + f"VALUES ({version}, '{applied_at}');\n"
                + "COMMIT;"
            )
        except sqlite3.Error:
            # Without this the failed transaction stays open on this
            # connection and keeps its lock until the object is collected.
            conn.rollback()
            raise
    conn.commit()


def _import_seen_listings(conn: sqlite3.Connection, path: str) -> int:
    """seen_listings.json -> listing + listing_price."""
    try:
        with open(path, encoding=CSV_READ_ENCODING) as f:
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

    imported = 0
    skipped = 0
    for item_id, entry in history.items():
        if not isinstance(entry, dict):
            # One hand-edited entry shouldn't cost the whole migration.
            skipped += 1
            continue
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
        imported += 1

    if skipped:
        print(
            f"warning: {path}: {skipped} regel(s) overgeslagen die geen "
            "advertentie-gegevens bevatten.",
            file=sys.stderr,
        )
    return imported


def _import_reference_prices(conn: sqlite3.Connection, path: str) -> int:
    """reference_prices.csv -> model.

    The free-text `specs` column and the `better_than_baseline` flag don't
    have their own columns on `model` (that table is shared with bike/part
    models that don't have either concept), so both go into specs_json as
    {"specs": ..., "better_than_baseline": ...}. export_csv() reverses this.

    Three optional columns go straight into `model`: `kind`, `brand` and
    `source_url`. A fourth, `frame_material`, goes into specs_json. reference_prices.csv has none of them and imports exactly
    as before (kind 'other'); fase 7's reference_bikes.csv and
    reference_bike_accessories.csv carry them, because the plan wants a
    source per researched row and a real kind per model.
    load_reference_data() ignores columns it doesn't know, so the script
    reads those files unchanged.
    """
    try:
        with open(path, encoding=CSV_READ_ENCODING) as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        return 0

    seen_patterns: set[str] = set()
    for row in rows:
        pattern = (row.get("pattern") or "").strip()
        if not pattern:
            continue
        if pattern in seen_patterns:
            # The upsert is on (kind, pattern), so the second row overwrites
            # the first and the table ends up with one model where the file
            # has two. Counting both would report an import that didn't
            # happen; the file is the thing that needs fixing.
            print(
                f"warning: {path}: patroon {pattern!r} staat meer dan één keer in het "
                "bestand; alleen de laatste rij blijft over.",
                file=sys.stderr,
            )
        seen_patterns.add(pattern)
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
        extra = {"specs": (row.get("specs") or "").strip(), "better_than_baseline": better}
        # Optional, only in reference_bikes.csv, and only filled where the
        # row's own sourced specs name the material. The valuation uses it to
        # keep an aluminium "Giant Defy 1" out of the comps for a carbon Defy
        # Composite — the listing text rarely says "alu" itself.
        material = (row.get("frame_material") or "").strip().lower()
        if material and material not in FRAME_MATERIALS:
            print(
                f"warning: {path}: onbekend frame_material {material!r} bij patroon "
                f"{pattern!r} — genegeerd (geldig: {', '.join(FRAME_MATERIALS)})",
                file=sys.stderr,
            )
        elif material:
            extra["frame_material"] = material
        specs_json = json.dumps(extra)
        kind = (row.get("kind") or "").strip().lower() or "other"
        if kind not in MODEL_KINDS:
            print(
                f"warning: {path}: onbekend kind {kind!r} bij patroon {pattern!r} — "
                f"als 'other' geïmporteerd (geldig: {', '.join(MODEL_KINDS)})",
                file=sys.stderr,
            )
            kind = "other"
        conn.execute(
            """
            INSERT INTO model (kind, brand, model, pattern, original_price_eur, specs_json,
                               score, source_url)
            VALUES (:kind, :brand, :model, :pattern, :original_price_eur, :specs_json,
                    :score, :source_url)
            ON CONFLICT(kind, pattern) DO UPDATE SET
                brand = excluded.brand,
                model = excluded.model,
                original_price_eur = excluded.original_price_eur,
                specs_json = excluded.specs_json,
                score = excluded.score,
                source_url = excluded.source_url
            """,
            {
                "kind": kind,
                "brand": (row.get("brand") or "").strip() or None,
                "model": label,
                "pattern": pattern,
                "original_price_eur": original_price,
                "specs_json": specs_json,
                "score": (row.get("score") or "").strip(),
                "source_url": (row.get("source_url") or "").strip() or None,
            },
        )
    # Not len(rows): a pattern listed twice is one model in the table, and the
    # warning above has already said so.
    return len(seen_patterns)


def _import_reference_price_history(conn: sqlite3.Connection, path: str) -> int:
    """reference_price_history.csv -> listing_price.

    A row can reference an item_id that isn't in `listing` yet (the history
    file can be older or younger than the seen_listings.json snapshot given
    to import_legacy()), so this inserts a minimal listing stub first rather
    than letting the foreign key fail.
    """
    try:
        with open(path, encoding=CSV_READ_ENCODING) as f:
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


def sync_listing_specs(
    conn: sqlite3.Connection, specs_by_listing: dict, source: str = "regex"
) -> int:
    """Write racefiets_jev.extract_specs() output into `spec`, keyed by
    listing item_id. A listing's previous rows from this source are deleted
    first, so re-running the crawl on an ad whose text hasn't changed doesn't
    pile up duplicate spec rows every run. Returns how many rows were
    written."""
    count = 0
    for listing_id, specs in specs_by_listing.items():
        conn.execute(
            "DELETE FROM spec WHERE listing_id = ? AND source = ?", (listing_id, source)
        )
        for key, value in specs.items():
            conn.execute(
                "INSERT INTO spec (listing_id, key, value, source, confidence) "
                "VALUES (?, ?, ?, ?, ?)",
                (listing_id, key, value, source, 1.0),
            )
            count += 1
    conn.commit()
    return count


def sync_listing_models(
    conn: sqlite3.Connection, matches_by_listing: dict, kind: str | None = None
) -> int:
    """Write every matched reference pattern (racefiets_jev.apply_reference_data()'s
    return value) into `listing_model` — one row per (listing, model) pair,
    not just the one match that wins the report's ref_* columns. A pattern
    with no corresponding `model` row (import_legacy() hasn't run yet, or the
    kind differs) is silently skipped: this table is additive bookkeeping for
    fase 3+, nothing in the current report depends on it. Returns how many
    rows were written.

    `kind=None` (the default) links a pattern to its model whatever its kind.
    The script only knows the patterns of the one --reference-file it ran
    with, and since fase 7 that file can hold 'bike' rows as well as the
    speakers' 'other' — pinning this to 'other' would silently drop every
    bike match. Pass a kind to restrict it."""
    count = 0
    for listing_id, patterns in matches_by_listing.items():
        for pattern in patterns:
            if kind is None:
                rows = conn.execute(
                    "SELECT id FROM model WHERE pattern = ?", (pattern,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id FROM model WHERE kind = ? AND pattern = ?", (kind, pattern)
                ).fetchall()
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO listing_model (listing_id, model_id, matched_on, confidence)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(listing_id, model_id) DO UPDATE SET
                        matched_on = excluded.matched_on,
                        confidence = excluded.confidence
                    """,
                    (listing_id, row["id"], "title+description", 1.0),
                )
                count += 1
    conn.commit()
    return count


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


def save_watchlist(
    conn: sqlite3.Connection, name: str, query: str, filters: dict, active: bool = True
) -> None:
    """Create or replace the watchlist entry `name` (PLAN_FIETSWAARDE.md
    fase 8). Replacing is deliberate: saving "powermeter" again with a new
    --max-price means "this is now the powermeter search", not "add a second
    one" — the name is what the user types to run it, so it has to stay
    unique. Which filter keys are allowed is racefiets_jev's business (they
    map onto its CLI flags); this layer only stores them."""
    conn.execute(
        """
        INSERT INTO watchlist (name, query, filters_json, active)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            query = excluded.query,
            filters_json = excluded.filters_json,
            active = excluded.active
        """,
        (name, query, json.dumps(filters, sort_keys=True), 1 if active else 0),
    )
    conn.commit()


def _watchlist_row(row: sqlite3.Row) -> dict:
    try:
        filters = json.loads(row["filters_json"] or "{}")
    except json.JSONDecodeError:
        # Only reachable by editing the database by hand. Running the search
        # without its filters would quietly widen it (a powermeter watch
        # without its --max-price), so refuse instead.
        raise ValueError(
            f"filters_json van watchlist {row['name']!r} is niet te lezen: "
            f"{row['filters_json']!r}"
        )
    if not isinstance(filters, dict):
        raise ValueError(
            f"filters_json van watchlist {row['name']!r} is geen object: {row['filters_json']!r}"
        )
    return {
        "id": row["id"],
        "name": row["name"],
        "query": row["query"],
        "filters": filters,
        "active": bool(row["active"]),
    }


def get_watchlist(conn: sqlite3.Connection, name: str) -> "dict | None":
    row = conn.execute("SELECT * FROM watchlist WHERE name = ?", (name,)).fetchone()
    return _watchlist_row(row) if row else None


def list_watchlists(conn: sqlite3.Connection, active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM watchlist"
    if active_only:
        sql += " WHERE active = 1"
    return [_watchlist_row(r) for r in conn.execute(sql + " ORDER BY name").fetchall()]


def delete_watchlist(conn: sqlite3.Connection, name: str) -> bool:
    """Remove the entry; returns whether there was one. The listings it
    found stay in `listing` — they are market observations like any other,
    and E1/E2 may already lean on them."""
    cur = conn.execute("DELETE FROM watchlist WHERE name = ?", (name,))
    conn.commit()
    return cur.rowcount > 0


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


def export_csv(conn: sqlite3.Connection, path: str, kind: str = "other") -> int:
    """Write one kind of `model` row back out as reference_prices.csv's exact
    column format (pattern,label,original_price_eur,specs,score,
    better_than_baseline), so racefiets_jev.load_reference_data() — and
    therefore reference_overview.py and check_reference_overlaps.py — can
    still read it. Returns the number of rows written.

    The kind filter is the point, not a detail: `model` is one table for
    speakers, bikes, groupsets and accessories alike, while
    reference_prices.csv is read as one flat list of patterns matched against
    whatever query is running. Exporting every kind at once would put a
    "Giant Defy" pattern in the same file as the speaker rows, where it gets
    matched against speaker titles. Fase 7 adds bike rows, so each kind needs
    its own file."""
    rows = conn.execute(
        "SELECT pattern, model, original_price_eur, specs_json, score FROM model "
        "WHERE kind = ? ORDER BY id",
        (kind,),
    ).fetchall()

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["pattern", "label", "original_price_eur", "specs", "score", "better_than_baseline"]
        )
        for row in rows:
            try:
                extra = json.loads(row["specs_json"] or "{}")
            except json.JSONDecodeError:
                print(
                    f"warning: specs_json van {row['model']!r} is niet te lezen; "
                    "specs en better_than_baseline blijven leeg.",
                    file=sys.stderr,
                )
                extra = {}
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
