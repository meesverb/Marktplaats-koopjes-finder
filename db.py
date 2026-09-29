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
from typing import Optional

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
    # 2: which queries found a listing, not just the last one. listing.query
    # is overwritten by every run that sees the listing, so with a day run on
    # "racefiets" and a nightly full crawl of "giant defy", a Defy last seen
    # by the day run was never considered by the nightly sweep — and a sold
    # Defy was never counted as sold. The sweep and the --query filters of
    # valuation.py/upgrade.py read this table instead. listing.query stays
    # (last query that saw it), so nothing that reads it breaks.
    """
    CREATE TABLE listing_query (
        listing_id TEXT NOT NULL REFERENCES listing(item_id),
        query TEXT NOT NULL,
        first_seen TEXT,
        last_seen TEXT,
        PRIMARY KEY (listing_id, query)
    );
    INSERT INTO listing_query (listing_id, query, first_seen, last_seen)
        SELECT item_id, query, first_seen, last_seen FROM listing WHERE query IS NOT NULL;
    """,
    # 3: whether price_eur is an asking price. is_bid alone can't say: a
    # MIN_BID listing is a bid listing whose search-result price is still the
    # seller's asking price, and that's over half of the Defy market. The
    # valuation used to drop every is_bid row for that reason. NULL = written
    # before this column existed; the next crawl that sees the listing fills
    # it in, and until then it's treated as before (is_bid decides).
    """
    ALTER TABLE listing ADD COLUMN price_is_asking INTEGER;
    """,
    # 4: a listing a nearly complete full crawl didn't see. One miss isn't
    # proof it's gone (see racefiets_jev.near_complete_max_missing); a
    # second full crawl that misses it too is, and then it's marked
    # disappeared as of this first miss. Any crawl that sees it clears it.
    """
    ALTER TABLE listing ADD COLUMN missed_at TEXT;
    """,
    # 5: the full description from the listing's own page, for the few
    # listings --detail-lookup fetched, and when. The search results stop at
    # 200 characters; `description` keeps holding that snippet (sleepers and
    # the report are about what the search shows), this column holds the
    # rest, and a listing that has it is never fetched again.
    """
    ALTER TABLE listing ADD COLUMN full_description TEXT;
    ALTER TABLE listing ADD COLUMN details_fetched_at TEXT;
    """,
    # 6: the photo URLs from the search results (Listing.image_urls,
    # space-separated). The dashboard (dashboard.py) is built from the
    # database, not from a run, and a thumbnail is how you tell a Garmin
    # from a Garmin holder at a glance.
    """
    ALTER TABLE listing ADD COLUMN image_urls TEXT;
    """,
    # 7: the owner's own buys and sales ("Mijn flips" in dashboard.py). What
    # he actually paid and got, not a market observation: kept out of
    # `listing`/`listing_price`, and never used as a comparable. item_id and
    # url point at the listing he bought from, if it was on Marktplaats (a
    # Vinted buy has neither). expected_resale_eur is what the dashboard
    # expected when he bought, so its estimate can be checked afterwards.
    """
    CREATE TABLE trade (
        id INTEGER PRIMARY KEY,
        item_id TEXT,
        url TEXT,
        title TEXT NOT NULL,
        model TEXT,
        bought_at TEXT NOT NULL,
        buy_price_eur REAL NOT NULL,
        buy_costs_eur REAL NOT NULL DEFAULT 0,
        expected_resale_eur REAL,
        sold_at TEXT,
        sell_price_eur REAL,
        sell_costs_eur REAL NOT NULL DEFAULT 0,
        sold_via TEXT,
        notes TEXT,
        created_at TEXT NOT NULL
    );
    """,
    # 8: Vinted exports (vinted.py). Kept out of `listing` for three reasons:
    # an export is a search the owner ran in his browser, not a complete
    # crawl, so sweep_disappeared() must never mark anything in it as gone; a
    # Vinted price must never become a comparable for a Marktplaats flip
    # (db_comparables() reads `listing` only); and Vinted doesn't search
    # within a category, so watches, trainers and clothing come along too.
    # fee_eur is Vinted's buyer protection as the export states it (EUR 0.70
    # + 5% on 28-09-2026), stored as given rather than recomputed.
    """
    CREATE TABLE vinted_listing (
        item_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        price_eur REAL,
        fee_eur REAL,
        total_eur REAL,
        brand TEXT,
        size TEXT,
        condition TEXT,
        favorites INTEGER,
        url TEXT,
        image_url TEXT,
        seller_id TEXT,
        is_business INTEGER,
        first_exported_at TEXT NOT NULL,
        last_exported_at TEXT NOT NULL,
        export_file TEXT
    );

    CREATE TABLE vinted_price (
        item_id TEXT NOT NULL REFERENCES vinted_listing(item_id),
        exported_at TEXT NOT NULL,
        price_eur REAL NOT NULL,
        PRIMARY KEY (item_id, exported_at)
    );
    """,
    # 9: when a crawl first saw the listing marked "gereserveerd". The search
    # results say so (Listing.reserved), but the dashboard is built from this
    # table, so without the column a reserved Edge 530 stayed on the Flips
    # tab. It is also the nearest thing to "sold" Marktplaats shows: a
    # listing that disappears while reserved was almost certainly bought,
    # one that disappears without it may just have been withdrawn. Cleared
    # when a crawl sees the listing unreserved again (the buyer backed out).
    # NULL on rows from before this column: not seen reserved, which is all
    # anyone knew then.
    """
    ALTER TABLE listing ADD COLUMN reserved_at TEXT;
    """,
    # 10: which dashboard a buy belongs to — "fietscomputers" or
    # "sporthorloges" (markets.py). Each dashboard's Mijn flips shows its own
    # market, and values a stock item against that market's listings. NULL on
    # rows from before: markets.trade_market() then goes by the model name,
    # and without one they are bike computers, the only market there was.
    """
    ALTER TABLE trade ADD COLUMN market TEXT;
    """,
    # 11: what the bid lookup (--bid-lookup) found on the listing page: how
    # many bids, the minimum Marktplaats accepts, and when that was looked
    # up. Before this only the resulting price was stored, and a round
    # without lookups (the daytime rounds) wrote NULL over a FAST_BID's
    # price, so the running bid the night round had fetched was gone again
    # by 10:00. sync_listings() now keeps the last lookup until a new one.
    """
    ALTER TABLE listing ADD COLUMN bid_count INTEGER;
    ALTER TABLE listing ADD COLUMN bid_minimum REAL;
    ALTER TABLE listing ADD COLUMN bids_checked_at TEXT;
    """,
    # 12: the owner's own marks on a listing in the live dashboard (marks.py):
    # "favoriet", or "weg" with why ("niet waard", "gereserveerd"). His
    # judgement, not a market observation, so kept out of `listing` like
    # `trade` is: a listing he put away still counts as a comparable, since
    # its asking price is as real as any other. price_eur is the price when
    # he marked it; a put-away listing comes back once the price drops below
    # that. One mark per listing: a favourite he puts away is no longer one.
    """
    CREATE TABLE listing_mark (
        item_id TEXT PRIMARY KEY,
        mark TEXT NOT NULL,
        reason TEXT,
        price_eur REAL,
        marked_at TEXT NOT NULL
    );
    """,
    # 13: the owner's own note on a marked listing ("gevraagd of 120 kan",
    # "gereserveerd tot zaterdag"). A separate migration rather than a column
    # in 12, which had already shipped. It belongs to the mark: changing
    # favourite to put-away keeps it, removing the mark removes it.
    """
    ALTER TABLE listing_mark ADD COLUMN note TEXT;
    """,
    # 14: a note on any listing, not only a marked one. A note is about the
    # listing (what the seller said, what was offered), a mark is a verdict
    # on it; tied together, a note vanished with the mark and an unmarked
    # listing couldn't have one. The notes written under 13 move over, with
    # their mark's time as a best guess of when. 13's column stays behind,
    # emptied: dropping a column needs SQLite 3.35, and the Python on the
    # owner's Windows machine may bring an older one.
    """
    CREATE TABLE listing_note (
        item_id TEXT PRIMARY KEY,
        note TEXT NOT NULL,
        noted_at TEXT NOT NULL
    );
    INSERT INTO listing_note (item_id, note, noted_at)
        SELECT item_id, note, marked_at FROM listing_mark WHERE note IS NOT NULL AND note <> '';
    UPDATE listing_mark SET note = NULL;
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
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _migrate(conn)
    except BaseException:
        # A refused or failed migration would otherwise leave the file open,
        # and on Windows an open file can't be moved or deleted until the
        # process exits.
        conn.close()
        raise
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
    back. reserved_at keeps the first sighting of a reservation, and goes
    back to NULL once a crawl sees the listing unreserved (migration 9).

    Bids (migration 11): a listing looked up this run (bid_count set) stores
    what the lookup found. One that wasn't keeps the last lookup — and, if
    the search results give no price of their own (a FAST_BID), the price
    that lookup gave, instead of NULL. A later lookup replaces both."""
    for listing in listings:
        looked_up = getattr(listing, "bid_count", None) is not None
        conn.execute(
            """
            INSERT INTO listing (item_id, title, description, price_eur, price_type, is_bid,
                                  price_is_asking, city, posted_date, condition,
                                  frame_height, url, query, first_seen, last_seen, image_urls,
                                  reserved_at, bid_count, bid_minimum, bids_checked_at)
            VALUES (:item_id, :title, :description, :price_eur, :price_type, :is_bid,
                    :price_is_asking, :city, :posted_date, :condition,
                    :frame_height, :url, :query, :first_seen, :last_seen, :image_urls,
                    :reserved_at, :bid_count, :bid_minimum, :bids_checked_at)
            ON CONFLICT(item_id) DO UPDATE SET
                title = excluded.title,
                description = excluded.description,
                price_eur = CASE WHEN excluded.price_eur IS NULL AND excluded.bids_checked_at IS NULL
                                      AND listing.bids_checked_at IS NOT NULL
                                      AND excluded.price_type = listing.price_type
                                 THEN listing.price_eur ELSE excluded.price_eur END,
                is_bid = CASE WHEN excluded.price_eur IS NULL AND excluded.bids_checked_at IS NULL
                                   AND listing.bids_checked_at IS NOT NULL
                                   AND excluded.price_type = listing.price_type
                              THEN listing.is_bid ELSE excluded.is_bid END,
                price_is_asking = CASE WHEN excluded.price_eur IS NULL AND excluded.bids_checked_at IS NULL
                                            AND listing.bids_checked_at IS NOT NULL
                                            AND excluded.price_type = listing.price_type
                                       THEN listing.price_is_asking ELSE excluded.price_is_asking END,
                bid_count = CASE WHEN excluded.bids_checked_at IS NULL
                                 THEN listing.bid_count ELSE excluded.bid_count END,
                bid_minimum = CASE WHEN excluded.bids_checked_at IS NULL
                                   THEN listing.bid_minimum ELSE excluded.bid_minimum END,
                bids_checked_at = COALESCE(excluded.bids_checked_at, listing.bids_checked_at),
                city = excluded.city,
                posted_date = excluded.posted_date,
                condition = excluded.condition,
                -- A frame height read from the listing page (--detail-lookup)
                -- isn't in the search results, so a later run would blank it.
                frame_height = COALESCE(NULLIF(excluded.frame_height, ''), listing.frame_height),
                url = excluded.url,
                query = excluded.query,
                image_urls = COALESCE(NULLIF(excluded.image_urls, ''), listing.image_urls),
                reserved_at = CASE WHEN excluded.reserved_at IS NULL THEN NULL
                                   ELSE COALESCE(listing.reserved_at, excluded.reserved_at) END,
                last_seen = excluded.last_seen,
                disappeared_at = NULL,
                days_online = NULL,
                missed_at = NULL
            """,
            {
                "item_id": listing.item_id,
                "title": listing.title,
                "description": listing.description,
                "price_eur": listing.price_eur,
                "price_type": listing.price_type,
                "is_bid": 1 if listing.price_is_bid else 0,
                "price_is_asking": 1 if listing.price_is_asking else 0,
                "city": listing.city,
                "posted_date": listing.date,
                "condition": listing.condition,
                "frame_height": listing.frame_height,
                "url": listing.url,
                "query": query,
                "first_seen": listing.first_seen or observed_at,
                "last_seen": observed_at,
                "image_urls": getattr(listing, "image_urls", "") or "",
                "reserved_at": observed_at if getattr(listing, "reserved", False) else None,
                "bid_count": getattr(listing, "bid_count", None),
                "bid_minimum": getattr(listing, "bid_minimum", None),
                "bids_checked_at": observed_at if looked_up else None,
            },
        )
        conn.execute(
            """
            INSERT INTO listing_query (listing_id, query, first_seen, last_seen)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(listing_id, query) DO UPDATE SET last_seen = excluded.last_seen
            """,
            (listing.item_id, query, observed_at, observed_at),
        )
        if listing.price_eur is not None:
            conn.execute(
                "INSERT OR IGNORE INTO listing_price (item_id, observed_at, price_eur) "
                "VALUES (?, ?, ?)",
                (listing.item_id, observed_at, listing.price_eur),
            )
    conn.commit()


