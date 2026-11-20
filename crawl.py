"""Alles wat Marktplaats leest: de advertentie (`Listing`), de zoekpagina's
ophalen (`collect_listings()`, `collect_split()` voor een hele categorie),
biedingen ophalen en toepassen, de advertentiepagina lezen, specs en
groepset uit de tekst halen, categorieën, en een rij uit koopjes.db terug
als `Listing` (`listing_from_row()`).

Hangt van niets anders in deze repo af dan db.py, computers.py en
sleepers.py, zodat elke laag erboven (het rapport, de taxatie, de pagina's)
hem kan gebruiken zonder racefiets_jev.py, het commando, te importeren.

Marktplaats kan zijn paginastructuur wijzigen: wat hier breekt, zegt dat
hardop (warn_bid_structure_changed(), ListingPageError) in plaats van stil
door te gaan.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import sys
import time
from dataclasses import dataclass, field, fields as dataclass_fields
from functools import lru_cache
from typing import Optional, Sequence
from urllib.parse import quote_plus, urlencode

import requests



BASE_URL = "https://www.marktplaats.nl"


DEFAULT_QUERY = "racefiets"


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)


@dataclass
class Listing:
    item_id: str
    title: str
    description: str
    price_eur: Optional[float]
    price_type: str
    city: str
    date: str
    condition: str
    frame_height: str
    groupset: str
    groupset_tier: Optional[int]
    url: str
    is_bargain: bool = False
    price_is_bid: bool = False
    is_new: bool = False
    first_seen: str = ""
    ref_label: str = ""
    ref_original_price: Optional[float] = None
    ref_score: str = ""
    ref_pct_of_original: Optional[float] = None
    ref_specs: str = ""
    ref_better: bool = False
    ref_market_avg: Optional[float] = None
    ref_market_count: int = 0
    pct_of_median: Optional[float] = None
    price_dropped: bool = False
    price_drop_from: Optional[float] = None
    # Counts usable bids only (see usable_bid_values()) — the same count
    # resolve_bid_price() bases the price on, so a listing's price and its
    # bid_count never tell two different stories about the same raw list.
    # None (lookup never ran) and 0 (ran, nothing usable) are not the same.
    bid_count: Optional[int] = None
    bid_minimum: Optional[float] = None
    bid_minimum_pct_of_median: Optional[float] = None
    bid_open: bool = False
    deal_score: Optional[float] = None
    deal_label: str = ""
    deal_reasons: str = ""
    # Added after the fields above, at the very end, so the CSV output and
    # bargain log only gain columns (see append_bargain_log). The sleeper
    # signal (sleepers.py) is its own thing, not part of deal_score.
    thin_content: bool = False
    reserved: bool = False
    # Up to SEARCH_IMAGES photo URLs from the search results, space-separated.
    image_urls: str = ""
    sleeper_score: Optional[float] = None
    sleeper_reasons: str = ""
    # Specs from Marktplaats' own structured attributes (see site_specs()),
    # in extract_specs()' vocabulary. Not a CSV column (metadata): it's a
    # dict, and a new column would warn on every existing bargains log.
    site_specs: dict = field(default_factory=dict, metadata={"csv": False})
    # The full description from the listing's own page, for the few listings
    # --detail-lookup fetched (see lookup_listing_details()). Empty otherwise;
    # `description` stays the search snippet either way.
    detail_text: str = field(default="", metadata={"csv": False})
    # computers.ComputerSignal when the title names a known bike computer
    # (computers.py). Not a CSV column, same reason as site_specs.
    computer: Optional[object] = field(default=None, metadata={"csv": False})
    # The highest usable bid the last bid lookup found (apply_bid_info()).
    # A MIN_BID whose price is a bid above the asking price reads the same as
    # one still at its asking price without it. Not a CSV column, same
    # reason as site_specs.
    bid_high: Optional[float] = field(default=None, metadata={"csv": False})
    # Where the seller is (search_location()): for the distance filter in
    # the dashboards (distance.py). None when Marktplaats only knows the
    # country. Not CSV columns, same reason as site_specs.
    latitude: Optional[float] = field(default=None, metadata={"csv": False})
    longitude: Optional[float] = field(default=None, metadata={"csv": False})
    # Paid promotion as the search results give it: priorityProduct
    # ("DAGTOPPER", "" for NONE) and the traits ("DAG_TOPPER_7DAYS
    # PACKAGE_PREMIUM ..."). For views.py: does a Dagtopper get more views?
    promotion: str = field(default="", metadata={"csv": False})
    traits: str = field(default="", metadata={"csv": False})
    # Views and saves from the listing's own page (views.page_stats()), when
    # this run fetched that page anyway (bid or detail lookup). sync_listings()
    # stores it in listing_stats.
    page_stats: Optional[dict] = field(default=None, metadata={"csv": False})

    @property
    def price_is_asking(self) -> bool:
        """Whether price_eur is what the seller asks, not a bid caught
        mid-auction. A MIN_BID price from the search results is the asking
        price, and a bid listing nobody has bid on yet keeps its seller's
        floor; only once bids are in can the price be the highest bid (that's
        when enrich_bid_listings() replaces it), so from then on it isn't
        trusted as an asking price. A property, not a field: a field would
        add a column to every existing bargains log."""
        return self.price_eur is not None and not (self.price_is_bid and self.bid_count)


LISTING_FIELDS = [f.name for f in dataclass_fields(Listing) if f.metadata.get("csv", True)]


def as_number(value) -> Optional[float]:
    """A number out of Marktplaats' JSON, or None when the field holds
    something else. Two shapes get through a plain isinstance check: a bool
    (True is an int in Python, so a stray "priceCents": true would read as one
    cent) and a number sent as a string, which then blows up on the division
    that follows. Neither shows up in the console, so both are cheap to
    exclude here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


PAGE_SIZE = 30


# The search API the site's own "sorteer op"/category menus call. The HTML
# page ignores sort parameters in its URL (tested: ?sortBy=... and the #sortBy
# fragment both come back unsorted), so sorting by date and restricting to a
# category server-side can only go through here.
SEARCH_API_PATH = "/lrp/api/search"


SORT_OPTIONS = {
    # Marktplaats' default ("Standaard"). Not by date: on a 40-page crawl of
    # "racefiets" today's listings were spread over all 40 pages, only 83 of
    # 314 on the first three — and 1200 result slots held just 951 distinct
    # listings, the rest repeats.
    "optimized": ("OPTIMIZED", "DECREASING"),
    "newest": ("SORT_INDEX", "DECREASING"),
}


class CrawlResult(list):
    """collect_listings()'s listings, plus whether the crawl provably saw
    every result for the query. Only then may the disappearance sweep treat
    "not seen" as "gone": Marktplaats stops paging at maxAllowedPageNumber
    (167 pages, ~5000 listings, for "racefiets" with 26000+ results), and a
    page that fails to load ends the crawl early."""

    def __init__(
        self,
        listings=(),
        complete: bool = False,
        note: str = "",
        near_complete: bool = False,
        cut_off_ids: tuple = (),
    ):
        super().__init__(listings)
        self.complete = complete
        self.note = note
        # Every page loaded and paging ran to the end, but a handful of the
        # total went unseen — see NEAR_COMPLETE_MAX_MISSING.
        self.near_complete = near_complete
        # The item ids of the last page, in page order, when the crawl
        # stopped at --pages while Marktplaats had more; empty otherwise.
        # See window_too_small().
        self.cut_off_ids = cut_off_ids


# A full crawl takes a few seconds per page, and a listing that is sold or
# withdrawn in the meantime shifts every later one up a place: the one at the
# top of the next page lands on a page already fetched, and goes unseen. On
# 27-09-2026 "giant defy" saw 164 of 165 that way; the crawl right after it
# saw 164 of 164. Calling such a crawl incomplete skipped the disappearance
# sweep on exactly the event it exists to measure. A few missing of an
# otherwise whole crawl is therefore "near complete": the sweep only notes
# what it missed, and a listing counts as gone once a second full crawl
# misses it too (db.sweep_disappeared). The page cap and the default sort's
# repeats lose far more than this (thousands, or ~20%).
def near_complete_max_missing(total: float) -> int:
    return max(3, int(total * 0.02))


def check_page_offset(data: dict, page: int) -> None:
    """Marktplaats answers a page it doesn't like by redirecting to page 1
    rather than with an error — that's how every multi-word query used to
    get page 1 over and over. The response says which offset it served;
    refuse anything but the one asked for, so the crawl stops loudly instead
    of storing page 1 N times and calling it N pages."""
    pagination = (data.get("searchRequest") or {}).get("pagination") or {}
    offset = as_number(pagination.get("offset"))
    limit = as_number(pagination.get("limit")) or PAGE_SIZE
    if offset is not None and page > 1 and offset != (page - 1) * limit:
        raise RuntimeError(
            f"Marktplaats gaf offset {int(offset)} terug voor pagina {page} "
            f"(verwacht {(page - 1) * int(limit)}) — de paginering werkt niet meer zoals "
            "het script verwacht."
        )


