"""Het schema van koopjes.db: één migratie per versie, op volgorde. db.py
past ze toe (db.connect()); dit bestand is alleen de SQL.

Een migratie maakt tabellen en voegt geen kolommen aan een bestaande tabel
toe: tests zetten de database terug met DROP TABLE (tests/helpers.roll_back()),
en een ALTER TABLE ... ADD COLUMN laat zich zo niet terugdraaien.
"""

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
    # 14: two things the live dashboard's "controleer" button (recheck.py)
    # needs. bid_high: the highest bid a lookup found. Without it a MIN_BID
    # whose price a bid above the asking price had replaced looked like one
    # still at its asking price, and a Suunto asking €290 with €350 bid on it
    # was shown as "vraagprijs, bieden kan". Kept like bid_count: until the
    # next lookup. checked_at: when that button last read the listing's own
    # page. Not last_seen, which is when a crawl saw it — the dashboard dates
    # its rounds and its "nieuw" by that.
    """
    ALTER TABLE listing ADD COLUMN bid_high REAL;
    ALTER TABLE listing ADD COLUMN checked_at TEXT;
    """,
    # 15: a note on any listing, not only a marked one. A note is about the
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
    # 16: which listings the owner took along as comparables for the
    # valuation of his own bike ("mee") or ruled out ("niet"), on the live
    # page /fiets (bike_comps.py). The "Defy" line covers aluminium,
    # Composite, Advanced, Pro, SL and disc bikes from 2009 to now, and no
    # rule on title words tells them apart as well as he does by looking.
    # Only "mee" counts in the valuation; no row = not looked at yet. Kept
    # apart from listing_mark: a favourite is a bike he might buy, a
    # comparable is a bike like the one he sells.
    """
    CREATE TABLE comp_choice (
        item_id TEXT PRIMARY KEY,
        choice TEXT NOT NULL,
        chosen_at TEXT NOT NULL
    );
    """,
    # 17: the flip page /flips (flips.py). A bike flip is more than a buy and
    # a sale: parts bought for it, work done on it, travel to pick it up,
    # hours, a target price, bids from buyers, photos. Those hang off
    # `trade` (table `flip`, one row per trade that has any of it), so the
    # totals on /flips and Mijn flips count the same buys. Own tables rather
    # than columns on `trade`, so a test can roll this migration back with
    # DROP TABLE (a dropped column needs SQLite 3.35). trade.market gets two
    # keys that are no dashboard ("fietsen", "spullen"); _with_trades() in
    # dashboard.py leaves those out. No `flip` row, or stage NULL: a
    # computer bought off a dashboard — sold or not says enough there.
    # trade_stage keeps when each stage began, for "staat 12 dagen te koop".
    # flip_task.trade_id NULL is a tool bought for no bike in particular:
    # the "investeringen" pot, which counts against the total but not
    # against any one flip; investment = 1 does the same for a tool on a
    # bike's list. A task is soft-deleted (deleted_at) so the Google Sheet
    # sync (flips_sheets.py) can tell a deleted row from one it hasn't seen
    # yet. updated_at is what "last change wins" compares against the sheet.
    """
    CREATE TABLE flip (
        trade_id INTEGER PRIMARY KEY,
        stage TEXT,
        target_low_eur REAL,
        target_high_eur REAL,
        hours REAL,
        specs_json TEXT,
        sale_url TEXT,
        comp_words TEXT,
        updated_at TEXT
    );

    CREATE TABLE trade_stage (
        id INTEGER PRIMARY KEY,
        trade_id INTEGER NOT NULL,
        stage TEXT NOT NULL,
        at TEXT NOT NULL
    );

    CREATE TABLE flip_task (
        id INTEGER PRIMARY KEY,
        trade_id INTEGER,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        shop TEXT,
        url TEXT,
        est_eur REAL,
        price_eur REAL,
        price_source TEXT,
        investment INTEGER NOT NULL DEFAULT 0,
        fare_eur REAL,
        discount TEXT,
        bought_at TEXT,
        done_at TEXT,
        position INTEGER NOT NULL DEFAULT 0,
        notes TEXT,
        updated_at TEXT NOT NULL,
        deleted_at TEXT
    );

    CREATE TABLE flip_bid (
        id INTEGER PRIMARY KEY,
        trade_id INTEGER NOT NULL,
        amount_eur REAL NOT NULL,
        at TEXT NOT NULL,
        note TEXT
    );

    CREATE TABLE flip_photo (
        id INTEGER PRIMARY KEY,
        trade_id INTEGER NOT NULL,
        file TEXT NOT NULL,
        kind TEXT NOT NULL,
        added_at TEXT NOT NULL
    );
    """,
    # 18: four things for the live racefiets page and the distance filter.
    # `listing_place`: where the seller is (latitude/longitude, as the search
    # results give it; distance.py measures from the owner's postcode), and
    # a Dagtopper and the other paid extras from the same results
    # (promotion/traits), so views.py can tell whether they buy views. Its
    # own table rather than columns on `listing`, for the reason 17 gives: a
    # test rolls a migration back with DROP TABLE. `setting`: the owner's
    # postcode and its coordinates — personal, so in the database and not in
    # a file in git. `own_bid`: the bids the owner placed himself on
    # Marktplaats (own_bids.py), every one of them, with the status of the
    # latest; an accepted one becomes a trade (trade_id). The script never
    # bids itself. `listing_stats`: views and saves from a listing's own
    # page, one row per look (views.py), so how they grow can be followed.
    # Raw observations like listing_price; item_id without a foreign key,
    # since an own ad on /flips need not be in `listing`.
    """
    CREATE TABLE listing_place (
        item_id TEXT PRIMARY KEY,
        latitude REAL,
        longitude REAL,
        promotion TEXT,
        traits TEXT
    );

    CREATE TABLE setting (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE own_bid (
        id INTEGER PRIMARY KEY,
        item_id TEXT NOT NULL,
        amount_eur REAL NOT NULL,
        bid_at TEXT NOT NULL,
        status TEXT NOT NULL,
        status_at TEXT NOT NULL,
        trade_id INTEGER
    );
    CREATE INDEX own_bid_item ON own_bid (item_id);

    CREATE TABLE listing_stats (
        id INTEGER PRIMARY KEY,
        item_id TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        views INTEGER,
        favorites INTEGER,
        online_since TEXT,
        price_eur REAL,
        source TEXT NOT NULL,
        UNIQUE (item_id, observed_at)
    );
    CREATE INDEX listing_stats_item ON listing_stats (item_id);
    """,
    # 19: fietsmodellen die de eigenaar zelf aanmaakt, en zijn eigen koppeling
    # van een advertentie aan een model (bike_identity.py, /racefietsen). De
    # herkenning uit de titel gaat vaak goed maar niet altijd, en een model
    # dat nergens in een lijst staat kon je niet toevoegen (de eigenaar,
    # 01-10-2026). bike_link: model_id NULL met alleen een jaar = "het model
    # klopt, dit is het bouwjaar"; confirmed = "klopt" geklikt, voor het
    # leren van regels later. Eigen tabellen, geen kolommen (zie 17).
    """
    CREATE TABLE bike_model (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        brand TEXT,
        family TEXT,
        variant TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE bike_link (
        item_id TEXT PRIMARY KEY,
        model_id INTEGER,
        year INTEGER,
        confirmed INTEGER NOT NULL DEFAULT 0,
        set_at TEXT NOT NULL
    );
    """,
    # 20: regels die de eigenaar goedkeurde: "advertenties die als from_key
    # herkend worden, horen bij dit eigen model" (/racefietsen, Modellen). Na
    # drie dezelfde correcties stelt de pagina er een voor; applied = 0 is
    # "nee", onthouden zodat hij het niet opnieuw vraagt. Een eigen koppeling
    # per advertentie (bike_link) gaat nog altijd voor. Eigen tabel (zie 17).
    """
    CREATE TABLE bike_rule (
        id INTEGER PRIMARY KEY,
        from_key TEXT NOT NULL,
        from_name TEXT,
        model_id INTEGER NOT NULL,
        applied INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (from_key, model_id)
    );
    """,
    # 21: aanbiedingen bij een regel van de klussenlijst (/flips): een link die
    # de eigenaar plakt met de prijs die hij zag, zodat hij per onderdeel
    # winkels naast elkaar ziet en er een kiest
    # (opdrachten/goedkoopste_onderdelen.md, deel B). De prijs tikt hij zelf
    # in; het script haalt niets van een winkelpagina. url mag leeg zijn als
    # er een notitie staat (AliExpress uit de app: winkel + zoekterm).
    # source: gecontroleerd (de eigenaar zag de prijs) of schatting (een prijs
    # uit onderzoek die niet te openen was, zoals bij AliExpress).
    """
    CREATE TABLE flip_offer (
        id INTEGER PRIMARY KEY,
        task_id INTEGER NOT NULL,
        url TEXT,
        shop TEXT,
        price_eur REAL NOT NULL,
        shipping_eur REAL,
        note TEXT,
        source TEXT NOT NULL DEFAULT 'gecontroleerd',
        checked_at TEXT,
        added_at TEXT NOT NULL,
        deleted_at TEXT
    );
    CREATE INDEX flip_offer_task ON flip_offer (task_id);
    """,
    # 22: de upgradetest (/upgrade, upgrade_test.py): per fiets het oordeel
    # van de eigenaar of hij een upgrade is van zijn eigen fiets, los van
    # prijs en maat — ja, nee of twijfel. Daarmee ziet hij hoeveel van zijn
    # antwoorden de score goed heeft en zoekt de pagina een regel die erbij
    # past (de eigenaar, 05-10-2026: "zodat ik zelf kan bepalen wat een
    # upgrade is"). Titel en prijs zoals hij ze zag. Eigen tabel (zie 17).
    """
    CREATE TABLE upgrade_label (
        item_id TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        title TEXT,
        price_eur REAL,
        labeled_at TEXT NOT NULL
    );
    """,
]