# The `spec` source for Marktplaats' own structured attributes
# (racefiets_jev.site_specs()), next to "regex" for what the text says. Where
# both have a key the text wins: see read_listing_specs().
SITE_SPEC_SOURCE = "marktplaats"


def read_listing_specs(conn: sqlite3.Connection, source: str | None = None) -> dict:
    """{listing_id: {key: value}} from `spec`, every source merged with the
    text ("regex") winning — the same order as racefiets_jev.listing_spec_dict(),
    so a listing read back from the database scores as it did live. With
    `source`, only that source."""
    if source is not None:
        rows = conn.execute(
            "SELECT listing_id, key, value FROM spec WHERE source = ?", (source,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT listing_id, key, value FROM spec "
            "ORDER BY CASE source WHEN 'regex' THEN 1 ELSE 0 END"
        ).fetchall()
    specs: dict = {}
    for row in rows:
        specs.setdefault(row["listing_id"], {})[row["key"]] = row["value"]
    return specs


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


def save_listing_details(conn: sqlite3.Connection, details: dict, fetched_at: str) -> None:
    """{item_id: full description} from the listing pages fetched this run.
    Call after sync_listings(), which creates the rows."""
    for item_id, text in details.items():
        conn.execute(
            "UPDATE listing SET full_description = ?, details_fetched_at = ? WHERE item_id = ?",
            (text, fetched_at, item_id),
        )
    conn.commit()


def load_listing_details(conn: sqlite3.Connection, item_ids) -> dict:
    """{item_id: (full description, frame height)} for the listings among
    `item_ids` whose page was fetched on an earlier run."""
    found = {}
    for item_id in item_ids:
        row = conn.execute(
            "SELECT full_description, frame_height FROM listing "
            "WHERE item_id = ? AND details_fetched_at IS NOT NULL",
            (item_id,),
        ).fetchone()
        if row is not None:
            found[item_id] = (row["full_description"] or "", row["frame_height"] or "")
    return found


def sweep_disappeared(
    conn: sqlite3.Connection,
    query: str,
    seen_item_ids,
    observed_at: str,
    *,
    confirmed: bool = True,
    report_missed: bool = False,
):
    """Mark every listing `query` ever found (listing_query, not the
    overwritten listing.query) that isn't in `seen_item_ids` and isn't
    already marked as disappeared. Call this only after a full crawl
    (`--pages 0`) of that exact query — a shallow crawl only sees the first
    few pages, and would otherwise mark everything past that depth as gone.

    `confirmed=False` is for a crawl that was complete but for a few (see
    racefiets_jev.near_complete_max_missing): an unseen listing only gets a
    `missed_at`, unless an earlier full crawl already missed it — then it's
    gone. A listing marked disappeared is dated from its first miss, the
    earliest the crawls knew it was gone.

    Returns how many rows were newly marked disappeared; with
    `report_missed`, (newly missed, newly disappeared)."""
    rows = conn.execute(
        "SELECT l.item_id, l.first_seen, l.missed_at FROM listing l "
        "JOIN listing_query lq ON lq.listing_id = l.item_id "
        "WHERE lq.query = ? AND l.disappeared_at IS NULL",
        (query,),
    ).fetchall()

    count = 0
    missed = 0
    for row in rows:
        if row["item_id"] in seen_item_ids:
            continue
        if not confirmed and not row["missed_at"]:
            conn.execute(
                "UPDATE listing SET missed_at = ? WHERE item_id = ?", (observed_at, row["item_id"])
            )
            missed += 1
            continue
        gone_at = row["missed_at"] or observed_at
        days_online = None
        first_seen = row["first_seen"]
        if first_seen:
            try:
                delta = _parse_iso(gone_at) - _parse_iso(first_seen)
                days_online = delta.days
            except ValueError:
                days_online = None
        conn.execute(
            "UPDATE listing SET disappeared_at = ?, days_online = ?, missed_at = NULL "
            "WHERE item_id = ?",
            (gone_at, days_online, row["item_id"]),
        )
        count += 1
    conn.commit()
    return (missed, count) if report_missed else count


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


# --- Own trades (migration 7) --------------------------------------------------


def add_trade(
    conn: sqlite3.Connection,
    *,
    title: str,
    bought_at: str,
    buy_price_eur: float,
    buy_costs_eur: float = 0.0,
    item_id: Optional[str] = None,
    url: Optional[str] = None,
    model: Optional[str] = None,
    expected_resale_eur: Optional[float] = None,
    notes: str = "",
    market: Optional[str] = None,
) -> int:
    """Record a buy; returns its id. `market` is the dashboard it was bought
    from (markets.py); None for a caller that doesn't know."""
    cur = conn.execute(
        """
        INSERT INTO trade (item_id, url, title, model, bought_at, buy_price_eur, buy_costs_eur,
                           expected_resale_eur, notes, created_at, market)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (item_id, url, title, model, bought_at, buy_price_eur, buy_costs_eur,
         expected_resale_eur, notes, datetime.now(timezone.utc).isoformat(timespec="seconds"), market),
    )
    conn.commit()
    return cur.lastrowid


def sell_trade(
    conn: sqlite3.Connection,
    trade_id: int,
    *,
    sold_at: str,
    sell_price_eur: float,
    sell_costs_eur: float = 0.0,
    sold_via: str = "",
) -> bool:
    """Mark a buy as sold; returns whether the trade exists. Selling again
    overwrites: a typo in the price is corrected by entering it again."""
    cur = conn.execute(
        "UPDATE trade SET sold_at = ?, sell_price_eur = ?, sell_costs_eur = ?, sold_via = ? WHERE id = ?",
        (sold_at, sell_price_eur, sell_costs_eur, sold_via, trade_id),
    )
    conn.commit()
    return cur.rowcount > 0


def unsell_trade(conn: sqlite3.Connection, trade_id: int) -> bool:
    """Back to stock (a sale that fell through)."""
    cur = conn.execute(
        "UPDATE trade SET sold_at = NULL, sell_price_eur = NULL, sell_costs_eur = 0, sold_via = NULL "
        "WHERE id = ?",
        (trade_id,),
    )
    conn.commit()
    return cur.rowcount > 0


def delete_trade(conn: sqlite3.Connection, trade_id: int) -> bool:
    cur = conn.execute("DELETE FROM trade WHERE id = ?", (trade_id,))
    conn.commit()
    return cur.rowcount > 0


def list_trades(conn: sqlite3.Connection) -> list[dict]:
    """All trades, oldest buy first. Empty on a database from before
    migration 7 opened read-only (the dashboard does that)."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'trade'"
    ).fetchone()
    if not exists:
        return []
    cur = conn.execute("SELECT * FROM trade ORDER BY bought_at, id")
    names = [c[0] for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


# --- Own marks on listings (migration 12) --------------------------------------


def set_mark(
    conn: sqlite3.Connection,
    item_id: str,
    mark: str,
    *,
    reason: Optional[str] = None,
    price_eur: Optional[float] = None,
) -> None:
    """Mark a listing, replacing any earlier mark. Marking again also resets
    price_eur and marked_at: putting a listing away again after its price
    dropped means "not even at this price"."""
    conn.execute(
        """
        INSERT INTO listing_mark (item_id, mark, reason, price_eur, marked_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(item_id) DO UPDATE SET
            mark = excluded.mark, reason = excluded.reason,
            price_eur = excluded.price_eur, marked_at = excluded.marked_at
        """,
        (item_id, mark, reason, price_eur, datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    conn.commit()


def clear_mark(conn: sqlite3.Connection, item_id: str) -> bool:
    cur = conn.execute("DELETE FROM listing_mark WHERE item_id = ?", (item_id,))
    conn.commit()
    return cur.rowcount > 0


def list_marks(conn: sqlite3.Connection) -> list[dict]:
    """All marks, with what `listing` knows of the listing now (title, url,
    price, whether it disappeared) so a favourite that went offline can still
    be shown. Empty on a database from before migration 12 opened read-only
    (the dashboard does that)."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'listing_mark'"
    ).fetchone()
    if not exists:
        return []
    cur = conn.execute(
        """
        SELECT m.item_id, m.mark, m.reason, m.price_eur, m.marked_at,
               l.title, l.url, l.price_eur AS current_price_eur, l.last_seen, l.disappeared_at
        FROM listing_mark m LEFT JOIN listing l ON l.item_id = m.item_id
        ORDER BY m.marked_at, m.item_id
        """
    )
    names = [c[0] for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


# --- Own notes on listings (migration 14) --------------------------------------


def set_note(conn: sqlite3.Connection, item_id: str, note: Optional[str]) -> None:
    """Set the owner's note on a listing; None or "" removes it."""
    if note:
        conn.execute(
            """
            INSERT INTO listing_note (item_id, note, noted_at) VALUES (?, ?, ?)
            ON CONFLICT(item_id) DO UPDATE SET note = excluded.note, noted_at = excluded.noted_at
            """,
            (item_id, note, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
    else:
        conn.execute("DELETE FROM listing_note WHERE item_id = ?", (item_id,))
    conn.commit()


def list_notes(conn: sqlite3.Connection) -> dict[str, str]:
    """{item_id: note}. On a database from before migration 14 opened
    read-only, the notes 13 kept on marks, so they don't seem lost until the
    next round or --serve migrates; before 13, none."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "listing_note" in tables:
        return dict(conn.execute("SELECT item_id, note FROM listing_note").fetchall())
    if "listing_mark" in tables and any(r[1] == "note" for r in conn.execute("PRAGMA table_info(listing_mark)")):
        return dict(conn.execute("SELECT item_id, note FROM listing_mark WHERE note IS NOT NULL AND note <> ''"))
    return {}


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