def fetch_page(session: requests.Session, query: str, page: int) -> dict:
    """Fetch one Marktplaats search results page and return its embedded JSON data."""
    # The query goes into the URL *path*, so it has to be encoded as one.
    # requests leaves "?", "#" and "&" alone (they're legal in a URL, just not
    # in a path segment), so a query like "wat?" would turn into an empty
    # query string and a search for "wat". safe="" also catches a slash, which
    # would otherwise add a path segment. A space has to become "+", not
    # "%20": Marktplaats 301-redirects /q/giant%20defy/p/2/ to /q/giant+defy/
    # — page 1 — so every page of a multi-word query used to be page 1.
    quoted = quote_plus(query, safe="")
    path = f"/q/{quoted}/" if page <= 1 else f"/q/{quoted}/p/{page}/"
    resp = session.get(BASE_URL + path, timeout=15)
    resp.raise_for_status()

    match = NEXT_DATA_RE.search(resp.text)
    if not match:
        raise RuntimeError(
            "Could not find listing data on the page — Marktplaats may have "
            "changed its page structure or shown a verification challenge."
        )
    data = json.loads(match.group(1))
    result = data["props"]["pageProps"]["searchRequestAndResponse"]
    check_page_offset(result, page)
    return result


def fetch_api_page(
    session: requests.Session,
    query: str,
    page: int,
    sort: str = "optimized",
    category_filter: Optional[tuple[int, list[int]]] = None,
    extra: Sequence[tuple[str, object]] = (),
    limit: int = PAGE_SIZE,
    order: Optional[tuple[str, str]] = None,
) -> dict:
    """Like fetch_page(), through the search API: same response shape, but
    it honours a sort order and a server-side category restriction.
    category_filter is (l1 id, [l2 ids]) as resolve_categories() makes it."""
    sort_by, sort_order = order or SORT_OPTIONS[sort]
    params = [
        ("query", query),
        ("limit", limit),
        ("offset", (page - 1) * limit),
        ("sortBy", sort_by),
        ("sortOrder", sort_order),
    ]
    if category_filter is not None:
        l1, l2s = category_filter
        params.append(("l1CategoryId", l1))
        # Plural and repeated: "l2CategoryId" (singular) is silently ignored
        # and returns every category.
        params.extend(("l2CategoryIds", l2) for l2 in l2s)
    params.extend(extra)
    resp = session.get(BASE_URL + SEARCH_API_PATH + "?" + urlencode(params), timeout=15)
    resp.raise_for_status()
    try:
        data = json.loads(resp.text)
    except ValueError:
        data = None
    if not isinstance(data, dict) or "listings" not in data:
        raise RuntimeError(
            "De zoek-API van Marktplaats gaf geen advertentielijst terug — mogelijk is die "
            "gewijzigd of werd er een verificatie getoond. Draai zonder --sort/--category "
            "om de gewone zoekpagina te gebruiken."
        )
    check_page_offset(data, page)
    return data


CONFIG_MARKER = "window.__CONFIG__ = "


def extract_balanced_json(text: str, start: int) -> Optional[dict]:
    """Extract one JSON object starting at `start` (the opening '{'),
    respecting quoted strings, and return it parsed."""
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# Once the page structure changes, every single listing hits the same wall, so
# warn once per run instead of printing the same line a hundred times.
_bid_structure_warned = False


def warn_bid_structure_changed(detail: str) -> None:
    global _bid_structure_warned
    if _bid_structure_warned:
        return
    _bid_structure_warned = True
    print(
        f"warning: biedinformatie niet te lezen ({detail}) — Marktplaats heeft "
        "waarschijnlijk zijn paginastructuur gewijzigd. Biedprijzen en minimumbod "
        "blijven leeg; de rest van de run gaat gewoon door.",
        file=sys.stderr,
    )


def page_stats(listing_page: Optional[dict]) -> Optional[dict]:
    """Views and saves from a listing page's `listing` object (listing_page_data()):
    {"views": 158, "favorites": 4, "since": "2026-09-29T12:39:43Z"}. Only on
    the page itself, not in the search results (checked 29-09-2026: stats =
    viewCount, favoritedCount, since). None when the page has no stats —
    that is no reason to fail a bid lookup."""
    stats = (listing_page or {}).get("stats")
    if not isinstance(stats, dict):
        return None
    views, favorites = as_number(stats.get("viewCount")), as_number(stats.get("favoritedCount"))
    if views is None and favorites is None:
        return None
    return {
        "views": None if views is None else int(views),
        "favorites": None if favorites is None else int(favorites),
        "since": text_value(stats.get("since")) or None,
    }


def fetch_bid_info(session: requests.Session, vip_url: str, stats_out: Optional[dict] = None) -> Optional[dict]:
    """Fetch a listing's own page and return its bidsInfo (current bids /
    minimum bid) — this isn't included in the search results for FAST_BID
    listings, only on the listing page itself (loaded client-side there via
    window.__CONFIG__).

    Returns None both when the page simply has no bid data (normal: not every
    listing is biddable) and when the page couldn't be read at all. Only the
    second case is worth a warning — without one, a changed page structure
    just looks like a run where nobody happened to be bidding."""
    resp = session.get(vip_url, timeout=15)
    resp.raise_for_status()
    try:
        listing = listing_page_data(resp.text)
    except ListingPageError as exc:
        warn_bid_structure_changed(str(exc))
        return None
    # The page is here anyway: its views and saves come along for free
    # (views.py), instead of a second request later.
    if stats_out is not None:
        stats_out.update(page_stats(listing) or {})
    return (listing or {}).get("bidsInfo")


class ListingPageError(ValueError):
    """A listing page without the window.__CONFIG__ blob it used to have:
    Marktplaats changed its page structure (or showed something else)."""


def listing_page_data(page: str) -> Optional[dict]:
    """The `listing` object from a listing page's window.__CONFIG__: price,
    bidsInfo, isReserved, ... None when the blob is there but holds no
    listing. Raises ListingPageError when the blob itself is missing or
    unreadable, so a caller can tell a changed page apart from a listing
    that simply has no bid data."""
    marker_pos = page.find(CONFIG_MARKER)
    if marker_pos == -1:
        raise ListingPageError(f"{CONFIG_MARKER.strip()} niet gevonden")
    brace_pos = page.find("{", marker_pos)
    if brace_pos == -1:
        raise ListingPageError("geen JSON-object achter de marker")
    config = extract_balanced_json(page, brace_pos)
    if config is None:
        raise ListingPageError("JSON achter de marker niet te lezen")
    # "listing" can be present and null — .get()'s default only covers a
    # missing key, not a null value.
    listing = config.get("listing")
    return listing if isinstance(listing, dict) else None


def usable_bid_values(bids_info: dict) -> list[float]:
    """The bid entries in bids_info["bids"] that carry a usable numeric
    value — anything else (a non-dict entry, a missing/unparseable value)
    isn't a bid we can act on. Used both to resolve the bid price and to
    count "how many bids are there" (bid_count), so the two never diverge."""
    bids = bids_info.get("bids") or []
    values = [as_number(b.get("value")) for b in bids if isinstance(b, dict)]
    return [v for v in values if v is not None]


def resolve_bid_price(bids_info: dict) -> Optional[float]:
    """The relevant "price" for a bidding listing: the current highest bid
    if there is one, otherwise the minimum bid Marktplaats will accept."""
    # A bid entry without a usable value is not worth taking the run down for;
    # fall back to the minimum bid as if there were no bids at all.
    values = usable_bid_values(bids_info)
    if values:
        return max(values) / 100
    minimum = real_minimum_bid(bids_info)
    if minimum is not None:
        return minimum
    return None


def real_minimum_bid(bids_info: dict) -> Optional[float]:
    """currentMinimumBid in euros, or None when there is no minimum.
    Marktplaats sends -1 for "bieden zonder minimum" (seen on every FAST_BID
    listing without bids we checked, 2026-09-22), and 0 means the same. The
    old truthiness test let -1 through as a price of EUR -0.01, which
    scored every such listing 100/100 "Topdeal" at "min. €-0"."""
    minimum = as_number(bids_info.get("currentMinimumBid"))
    if minimum is None or minimum <= 0:
        return None
    return minimum / 100


def apply_bid_info(listing: Listing, bids_info: dict) -> None:
    """What a listing page's bidsInfo says, onto the listing: how many bids,
    the minimum, the highest bid, and the price that follows from them. The
    crawl's bid lookup and the live dashboard's controleer button
    (recheck.py) both go through here, so they reach the same price."""
    # bid_count counts usable bids, not raw entries — a bid without
    # a parseable value doesn't move resolve_bid_price() either, so
    # the two must count the same thing (see usable_bid_values()).
    values = usable_bid_values(bids_info)
    listing.bid_count = len(values)
    listing.bid_minimum = real_minimum_bid(bids_info)
    listing.bid_high = max(values) / 100 if values else None
    price = resolve_bid_price(bids_info)
    # A MIN_BID listing already has a price from the search results
    # (what the seller is asking) and Marktplaats will accept a
    # *lower* minimum bid than that — seen in the wild: asking €47.50,
    # minimum bid €35. Those are two different numbers, so the asking
    # price stays the price (otherwise these listings would look
    # cheaper than fixed-price ones purely for being biddable) and the
    # minimum lands in bid_minimum. Only a real bid above the asking
    # price replaces it: below that bid the listing can't be had.
    raw_bids = bids_info.get("bids") or []
    if price is not None and (
        listing.price_eur is None or (raw_bids and price > listing.price_eur)
    ):
        listing.price_eur = price
        listing.price_is_bid = True


