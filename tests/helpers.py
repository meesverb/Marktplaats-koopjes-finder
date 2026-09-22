"""Shared helpers for the test suite."""
from __future__ import annotations

import sys
from pathlib import Path

# Tests are run from the repository root (`python -m unittest discover -s tests`),
# but make the import work regardless of where they're started from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import racefiets_jev as mp  # noqa: E402


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
