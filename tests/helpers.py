"""Shared helpers for the test suite."""
from __future__ import annotations

import sys
from pathlib import Path

# Tests are run from the repository root (`python -m unittest discover -s tests`),
# but make the import work regardless of where they're started from.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import racefiets_jev as mp  # noqa: E402
import requests  # noqa: E402


def _no_listing_pages(session, url):
    # A test that runs a whole query (run_for_query/main) with a database and
    # the real mijn_fiets.md gets a budget, and --detail-lookup would then
    # fetch real listing pages. Tests never touch the network; the ones about
    # the lookup patch this with a canned page.
    raise requests.ConnectionError(f"geen netwerk in tests ({url})")


mp.fetch_listing_page = _no_listing_pages


def close_databases_before_cleanup(testcase) -> None:
    """Close every koopjes.db connection a test opens, before its temporary
    directory is removed. Call it in setUp *after* registering that
    directory's cleanup (cleanups run last-in, first-out).

    Windows refuses to delete a file that is still open ("WinError 32: het
    bestand wordt door een ander proces gebruikt"), so a test that leaves a
    connection open fails in its cleanup there — while Linux and macOS
    delete the file regardless, which is how 52 of these went unnoticed."""
    import db
    from unittest import mock

    opened = []
    real_connect = db.connect

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    patcher = mock.patch.object(db, "connect", tracking_connect)
    patcher.start()
    testcase.addCleanup(lambda: [conn.close() for conn in opened])
    testcase.addCleanup(patcher.stop)


def repo_file(name: str) -> str:
    """A data file next to the code (scoring_config.json, mijn_fiets.md, ...).
    Tests that read one go through here rather than through a bare relative
    path, so a run started from inside tests/ finds the same file as one
    started from the repository root."""
    return str(REPO_ROOT / name)


def make_listing(**overrides) -> mp.Listing:
    """A Listing with sensible defaults; pass only the fields a test cares about."""
    fields = dict(
        item_id="m1",
        title="Testadvertentie",
        description="",
        price_eur=100.0,
        price_type="FIXED",
        city="Utrecht",
        date="",
        condition="Gebruikt",
        frame_height="",
        groupset="",
        groupset_tier=None,
        url="https://www.marktplaats.nl/v/x/m1-test",
    )
    fields.update(overrides)
    return mp.Listing(**fields)


def raw_listing(**overrides) -> dict:
    """A raw Marktplaats search-result dict as parse_listing() expects it."""
    raw = {
        "itemId": "m1",
        "title": "Testadvertentie",
        "description": "",
        "priceInfo": {"priceCents": 10000, "priceType": "FIXED"},
        "location": {"cityName": "Utrecht"},
        "date": "2026-09-22T10:00:00Z",
        "vipUrl": "/v/x/m1-test",
        "attributes": [],
        "extendedAttributes": [],
    }
    raw.update(overrides)
    return raw


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        pass


class FakeSession:
    """Stands in for requests.Session: serves canned pages per URL."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.headers: dict[str, str] = {}
        self.requested: list[str] = []

    def get(self, url: str, timeout: int = 0) -> FakeResponse:
        self.requested.append(url)
        return FakeResponse(self.pages.get(url, ""))


def search_page(listings: list[dict], max_page: int = 1, facets: list | None = None) -> str:
    """A search-results page as fetch_page() digs the JSON out of it."""
    import json

    data = {
        "props": {
            "pageProps": {
                "searchRequestAndResponse": {
                    "listings": listings,
                    "maxAllowedPageNumber": max_page,
                    "facets": facets or [],
                }
            }
        }
    }
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'


def config_page(bids_info: dict) -> str:
    """A listing page with a window.__CONFIG__ blob, as fetch_bid_info parses it."""
    import json

    config = {"listing": {"bidsInfo": bids_info}}
    return f"<html><script>window.__CONFIG__ = {json.dumps(config)};</script></html>"


def read_csv_rows(path: str) -> list[dict]:
    """Read a CSV written by the script, closing the file properly."""
    import csv

    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))