def apply_stored_bids(listing: Listing, row) -> None:
    """What koopjes.db kept from the last bid lookup and controleer
    (migrations 11 and 14), onto a listing read back from the database: the
    dashboards and /racefietsen build their listings from `listing`, not from
    a run. `row` needs bid_count, bid_minimum, bid_high, bids_checked_at,
    checked_at, is_bid and price_is_asking."""
    listing.bid_minimum = row["bid_minimum"]
    listing.bid_high = row["bid_high"]
    # A bid above the asking price holds until the next lookup. A round that
    # doesn't look MIN_BID up (bid_lookup fast, and none during the day)
    # writes the asking price from the search results back, but below that
    # bid the listing can't be had any more — the same rule as
    # apply_bid_info().
    if (listing.price_type == "MIN_BID" and listing.bid_high is not None
            and listing.price_eur is not None and listing.bid_high > listing.price_eur):
        listing.price_eur = listing.bid_high
    listing.bids_checked_at = row["bids_checked_at"]
    # When the controleer button last read the listing's own page.
    listing.checked_at = row["checked_at"]
    # From before migration 11 only price_is_asking = 0 marks a running bid
    # (migration 3); one bid is enough for Listing.price_is_asking to say the
    # same.
    if row["bid_count"] is not None:
        listing.bid_count = row["bid_count"]
    elif row["is_bid"] and row["price_is_asking"] == 0:
        listing.bid_count = 1


def listing_from_row(row, site_specs: Optional[dict] = None, places: Optional[dict] = None) -> Listing:
    """A row from `listing` in koopjes.db back as a Listing, for everything
    that reads the database instead of running a crawl (the dashboards,
    /racefietsen, upgrade.py). Columns the SELECT left out stay empty; with
    the bid columns in it, also what the last bid lookup and controleer found
    (apply_stored_bids()). `site_specs`: {item_id: specs} from the listing
    page's Kenmerken, `places`: {item_id: (lat, lon, promotion, traits)}."""
    keys = row.keys()

    def get(key):
        return row[key] if key in keys else None

    title, detail = get("title") or "", get("full_description") or ""
    groupset, tier = detect_groupset(f"{title} {detail or get('description') or ''}")
    lat, lon, promotion, traits = (places or {}).get(row["item_id"], (None, None, "", ""))
    listing = Listing(
        item_id=row["item_id"], title=title, description=get("description") or "", price_eur=get("price_eur"),
        price_type=get("price_type") or "", city=get("city") or "", date=get("posted_date") or "",
        condition=get("condition") or "", frame_height=get("frame_height") or "", groupset=groupset,
        groupset_tier=tier, url=get("url") or "", price_is_bid=bool(get("is_bid")),
        first_seen=get("first_seen") or "", image_urls=get("image_urls") or "",
        reserved=get("reserved_at") is not None, site_specs=(site_specs or {}).get(row["item_id"], {}),
        detail_text=detail, latitude=lat, longitude=lon, promotion=promotion or "", traits=traits or "")
    if "bid_minimum" in keys:
        apply_stored_bids(listing, row)
    return listing


def enrich_bid_listings(
    listings: list[Listing],
    delay: float,
    mode: str = "fast",
    session: Optional[requests.Session] = None,
) -> None:
    """Fetch bid details from bidding listings' own pages. FAST_BID listings
    report €0 in search results, so without this they have no usable price at
    all; MIN_BID listings do report an asking price, so for those this adds
    the minimum bid that's actually accepted (usually lower) and how many
    bids have already been placed (mode "all").

    mode: "fast" (default, FAST_BID only), "all" (also MIN_BID), "none".
    """
    if mode == "none":
        return

    targets = [l for l in listings if l.price_type == "FAST_BID" and l.price_eur is None]
    if mode == "all":
        targets += [l for l in listings if l.price_type == "MIN_BID"]
    if not targets:
        return

    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "nl-NL,nl;q=0.9"})

    print(f"Biedprijzen ophalen voor {len(targets)} bied-advertenties...", file=sys.stderr)
    for i, listing in enumerate(targets, start=1):
        stats: dict = {}
        try:
            bids_info = fetch_bid_info(session, listing.url, stats)
        except requests.RequestException as exc:
            print(f"  warning: kon bod niet ophalen voor {listing.item_id}: {exc}", file=sys.stderr)
            continue

        if bids_info:
            apply_bid_info(listing, bids_info)
        if stats:
            listing.page_stats = {**stats, "source": "biedopvraging"}

        print(f"  {i}/{len(targets)} verwerkt", file=sys.stderr)
        if i < len(targets):
            time.sleep(delay)


def extract_dominant_category(search_response: dict) -> Optional[int]:
    """Marktplaats flags the category a query is really about (dominant:
    true) in its RelevantCategories facet. Past a certain page depth its
    search loosens to fuzzy/partial word matches and starts returning
    listings from unrelated categories (e.g. "racefiets" eventually pulling
    in PS2 games because their titles contain "racer"); this lets us filter
    those back out."""
    for facet in search_response.get("facets") or []:
        if facet.get("key") == "RelevantCategories":
            dominant = [c for c in facet.get("categories") or [] if c.get("dominant")]
            if not dominant:
                return None
            # For an ambiguous query Marktplaats can flag more than one
            # category as dominant (e.g. "boxen" flags both baby playpens
            # and speakers) — the one with the most matches is the real one.
            # `or 0`: a null count would come back out of .get() as None and
            # take max() down comparing it to an int, same as a count that
            # arrives as a string.
            return max(dominant, key=lambda c: as_number(c.get("histogramCount")) or 0).get("id")
    return None


def text_value(value) -> str:
    """A text field from the search JSON as a str. Marktplaats sends some
    keys with a null value rather than leaving them out, and .get()'s
    default only covers a missing key; a None that gets through takes the
    report down at the first html.escape() or slice."""
    return value if isinstance(value, str) else ""


def extract_attribute(raw_listing: dict, key: str) -> str:
    for group in ("attributes", "extendedAttributes"):
        # `or []`: Marktplaats can send the key with a null value, and the
        # default of .get() only covers a missing key.
        for attr in raw_listing.get(group) or []:
            if attr.get("key") == key:
                return text_value(attr.get("value"))
    return ""


# Marktplaats groups frame height into fixed buckets (e.g. "53 tot 57 cm")
# rather than exposing an exact size, so filtering can only match on
# whichever buckets overlap the requested range.
FRAME_HEIGHT_PATTERNS = [
    (re.compile(r"^Minder dan (\d+)", re.I), lambda m: (0.0, float(m.group(1)))),
    (re.compile(r"^(\d+)\s*tot\s*(\d+)", re.I), lambda m: (float(m.group(1)), float(m.group(2)))),
    (re.compile(r"^(\d+)\s*cm of meer", re.I), lambda m: (float(m.group(1)), float("inf"))),
    (re.compile(r"^(\d+(?:[.,]\d+)?)\s*cm$", re.I), lambda m: (float(m.group(1).replace(",", ".")),) * 2),
]


def frame_height_bounds(value: str) -> Optional[tuple[float, float]]:
    """Parse a Marktplaats frame-height bucket string into a (min, max) cm range."""
    value = value.strip()
    for pattern, to_bounds in FRAME_HEIGHT_PATTERNS:
        match = pattern.match(value)
        if match:
            return to_bounds(match)
    return None


# Groupset isn't a structured Marktplaats field, so this is detected from
# free text (title + description) by keyword. Tiers are on a rough unified
# 1-6 scale (entry to top-of-the-line) so groupsets from different brands
# can be compared: Shimano Claris/Sora/Tiagra/105/Ultegra/Dura-Ace, SRAM
# Apex/Rival/Force/Red, Campagnolo Veloce/Centaur/Chorus/Record(/Super
# Record). SRAM/Campagnolo tier words are ambiguous English/Dutch words on
# their own ("force", "record", ...), so those require the brand name to
# also appear somewhere in the text.
GROUPSET_CATALOG = [
    ("Shimano", "Dura-Ace", re.compile(r"dura[\s-]?ace", re.I), 6, False),
    ("Shimano", "Ultegra", re.compile(r"\bultegra\b", re.I), 5, False),
    ("Shimano", "105", re.compile(r"(?<!\d)\b105\b(?!\s*(cm|euro|eur|,-|km|mm|kg))", re.I), 4, False),
    ("Shimano", "Tiagra", re.compile(r"\btiagra\b", re.I), 3, False),
    ("Shimano", "Sora", re.compile(r"\bsora\b", re.I), 2, False),
    ("Shimano", "Claris", re.compile(r"\bclaris\b", re.I), 1, False),
    ("SRAM", "Red", re.compile(r"\bred\b", re.I), 6, True),
    ("SRAM", "Force", re.compile(r"\bforce\b", re.I), 5, True),
    ("SRAM", "Rival", re.compile(r"\brival\b", re.I), 4, True),
    ("SRAM", "Apex", re.compile(r"\bapex\b", re.I), 3, True),
    ("Campagnolo", "Super Record", re.compile(r"super\s*record", re.I), 6, True),
    ("Campagnolo", "Record", re.compile(r"\brecord\b", re.I), 5, True),
    ("Campagnolo", "Chorus", re.compile(r"\bchorus\b", re.I), 4, True),
    ("Campagnolo", "Centaur", re.compile(r"\bcentaur\b", re.I), 3, True),
    ("Campagnolo", "Veloce", re.compile(r"\bveloce\b", re.I), 2, True),
]


# Di2 is Shimano's electronic groupset, eTap and AXS are SRAM's — a mention of
# one says nothing about a groupset from the other brand. (Campagnolo's EPS is
# deliberately absent: no rows in the catalog need it yet.)
ELECTRONIC_MARKERS = {
    "Shimano": re.compile(r"\bdi2\b", re.I),
    "SRAM": re.compile(r"\betap\b|\baxs\b", re.I),
}


# The marker has to belong to the same phrase as the groupset name: close by,
# with nothing but words, digits, spaces, hyphens or slashes in between.
# "Shimano Ultegra R8050 Di2" is one name; in "Shimano 105, Di2-upgrade
# mogelijk" the comma separates the groupset that's for sale from a sales
# pitch about one that isn't, and tagging that 105 as electronic would put a
# wrong spec in front of every later comparison.
ELECTRONIC_MAX_GAP = 30


ELECTRONIC_GAP_RE = re.compile(r"[\w\s/-]*")


def mentions_electronic(text: str, brand: str, groupset_match: re.Match) -> bool:
    """Whether `text` says the groupset found at `groupset_match` is the
    electronic version of itself."""
    marker = ELECTRONIC_MARKERS.get(brand)
    if marker is None:
        return False
    for found in marker.finditer(text):
        between = (
            text[groupset_match.end():found.start()]
            if found.start() >= groupset_match.end()
            else text[found.end():groupset_match.start()]
        )
        if len(between) <= ELECTRONIC_MAX_GAP and ELECTRONIC_GAP_RE.fullmatch(between):
            return True
    return False


# "Groepset: Ultegra 11 speed" — a line where the seller says what the
# groupset is. A full description then goes on to list parts ("Cassette: Dura
# Ace 12/30", "Crank: 105"), and highest-tier-wins would call a bike with an
# Ultegra groupset and a Dura-Ace cassette a Dura-Ace bike. Seen on the first
# listing page fetched (27-09-2026).
GROUPSET_LINE_RE = re.compile(
    r"(?:^|[\n;|•])\s*(?:groepset|groupset|groep)\s*[:=-]\s*([^\n;|•]+)", re.I
)


# Remembered per text, like extract_specs(): /racefietsen, the valuation and
# the report read the same listing texts several times per build, and again
# after every round. The result depends on the text alone.
@lru_cache(maxsize=1 << 15)
def detect_groupset(text: str) -> tuple[str, Optional[int]]:
    """Best-effort groupset detection from free text. Returns (label, tier)
    for the highest-tier match found, or ("", None) if nothing recognized.
    A labelled groupset line wins over the rest of the text."""
    for line in GROUPSET_LINE_RE.findall(text):
        label, tier = _detect_groupset_in(line)
        if tier is not None:
            return label, tier
    return _detect_groupset_in(text)


def _detect_groupset_in(text: str) -> tuple[str, Optional[int]]:
    text_lower = text.lower()
    best_label = ""
    best_tier: Optional[int] = None
    best_brand = ""
    best_match: Optional[re.Match] = None
    for brand, name, pattern, tier, needs_brand in GROUPSET_CATALOG:
        match = pattern.search(text)
        # "Force AXS" and "Red eTap" are how sellers write a SRAM groupset
        # without ever typing "SRAM"; the electronic marker in the same phrase
        # pins the brand just as well as the brand name would. A loose "axs"
        # elsewhere in the text doesn't count, or "force" in a sales pitch
        # would become a groupset.
        if (
            match
            and needs_brand
            and brand.lower() not in text_lower
            and not mentions_electronic(text, brand, match)
        ):
            continue
        if match and (best_tier is None or tier > best_tier):
            best_tier = tier
            best_label = f"{brand} {name}"
            best_brand = brand
            best_match = match

    if best_match is not None and mentions_electronic(text, best_brand, best_match):
        best_label += " (elektronisch)"

    return best_label, best_tier


FRAME_MATERIAL_PATTERNS = [
    ("carbon", re.compile(r"\bcarbon\b", re.I)),
    ("titanium", re.compile(r"\btita(?:a)?n(?:ium)?\b", re.I)),
    ("aluminium", re.compile(r"\b(?:aluminium|alu)\b", re.I)),
    ("staal", re.compile(r"\b(?:staal|stalen|steel|chromoly|cro-?mo)\b", re.I)),
]


# "Carbon" (or aluminium, ...) in an ad is as often about the wheels as the
# frame — "aluminium frame, carbon wielset" is a common combination on
# exactly this kind of bike (see mijn_fiets.md). A material word is only
# trusted for frame_material within its own clause (split on . , ;): a
# clause naming a wheel word without also naming "frame" is a wheel mention,
# not a frame one, and is skipped in favor of another clause/material. When a
# clause names both a frame word and a wheel word, the clause alone can't
# say which one the material belongs to, so proximity is used as a vangnet:
# whichever word — "frame" or the wheel word — sits closer to the material
# mention wins. This only kicks in for that ambiguous case; it doesn't
# replace the material-first outer loop above it.
WHEEL_CONTEXT_WORD_RE = re.compile(r"\b(?:velg\w*|wiel\w*|wheel\w*)\b", re.I)


FRAME_WORD_RE = re.compile(r"\bframe\w*\b", re.I)


CLAUSE_SPLIT_RE = re.compile(r"[.,;]")


def _nearest_word_distance(
    clause: str, match: "re.Match[str]", word_re: "re.Pattern[str]"
) -> Optional[int]:
    """Character distance from `match` to the nearest word_re match in
    `clause`, or None if word_re doesn't occur at all."""
    best: Optional[int] = None
    for word_match in word_re.finditer(clause):
        if word_match.end() <= match.start():
            distance = match.start() - word_match.end()
        elif match.end() <= word_match.start():
            distance = word_match.start() - match.end()
        else:
            distance = 0
        if best is None or distance < best:
            best = distance
    return best


def detect_frame_material(text: str) -> Optional[str]:
    clauses = CLAUSE_SPLIT_RE.split(text)
    for label, pattern in FRAME_MATERIAL_PATTERNS:
        for clause in clauses:
            match = pattern.search(clause)
            if not match:
                continue
            has_wheel_word = bool(WHEEL_CONTEXT_WORD_RE.search(clause))
            has_frame_word = bool(FRAME_WORD_RE.search(clause))
            if has_wheel_word and not has_frame_word:
                continue
            if has_wheel_word and has_frame_word:
                frame_dist = _nearest_word_distance(clause, match, FRAME_WORD_RE)
                wheel_dist = _nearest_word_distance(clause, match, WHEEL_CONTEXT_WORD_RE)
                if frame_dist is None or (wheel_dist is not None and wheel_dist <= frame_dist):
                    continue
            return label
    return None


# Order matters: the more specific hydraulic/mechanical phrasing has to be
# tried before the bare "schijfrem" pattern, or it would win first and the
# brake type would never come out more specific than "disc".
BRAKE_TYPE_PATTERNS = [
    (
        "hydraulische schijfrem",
        re.compile(r"hydraulisch\w*\s+schijfrem\w*|hydraulic\s+disc", re.I),
    ),
    (
        "mechanische schijfrem",
        re.compile(r"mechanisch\w*\s+schijfrem\w*|mechanical\s+disc", re.I),
    ),
    # A bare "Disc" is how the model name says it on a lot of bikes ("Emonda
    # SL5 Disc", "Defy Advanced Pro 1 Disc"), usually the only brake mention
    # in the title and the 200-character snippet. Except when it's a disc
    # wheel — the closed rear wheel of a time-trial bike, not a brake.
    (
        "schijfrem",
        re.compile(
            r"\bschijfrem\w*\b|\bdisc\b(?![\s-]*(?:wheel\b|wiel\b|achterwiel\b))", re.I
        ),
    ),
    ("velrem", re.compile(r"\bvelg?rem\w*\b|\brim[\s-]?brakes?\b", re.I)),
]


# Restricted to the range that's actually used on a road bike (8-13 sprockets
# at the cassette) — a bare "22 speed" or "24 speed" almost always turns out
# to describe hub gears or a kids' bike miscounting front x rear, not a
# racefiets groupset, so those are deliberately left unmatched.
SPEEDS_RE = re.compile(r"\b(8|9|10|11|12|13)[\s-]*(?:speed|spd|versnellingen|v)\b", re.I)


WHEEL_TYPE_PATTERNS = [
    (
        "carbon",
        re.compile(
            r"carbon\s*(?:velg\w*|wiel\w*|wheel\w*)|(?:velg\w*|wiel\w*|wheel\w*)"
            r"[^.,;]{0,15}\bcarbon\b",
            re.I,
        ),
    ),
    (
        "aluminium",
        re.compile(
            r"(?:aluminium|alu)\s*(?:velg\w*|wiel\w*)|(?:velg\w*|wiel\w*)"
            r"[^.,;]{0,15}\b(?:aluminium|alu)\b",
            re.I,
        ),
    ),
]


# Requires an explicit label ("bouwjaar", "model(jaar)", "uit") rather than
# any bare 20xx number in the text — a price, a phone number in the
# description or "sinds 2018 in bezit" would otherwise all misread as the
# bike's model year.
MODEL_YEAR_RE = re.compile(r"\b(?:bouwjaar|model(?:jaar)?|uit)\s*[:\s]*((?:19|20)\d{2})\b", re.I)


WEIGHT_KG_RE = re.compile(r"\b(\d{1,2}[.,]\d{1,2})\s*kg\b", re.I)


POWERMETER_RE = re.compile(
    r"\bpowermeter\b|\bpower\s*meter\b|\bvermogensmeter\b|\bquarq\b|\bstages\b|"
    r"\bfavero\b|\b4iiii\b|\bsrm\b",
    re.I,
)


# has_computer is relative to what the owner already has (see PLAN_FIETSWAARDE.md
# §7 — he keeps his own Wahoo Elemnt Roam), but that weighting is scoring.py's
# job (fase 4); extraction here only records that a computer was mentioned.
# A bare brand name only counts when what follows isn't one of that brand's
# other products or a mount for one: "Garmin houder" is a bar mount (seen in a
# full description, 27-09-2026), Varia a radar light, Vector/Rally pedal power
# meters, Kickr/Tickr a trainer and a heart-rate strap.
COMPUTER_RE = re.compile(
    r"\bfietscomputer\b|\bbike\s*computer\b|\belemnt\b|\bedge\s*\d+\b|"
    r"\bgarmin\b(?![\s-]*(?:houder|mount|steun|beugel|adapter|varia|vector|rally|hrm|hartslag))|"
    r"\bwahoo\b(?![\s-]*(?:houder|mount|steun|beugel|adapter|kickr|tickr|rpm|speedplay|headwind|climb))",
    re.I,
)


def _first_pattern_label(text: str, patterns: list[tuple[str, "re.Pattern[str]"]]) -> Optional[str]:
    for label, pattern in patterns:
        if pattern.search(text):
            return label
    return None


def extract_specs(text: str) -> dict[str, str]:
    """Best-effort structured specs from free text (title + description),
    beyond the groupset already covered by detect_groupset(). Only keys that
    were confidently recognized are present; nothing is guessed for the
    rest. A fresh dict every call; the reading itself is remembered per
    text (see detect_groupset())."""
    return dict(_extract_specs(text))


@lru_cache(maxsize=1 << 15)
def _extract_specs(text: str) -> tuple:
    specs: dict[str, str] = {}

    material = detect_frame_material(text)
    if material:
        specs["frame_material"] = material

    brake = _first_pattern_label(text, BRAKE_TYPE_PATTERNS)
    if brake:
        specs["brake_type"] = brake

    speeds_match = SPEEDS_RE.search(text)
    if speeds_match:
        specs["speeds"] = speeds_match.group(1)

    wheel = _first_pattern_label(text, WHEEL_TYPE_PATTERNS)
    if wheel:
        specs["wheel_type"] = wheel

    year_match = MODEL_YEAR_RE.search(text)
    if year_match:
        specs["model_year"] = year_match.group(1)

    weight_match = WEIGHT_KG_RE.search(text)
    if weight_match:
        specs["weight_kg"] = weight_match.group(1).replace(",", ".")

    if POWERMETER_RE.search(text):
        specs["has_powermeter"] = "1"
    if COMPUTER_RE.search(text):
        specs["has_computer"] = "1"

    return tuple(specs.items())


def extract_listing_specs(listings: list[Listing]) -> dict[str, dict[str, str]]:
    """extract_specs() for every listing, keyed by item_id, ready to hand to
    db.sync_listing_specs()."""
    return {listing.item_id: extract_specs(spec_text(listing)) for listing in listings}


def spec_text(listing: Listing) -> str:
    """The text specs are read from: the full description where the listing
    page was fetched, the search snippet otherwise."""
    return f"{listing.title} {listing.detail_text or listing.description}"


# Marktplaats' structured attributes, as the search results carry them in
# extendedAttributes (checked 27-09-2026: `material` on 17 of 30 racefietsen,
# `brakeType` on the odd one), mapped onto extract_specs()' vocabulary. Only
# values that say one thing: "Overige", a combined value or a new wording is
# left out rather than guessed. numberOfGears is not used — it counts the
# gears ("Meer dan 20 versnellingen"), not the sprockets `speeds` means.
SITE_MATERIALS = {"carbon": "carbon", "aluminium": "aluminium", "staal": "staal", "titanium": "titanium"}


SITE_BRAKES = {
    "velgrem": "velrem",
    "velrem": "velrem",
    "schijfrem": "schijfrem",
    "hydraulische schijfrem": "hydraulische schijfrem",
    "mechanische schijfrem": "mechanische schijfrem",
}


def site_specs(raw: dict) -> dict[str, str]:
    specs = {}
    material = SITE_MATERIALS.get(extract_attribute(raw, "material").strip().lower())
    if material:
        specs["frame_material"] = material
    brake = SITE_BRAKES.get(extract_attribute(raw, "brakeType").strip().lower())
    if brake:
        specs["brake_type"] = brake
    return specs


def listing_spec_dict(listing: Listing) -> dict[str, str]:
    """Everything known about a listing's build: the text first, because
    it's the more specific ("hydraulische schijfrem" where the attribute
    only says "Schijfrem"), and the seller's structured attributes for what
    the text doesn't say — which, with a 200-character snippet, is often the
    frame material."""
    return {**listing.site_specs, **extract_specs(spec_text(listing))}


#
# The search results cut the description at 200 characters, and that's where
# the groupset, brakes and wheels usually are ("Groepset: Ultegra 11 speed"
# after two sentences about why the bike is for sale). The listing page has
# the whole text, server-rendered, plus the seller's attributes as a list.
# Checked on the real site 27-09-2026.
DESCRIPTION_START = 'data-collapsable="description">'


PAGE_ATTRIBUTE_RE = re.compile(
    r'Attributes-module-label">([^<]+)</div>\s*<div class="Attributes-module-value">'
    r"(?:<a[^>]*>)?([^<]+)"
)


PAGE_FRAME_HEIGHT_LABEL = "framehoogte"


_detail_structure_warned = False


def warn_detail_structure_changed(detail: str) -> None:
    global _detail_structure_warned
    if _detail_structure_warned:
        return
    _detail_structure_warned = True
    print(
        f"warning: advertentiepagina niet te lezen ({detail}) — Marktplaats heeft "
        "waarschijnlijk zijn paginastructuur gewijzigd. De volledige omschrijving blijft "
        "leeg; de rest van de run gaat gewoon door.",
        file=sys.stderr,
    )


def html_to_text(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html_lib.unescape(text).strip()


def parse_listing_page(page: str) -> Optional[tuple[str, dict[str, str]]]:
    """(full description, Kenmerken as {label: value}) from a listing page,
    or None when the description block isn't where it used to be."""
    start = page.find(DESCRIPTION_START)
    if start == -1:
        return None
    start += len(DESCRIPTION_START)
    end = page.find("</div>", start)
    if end == -1:
        return None
    attributes = {
        html_lib.unescape(label).strip().lower(): html_lib.unescape(value).strip()
        for label, value in PAGE_ATTRIBUTE_RE.findall(page)
    }
    return html_to_text(page[start:end]), attributes


def page_specs(attributes: dict[str, str]) -> dict[str, str]:
    """The listing page's Kenmerken in site_specs()' terms, plus the frame
    height, which the search results often leave out."""
    specs = {}
    material = SITE_MATERIALS.get(attributes.get("materiaal", "").lower())
    if material:
        specs["frame_material"] = material
    brake = SITE_BRAKES.get(attributes.get("rem", "").lower())
    if brake:
        specs["brake_type"] = brake
    return specs


# How many photos a listing keeps from the search results. Marktplaats sends
# at most three there (the rest are only on the listing page), and for the
# sleeper cards (sleepers.py) three is enough to see what the bike is.
SEARCH_IMAGES = 3


def search_image_urls(raw: dict) -> str:
    """The listing's photos as the search results give them, space-separated.
    largeUrl, because a brand name on a down tube has to be readable; the
    other sizes are fallbacks should Marktplaats drop that one."""
    urls = []
    for picture in raw.get("pictures") or []:
        if not isinstance(picture, dict):
            continue
        url = picture.get("largeUrl") or picture.get("mediumUrl") or picture.get("url")
        if isinstance(url, str) and url.startswith("https://") and " " not in url:
            urls.append(url)
    return " ".join(urls[:SEARCH_IMAGES])


# The price types that take bids. Their price is the asking price (MIN_BID)
# or nothing at all (FAST_BID) until a bid lookup has read the listing page.
BID_PRICE_TYPES = ("MIN_BID", "FAST_BID")


def price_from_info(price_info: dict) -> tuple[Optional[float], str]:
    """(price in euros or None, priceType) from a priceInfo object — the
    search results and the listing page use the same one."""
    price_cents = as_number(price_info.get("priceCents"))
    price_type = text_value(price_info.get("priceType"))
    # priceCents is 0 for listings with no real price shown (e.g. an
    # unstarted bid or "see description") except when priceType is FREE,
    # where 0 genuinely means the item is free.
    has_real_price = price_cents is not None and (price_cents > 0 or price_type == "FREE")
    return (price_cents / 100 if has_real_price else None), price_type


def search_location(raw: dict) -> tuple[Optional[float], Optional[float]]:
    """(latitude, longitude) of a listing from the search results. Marktplaats
    sends them for every listing, also without a postcode in the request
    (checked 29-09-2026). A seller who only gave the country comes with
    onCountryLevel true and 0, 0 — that is no place, so None."""
    location = raw.get("location") or {}
    if not isinstance(location, dict) or location.get("onCountryLevel") is True:
        return None, None
    lat, lon = as_number(location.get("latitude")), as_number(location.get("longitude"))
    if lat is None or lon is None or (lat == 0 and lon == 0) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    return lat, lon


def search_promotion(raw: dict) -> tuple[str, str]:
    """(priorityProduct, traits) as text. "NONE" is no promotion, so ""."""
    product = text_value(raw.get("priorityProduct"))
    traits = raw.get("traits")
    words = " ".join(t for t in traits if isinstance(t, str) and " " not in t) if isinstance(traits, list) else ""
    return ("" if product.upper() == "NONE" else product), words


def parse_listing(raw: dict) -> Listing:
    price_eur, price_type = price_from_info(raw.get("priceInfo") or {})
    latitude, longitude = search_location(raw)
    promotion, traits = search_promotion(raw)

    vip_url = text_value(raw.get("vipUrl"))
    url = BASE_URL + vip_url if vip_url.startswith("/") else vip_url

    title = text_value(raw.get("title"))
    description = text_value(raw.get("description"))
    groupset, groupset_tier = detect_groupset(f"{title} {description}")

    return Listing(
        item_id=raw.get("itemId", ""),
        title=title,
        description=description,
        price_eur=price_eur,
        price_type=price_type,
        city=text_value((raw.get("location") or {}).get("cityName")),
        date=text_value(raw.get("date")),
        condition=extract_attribute(raw, "condition"),
        frame_height=extract_attribute(raw, "frameHeight"),
        groupset=groupset,
        groupset_tier=groupset_tier,
        url=url,
        # A MIN_BID listing's search-result price is what the seller is
        # asking; the minimum bid Marktplaats actually accepts (usually lower)
        # and the number of bids placed are only on the listing page itself,
        # so bid_minimum/bid_count stay empty until --bid-lookup all fills
        # them in.
        price_is_bid=price_type in BID_PRICE_TYPES,
        thin_content=raw.get("thinContent") is True,
        reserved=raw.get("reserved") is True,
        image_urls=search_image_urls(raw),
        site_specs=site_specs(raw),
        latitude=latitude,
        longitude=longitude,
        promotion=promotion,
        traits=traits,
    )


# The category a complete road bike is listed in. The upgrade finder and the
# valuation both need "is this a bike at all": once a watchlist crawls
# fietsonderdelen, koopjes.db also holds cranksets and powermeters, and a
# "Defy Composite frame" in the parts category is no comp for a complete
# Defy Composite.
ROAD_BIKE_CATEGORY = "fietsen-racefietsen"


# --category alle: everything the query finds, in every category — no
# server-side filter and no dominant-category guess. For a query that is
# its own filter: "giant defy" is dominant in racefietsen, but on 29-09-2026
# 23 of its 165 results were Defys a seller put under heren-sportfietsen,
# dames-omafietsen and the like, including two Defy Composites, and the
# guess dropped every one of them.
ALL_CATEGORIES = "alle"


LISTING_URL_CATEGORY_RE = re.compile(r"/v/[^/]+/([^/]+)/")


def category_from_url(url: str) -> Optional[str]:
    """The subcategory key from a listing URL. Marktplaats builds every
    listing URL as /v/<main category>/<subcategory>/<id>-<slug> (vipUrl in the
    search results), and the database has that URL for every listing it ever
    stored — unlike categoryId, which was never saved. None when the URL
    doesn't have that shape."""
    match = LISTING_URL_CATEGORY_RE.search(url or "")
    return match.group(1) if match else None


def relevant_categories(search_response: dict) -> list[dict]:
    for facet in search_response.get("facets") or []:
        if facet.get("key") == "RelevantCategories":
            return facet.get("categories") or []
    return []


def resolve_categories(search_response: dict, wanted: list[str]) -> tuple[int, list[int]]:
    """Turn --category values (a Marktplaats category key such as
    "fietsonderdelen", or its number) into what fetch_api_page() sends: one
    main category and the subcategories under it. Resolved against the
    query's own RelevantCategories facet, which lists every category the
    query has results in, with its parent — so a category that isn't in
    there has nothing to find anyway, and the error can list what is."""
    by_name: dict[str, dict] = {}
    for cat in relevant_categories(search_response):
        if cat.get("id") is None:
            continue
        by_name[str(cat["id"])] = cat
        if cat.get("key"):
            by_name[str(cat["key"]).lower()] = cat

    chosen, missing = [], []
    for name in wanted:
        cat = by_name.get(name.strip().lower())
        if cat is None:
            missing.append(name)
        else:
            chosen.append(cat)
    if missing:
        counted = [c for c in relevant_categories(search_response) if c.get("histogramCount")]
        counted.sort(key=lambda c: as_number(c.get("histogramCount")) or 0, reverse=True)
        available = ", ".join(f"{c.get('key')} ({c.get('histogramCount')})" for c in counted[:10])
        if not chosen:
            raise ValueError(
                f"categorie {missing[0]!r} komt niet voor in de resultaten voor deze zoekterm. "
                f"Wel: {available or 'geen'}"
            )
        # Een deel van de categorieën heeft nu niets voor deze zoekterm
        # ("tomtom" in activity-trackers, 28-09-2026; "epix" had er die dag
        # 2). Dat kan elke dag anders zijn, en een zoekopdracht die daardoor
        # helemaal niets ophaalt kost een nacht. Een tikfout valt nog steeds
        # op als geen enkele categorie klopt, en staat hier in het log.
        print(f"  let op: categorie {', '.join(repr(m) for m in missing)} heeft nu geen resultaten voor "
              f"deze zoekterm; overgeslagen. Wel: {available or 'geen'}", file=sys.stderr)

    main_ids = {c.get("parentId") or c["id"] for c in chosen}
    if len(main_ids) > 1:
        raise ValueError(
            "de gekozen categorieën vallen onder verschillende hoofdcategorieën; "
            "Marktplaats zoekt er maar één tegelijk. Maak er twee zoekopdrachten van."
        )
    l1 = int(main_ids.pop())
    if any(not c.get("parentId") for c in chosen):
        # The main category itself was asked for: that already covers every
        # subcategory under it.
        return l1, []
    return l1, [int(c["id"]) for c in chosen]


# A "wanted" ad: someone looking to buy, listed in the same category as the
# things for sale. Nothing in the listing data marks it (adType and traits
# look like any other ad's), so the title is all there is. Only where the
# word stands alone — at the start, at the end, or in brackets — since "veel
# gezocht model" is a seller's sales pitch. Without this they came out on top:
# no price, a "bieden" button, and a 100/100 Topdeal.
WANTED_AD_RE = re.compile(
    r"^\W*gezocht\b|\(\s*gezocht\s*\)|(?<!veel )(?<!zeer )(?<!vaak )\bgezocht\W*$",
    re.I,
)


def is_wanted_ad(title: str) -> bool:
    return bool(WANTED_AD_RE.search(title or ""))


def other_dominant_categories(search_response: dict, kept: Optional[int]) -> list[dict]:
    return [
        c for c in relevant_categories(search_response) if c.get("dominant") and c.get("id") != kept
    ]


# One more try after a failed page, after this long. Seen 28-09-2026: a
# single 403 from Marktplaats' CloudFront between two fine requests, gone a
# minute later. Without a second try that one response ended the crawl, and a
# nightly full crawl that stops early marks nothing as gone — a whole night of
# data. One retry, well spaced, is still polite; a second failure stops as
# before. With --delay 0 (tests, a quick manual run) there's no wait.
RETRY_WAIT_SECONDS = 60


def _fetch_with_retry(fetch, page: int, delay: float) -> dict:
    try:
        return fetch(page)
    except (requests.RequestException, RuntimeError) as exc:
        wait = max(RETRY_WAIT_SECONDS, delay) if delay > 0 else 0
        print(f"warning: page {page} failed ({exc}); trying once more in {wait:.0f}s", file=sys.stderr)
        time.sleep(wait)
        return fetch(page)


# --split: a complete crawl of more than Marktplaats will page through.
# Measured 30-09-2026 on the category racefietsen (13316 listings): the
# search API pages to offset ~5000 at most, also with limit 100 (50 pages of
# 100), and it filters server-side on a listing's condition
# (attributesById[], the "condition" facet: Nieuw 2325, Zo goed als nieuw
# 4350, Gebruikt 6047) and on a price range (attributeRanges[]
# PriceCents:lo:hi, both ends included). Price ranges alone miss everything
# without an amount ("bieden", "zie omschrijving": 2550 of the 13316), and
# sorting by price leaves the FAST_BID ones out altogether, so the condition
# goes first; a condition with more than SPLIT_CAP gets a second pass oldest
# first. Price bands then pick up the listings that have no condition set.
SPLIT_CAP = 4800


SPLIT_PAGE_SIZE = 100


# Rustiger dan een gewone crawl. Op 30-09-2026 gaf Marktplaats na ~120
# verzoeken van 100 advertenties in 6 minuten (1,5 s ertussen) een 403
# Forbidden; een paar minuten later ging het weer. Dus: minstens 4 s
# ertussen, elke 40 verzoeken een minuut pauze, en na een 403 vijf minuten
# wachten en één keer opnieuw — lukt dat niet, dan stopt de crawl met wat
# hij heeft (incompleet: er wordt niets als verdwenen gemarkeerd).
SPLIT_MIN_DELAY = 4.0


SPLIT_BREAK_EVERY = 40


SPLIT_BREAK_SECONDS = 60


SPLIT_BLOCKED_WAIT = 300


SPLIT_PRICE_BANDS_EUR = (0, 150, 300, 500, 800, 1200, 2000, 3500)


OLDEST_FIRST = ("SORT_INDEX", "INCREASING")


def _facet_values(search_response: dict, key: str) -> list[tuple[int, int]]:
    """(attributeValueId, count) of one attribute facet."""
    for facet in search_response.get("facets") or []:
        if facet.get("key") == key:
            out = []
            for option in facet.get("attributeGroup") or []:
                ident, count = option.get("attributeValueId"), as_number(option.get("histogramCount"))
                if isinstance(ident, int) and count:
                    out.append((ident, int(count)))
            return out
    return []


def collect_split(
    query: str,
    delay: float,
    session: requests.Session,
    category_filter: tuple[int, list[int]],
    first: dict,
) -> "CrawlResult":
    """A complete crawl in parts that each stay under the page cap (see
    SPLIT_CAP). `first`: the unfiltered search response, for the total and
    the condition facet. Complete only if the parts together saw every
    listing Marktplaats counts; otherwise the sweep is skipped, as for any
    incomplete crawl."""
    total = as_number(first.get("totalResultCount")) or 0
    listings: dict[str, Listing] = {}
    raw_ids: set = set()
    fetch_error: Optional[str] = None
    requests_made = 0

    def crawl(extra: list, order: tuple, max_pages: int, label: str) -> Optional[int]:
        """Pages of one part; returns the part's total, or None on an error."""
        nonlocal fetch_error, requests_made
        part_total = None
        page = 1
        def get(p: int) -> dict:
            return fetch_api_page(session, query, p, category_filter=category_filter, extra=extra,
                                  limit=SPLIT_PAGE_SIZE, order=order)

        while page <= max_pages:
            if requests_made:
                pause = max(delay, SPLIT_MIN_DELAY) if delay > 0 else 0
                if delay > 0 and requests_made % SPLIT_BREAK_EVERY == 0:
                    pause = SPLIT_BREAK_SECONDS
                time.sleep(pause)
            try:
                try:
                    data = get(page)
                except requests.HTTPError as exc:
                    if getattr(exc.response, "status_code", None) != 403 and "403" not in str(exc):
                        raise
                    print(f"warning: Marktplaats weigert even (403); {SPLIT_BLOCKED_WAIT // 60} minuten wachten",
                          file=sys.stderr)
                    time.sleep(SPLIT_BLOCKED_WAIT if delay > 0 else 0)
                    data = get(page)
            except (requests.RequestException, RuntimeError) as exc:
                print(f"warning: {label}, pagina {page}: {exc}", file=sys.stderr)
                fetch_error = f"{label}: pagina {page} kon niet worden opgehaald"
                return None
            requests_made += 1
            if part_total is None:
                part_total = int(as_number(data.get("totalResultCount")) or 0)
                max_pages = min(max_pages, -(-min(part_total, SPLIT_CAP + 200) // SPLIT_PAGE_SIZE))
            raw = data.get("listings") or []
            if not raw:
                break
            for item in raw:
                if item.get("itemId"):
                    raw_ids.add(item["itemId"])
                listing = parse_listing(item)
                if listing.item_id and not is_wanted_ad(listing.title):
                    listings[listing.item_id] = listing
            site_max = as_number(data.get("maxAllowedPageNumber"))
            if site_max and page >= site_max:
                break
            page += 1
        print(f"  {label}: {part_total} advertenties, {len(raw_ids)} van de {int(total)} tot nu toe gezien",
              file=sys.stderr)
        return part_total

    print(f"  {int(total)} resultaten, meer dan Marktplaats doorbladert: in delen (--split)", file=sys.stderr)
    for ident, count in _facet_values(first, "condition"):
        extra = [("attributesById[]", ident)]
        part = crawl(extra, SORT_OPTIONS["newest"], 10_000, f"staat {ident}")
        if part is None:
            break
        if part > SPLIT_CAP:
            # Newest first reached the cap; the oldest ones from the other end.
            rest = -(-(part - SPLIT_CAP) // SPLIT_PAGE_SIZE) + 2
            if crawl(extra, OLDEST_FIRST, rest, f"staat {ident}, oudste eerst") is None:
                break
    if not fetch_error:
        bands = list(zip(SPLIT_PRICE_BANDS_EUR, SPLIT_PRICE_BANDS_EUR[1:] + (None,)))
        for lo, hi in bands:
            upper = f"{hi * 100 - 1}" if hi is not None else ""
            extra = [("attributeRanges[]", f"PriceCents:{lo * 100}:{upper}")]
            part = crawl(extra, SORT_OPTIONS["newest"], 10_000, f"prijs €{lo}-{hi or ''}")
            if part is None:
                break
            if part > SPLIT_CAP:
                crawl(extra, OLDEST_FIRST, -(-(part - SPLIT_CAP) // SPLIT_PAGE_SIZE) + 2,
                      f"prijs €{lo}-{hi or ''}, oudste eerst")
    print(f"  in delen: {requests_made} verzoeken, {len(raw_ids)} van de {int(total)} gezien", file=sys.stderr)
    if fetch_error:
        return CrawlResult(listings.values(), complete=False, note=fetch_error)
    if len(raw_ids) < total:
        # Not near_complete: what the parts miss (no condition and no price)
        # is missed every week, and would be swept as gone although online.
        return CrawlResult(listings.values(), complete=False,
                           note=f"in delen {len(raw_ids)} van de {int(total)} gezien (zonder staat én zonder prijs "
                                "is niet apart op te vragen)")
    return CrawlResult(listings.values(), complete=True)


def collect_listings(
    query: str,
    pages: int,
    delay: float,
    session: Optional[requests.Session] = None,
    *,
    sort: str = "optimized",
    categories: Optional[list[str]] = None,
    split: bool = False,
) -> CrawlResult:
    """Fetch listings page by page. pages <= 0 means "fetch everything
    Marktplaats allows browsing to" (it caps pagination at a few hundred
    listings regardless of the total match count).

    sort "newest" and categories go through the search API
    (fetch_api_page()); the default goes through the search page as it
    always has. With categories, the first request is an unrestricted one
    to resolve them (see resolve_categories()), and Marktplaats does the
    category filtering from there — instead of the dominant-category guess
    below, which keeps only one category. categories ["alle"]
    (ALL_CATEGORIES) does neither: every result, whatever its category."""
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "nl-NL,nl;q=0.9"})

    print(f"Zoeken naar '{query}' op Marktplaats...", file=sys.stderr)
    category_filter: Optional[tuple[int, list[int]]] = None
    all_categories = any(c.strip().lower() == ALL_CATEGORIES for c in categories or ())
    if all_categories and len(categories) > 1:
        # "alle,fietsonderdelen" asks for two different things; guessing
        # which one was meant runs a wider or narrower search than asked.
        note = f"--category: {ALL_CATEGORIES!r} gaat niet samen met andere categorieën"
        print(f"error: {note}", file=sys.stderr)
        return CrawlResult([], complete=False, note=note)
    if categories and not all_categories:
        try:
            first = _fetch_with_retry(lambda p: fetch_api_page(session, query, p, sort), 1, delay)
            category_filter = resolve_categories(first, categories)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print(f"error: --category: {exc}", file=sys.stderr)
            return CrawlResult([], complete=False, note=f"--category: {exc}")
        time.sleep(delay)
        if split and pages <= 0:
            try:
                whole = _fetch_with_retry(
                    lambda p: fetch_api_page(session, query, p, category_filter=category_filter, limit=1), 1, delay)
            except (requests.RequestException, RuntimeError) as exc:
                return CrawlResult([], complete=False, note=f"--split: {exc}")
            time.sleep(delay)
            if (as_number(whole.get("totalResultCount")) or 0) > SPLIT_CAP:
                return collect_split(query, delay, session, category_filter, whole)

    use_api = sort != "optimized" or category_filter is not None

    def fetch(page_number: int) -> dict:
        if use_api:
            return fetch_api_page(session, query, page_number, sort, category_filter)
        return fetch_page(session, query, page_number)

    listings: dict[str, Listing] = {}
    raw_ids: set = set()
    total_results: Optional[float] = None
    dominant_category: Optional[int] = None
    skipped_offtopic = 0
    skipped_without_id = 0
    skipped_wanted = 0
    fetch_error: Optional[str] = None
    reached_end = False
    cut_off_ids: tuple = ()
    page = 1
    while True:
        try:
            data = _fetch_with_retry(fetch, page, delay)
        except (requests.RequestException, RuntimeError) as exc:
            print(f"warning: failed to fetch page {page}: {exc}", file=sys.stderr)
            fetch_error = f"pagina {page} kon niet worden opgehaald"
            break

        raw_listings = data.get("listings", [])
        if not raw_listings:
            reached_end = True
            break

        if total_results is None:
            total_results = as_number(data.get("totalResultCount"))
        if dominant_category is None and category_filter is None and not all_categories:
            dominant_category = extract_dominant_category(data)
            others = other_dominant_categories(data, dominant_category)
            if dominant_category is not None and others:
                names = ", ".join(f"{c.get('key')} ({c.get('histogramCount')})" for c in others)
                print(
                    f"  let op: Marktplaats noemt voor '{query}' ook {names} als hoofdcategorie; "
                    "die worden overgeslagen. Neem ze mee met --category.",
                    file=sys.stderr,
                )

        for raw in raw_listings:
            if raw.get("itemId"):
                raw_ids.add(raw.get("itemId"))
            if dominant_category is not None and raw.get("categoryId") != dominant_category:
                skipped_offtopic += 1
                continue
            listing = parse_listing(raw)
            if not listing.item_id:
                # Listings are keyed by item id from here on (deduplicating
                # across pages, and everything the history remembers), so
                # without one they would overwrite each other and be "new"
                # forever. Rather drop them than merge two ads into one.
                skipped_without_id += 1
                continue
            if is_wanted_ad(listing.title):
                skipped_wanted += 1
                continue
            listings[listing.item_id] = listing

        # The key can be there with a null value (and .get()'s default only
        # covers a missing key), which would take both the min() below and the
        # page >= max_page test down with a TypeError. int(), because the page
        # number ends up in the progress line and "pagina 1/3.0" reads as a bug.
        site_max_page = as_number(data.get("maxAllowedPageNumber"))
        max_page = int(site_max_page) if site_max_page else page
        target = min(pages, max_page) if pages > 0 else max_page
        print(f"  pagina {page}/{target} opgehaald — {len(listings)} advertenties tot nu toe", file=sys.stderr)

        reached_requested_limit = pages > 0 and page >= pages
        reached_site_limit = page >= max_page
        if reached_site_limit:
            reached_end = True
        elif reached_requested_limit:
            cut_off_ids = tuple(raw.get("itemId") for raw in raw_listings if raw.get("itemId"))
        if reached_requested_limit or reached_site_limit:
            break
        page += 1
        time.sleep(delay)

    if skipped_without_id:
        print(
            f"  {skipped_without_id} advertentie(s) zonder item-id overgeslagen "
            "(niet uit elkaar te houden en niet te onthouden)",
            file=sys.stderr,
        )
    if skipped_wanted:
        print(
            f"  {skipped_wanted} 'gezocht'-advertentie(s) overgeslagen (iemand die zoekt, "
            "geen aanbod)",
            file=sys.stderr,
        )
    if skipped_offtopic:
        print(
            f"  {skipped_offtopic} advertenties buiten de hoofdcategorie overgeslagen "
            "(Marktplaats' zoekresultaten waaieren op diepere pagina's uit naar losse "
            "woord-matches)",
            file=sys.stderr,
        )

    # Complete = every result for the query went past us: no page failed,
    # paging ran to the end, and the distinct listings seen (before any
    # filtering) add up to the total Marktplaats reports. The last test is
    # what catches the page cap, and also the default sort's habit of
    # serving the same listing on several pages while skipping others.
    if fetch_error:
        complete, note = False, fetch_error
    elif not reached_end:
        complete, note = False, "niet alle pagina's opgehaald"
    elif total_results is not None and len(raw_ids) < total_results:
        complete = False
        note = (
            f"{len(raw_ids)} van de {int(total_results)} resultaten gezien — Marktplaats "
            "toont er niet meer, of herhaalde advertenties over pagina's heen"
        )
    else:
        complete, note = True, ""
    near_complete = (
        not complete
        and not fetch_error
        and reached_end
        and total_results is not None
        and total_results - len(raw_ids) <= near_complete_max_missing(total_results)
    )
    return CrawlResult(
        listings.values(), complete=complete, note=note, near_complete=near_complete,
        cut_off_ids=cut_off_ids,
    )


# How many listings at the bottom of the last page window_too_small() looks
# at. Not just the last one: with --sort newest the listing at the very
# bottom is often one posted a few minutes after the previous round, and so
# new without anything being missed. Not the whole page either: on page 1
# Marktplaats puts its paid "Dagtoppers" on top whatever the sort, and those
# are usually listings seen before (28-09-2026, fietscomputers: 7 of the 30).
WINDOW_CHECK_LISTINGS = 5


def window_too_small(cut_off_ids, history: dict, kept_ids) -> bool:
    """A shallow --sort newest crawl whose last listings were all new has
    probably not reached the previous round: there may be new listings
    beyond the last page that this round didn't see (the next full crawl
    will). Only the listings that survived this run's filters (`kept_ids`)
    count: a "gezocht" ad, or a racefiets outside the price or frame range,
    never goes into the history, so it would look new every round. Fewer
    than WINDOW_CHECK_LISTINGS of those on the last page, or no history to
    compare against, and there is nothing to say."""
    tail = [i for i in cut_off_ids if i in kept_ids][-WINDOW_CHECK_LISTINGS:]
    return bool(history) and len(tail) == WINDOW_CHECK_LISTINGS and not any(i in history for i in tail)


def filter_by_price(
    listings: list[Listing], min_price: Optional[float], max_price: Optional[float]
) -> list[Listing]:
    """Drop listings outside the price range. A listing without a price at all
    passes: a FAST_BID reports none in the search results, and unknown isn't
    the same as out of range — it gets tested again once the bid lookup has
    given it a price."""
    if min_price is not None:
        listings = [l for l in listings if l.price_eur is None or l.price_eur >= min_price]
    if max_price is not None:
        listings = [l for l in listings if l.price_eur is None or l.price_eur <= max_price]
    return listings


def filter_by_frame_height(
    listings: list[Listing],
    min_height: Optional[float],
    max_height: Optional[float],
    keep_unknown: bool = False,
) -> list[Listing]:
    """keep_unknown decides what happens to a listing without a (readable)
    frame size. The CLI keeps them unless --strict-frame-height: on a
    40-page crawl of "racefiets", 76% of the bikes had no size filled in, so
    dropping them hid three out of four bikes — most of which just say
    "maat 56" in the text instead."""
    if min_height is None and max_height is None:
        return listings

    lo = min_height if min_height is not None else 0.0
    hi = max_height if max_height is not None else float("inf")

    result = []
    for listing in listings:
        bounds = frame_height_bounds(listing.frame_height)
        if bounds is None:
            if keep_unknown:
                result.append(listing)
            continue
        bucket_lo, bucket_hi = bounds
        if bucket_hi >= lo and bucket_lo <= hi:
            result.append(listing)
    return result


def market_prices(listings: list[Listing]) -> list[float]:
    """The prices that say something about what a thing costs here. A listing
    without a price is out for obvious reasons, and so is a EUR 0 one: that's
    a FREE listing (priceType FREE — see parse_listing), a giveaway rather
    than an asking price, and averaging it in drags every benchmark down."""
    return [l.price_eur for l in listings if l.price_eur]


def apply_bid_flags(listings: list[Listing]) -> None:
    """Mark bidding listings nobody has bid on yet — for those the seller's
    minimum bid is still the whole asking price, so they're the ones where
    you can actually still get in cheap. Listings whose bid count was never
    looked up (MIN_BID without --bid-lookup all) stay unmarked: unknown is
    not the same as zero."""
    for listing in listings:
        listing.bid_open = listing.price_is_bid and listing.bid_count == 0


def open_bid_listings(listings: list[Listing]) -> list[Listing]:
    return [l for l in listings if l.bid_open]


def bid_listings(listings: list[Listing]) -> list[Listing]:
    return [l for l in listings if l.price_is_bid]


# Marktplaats' accepted minimum bid is sometimes a cent under the asking
# price (€174.99 on a €175 listing) — that's not a discount worth pointing at,
# so only a minimum this far below the asking price counts as one.
MEANINGFUL_MINIMUM_BID_RATIO = 0.98


def format_bid_info(listing: Listing) -> str:
    """Short human-readable summary of a listing's bid state."""
    if not listing.price_is_bid:
        return ""
    bits = []
    if listing.bid_minimum is not None:
        minimum = f"min. €{listing.bid_minimum:.0f}"
        # The "% v. mediaan" here is an invitation: that's what opening the
        # bidding would cost you. It only holds while nobody has bid — after
        # that the listing can't be had for the minimum any more (the price
        # column has moved up to the standing bid, see resolve_bid_price), so
        # presenting it as a cheap way in would be wrong. The minimum itself
        # stays visible; only the framing goes. And as before, it's only worth
        # spelling out when it's really under the asking price, otherwise it
        # just repeats the "% v. mediaan" column.
        #
        # An unknown bid count is not a zero one (the same rule apply_bid_flags
        # applies to VRIJ TE BIEDEN): if we never counted the bids, we can't
        # claim nobody has bid.
        if (
            listing.bid_minimum_pct_of_median is not None
            and listing.bid_count == 0
            and (
                listing.price_eur is None
                or listing.bid_minimum <= listing.price_eur * MEANINGFUL_MINIMUM_BID_RATIO
            )
        ):
            minimum += f" ({listing.bid_minimum_pct_of_median:.0f}% v. mediaan)"
        bits.append(minimum)
    if listing.bid_count is None:
        bits.append("biedingen onbekend")
    elif listing.bid_count == 0:
        bits.append("nog geen bod")
    elif listing.bid_count == 1:
        bits.append("1 bod")
    else:
        bits.append(f"{listing.bid_count} biedingen")
    return " · ".join(bits)
