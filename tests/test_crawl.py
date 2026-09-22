"""Crawling: pagination, sort order, categories and whether a crawl was
complete.

Every rule here comes from checking the real site (2026-09-22):

- a space encoded as %20 got page 2+ redirected to page 1, so every
  multi-word query ("giant defy") fetched page 1 over and over;
- the default order ("Standaard") isn't by date, and repeats listings across
  pages, so only the search API's newest-first order covers "everything new
  since the last run" in a few pages;
- a query can have two dominant categories ("powermeter": parts and bikes),
  and keeping only the biggest threw away every loose powermeter;
- --pages 0 stops at ~5000 results, so "not seen in a full crawl" does not
  mean "gone" unless the crawl provably saw every result.
"""
import contextlib
import io
import json
import unittest
from urllib.parse import parse_qs, urlparse

from helpers import FakeResponse, FakeSession, make_listing, mp, raw_listing


def response(listings, *, total=None, max_page=1, offset=None, facets=None) -> dict:
    data = {"listings": listings, "maxAllowedPageNumber": max_page, "facets": facets or []}
    if total is not None:
        data["totalResultCount"] = total
    if offset is not None:
        data["searchRequest"] = {"pagination": {"offset": offset, "limit": 30}}
    return data


def html(data: dict) -> str:
    wrapped = {"props": {"pageProps": {"searchRequestAndResponse": data}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(wrapped)}</script>'


def category_facet(*cats) -> list:
    return [{"key": "RelevantCategories", "categories": list(cats)}]


PARTS = {"id": 462, "key": "fietsonderdelen", "parentId": 445, "histogramCount": 255, "dominant": True}
BIKES = {"id": 464, "key": "fietsen-racefietsen", "parentId": 445, "histogramCount": 508, "dominant": True}
BIKES_L1 = {"id": 445, "key": "fietsen-en-brommers"}
SPORT = {"id": 792, "key": "wielrennen", "parentId": 784, "histogramCount": 43}


class RoutingSession(FakeSession):
    """Serves the search API by what the URL asks for rather than by exact
    string, so a test doesn't have to spell out the parameter order."""

    def __init__(self, route):
        super().__init__({})
        self.route = route

    def get(self, url, timeout=0):
        self.requested.append(url)
        parsed = urlparse(url)
        return FakeResponse(self.route(parsed.path, parse_qs(parsed.query)))


def collect(session, **kwargs):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        result = mp.collect_listings("test", kwargs.pop("pages", 0), 0, session=session, **kwargs)
    return result, err.getvalue()


class QueryEncodingTest(unittest.TestCase):
    def requested_url(self, query, page=1):
        session = FakeSession({})
        with self.assertRaises(RuntimeError):
            mp.fetch_page(session, query, page)
        return session.requested[0]

    def test_a_space_becomes_a_plus(self):
        # /q/giant%20defy/p/2/ is redirected to /q/giant+defy/ — page 1.
        self.assertTrue(self.requested_url("giant defy", page=2).endswith("/q/giant+defy/p/2/"))

    def test_a_literal_plus_stays_distinguishable_from_a_space(self):
        self.assertTrue(self.requested_url("c++").endswith("/q/c%2B%2B/"))


class PageOffsetTest(unittest.TestCase):
    def test_page_one_served_for_page_two_is_an_error(self):
        with self.assertRaises(RuntimeError):
            mp.check_page_offset(response([], offset=0), 2)

    def test_the_right_offset_passes(self):
        mp.check_page_offset(response([], offset=30), 2)
        mp.check_page_offset(response([], offset=0), 1)

    def test_a_response_without_pagination_info_passes(self):
        mp.check_page_offset(response([]), 3)

    def test_fetch_page_stops_on_a_redirect_to_page_one(self):
        url = mp.BASE_URL + "/q/test/p/2/"
        session = FakeSession({url: html(response([raw_listing()], offset=0))})
        with self.assertRaises(RuntimeError):
            mp.fetch_page(session, "test", 2)


class FetchApiPageTest(unittest.TestCase):
    def test_sort_offset_and_categories_go_into_the_request(self):
        seen = {}

        def route(path, params):
            seen.update(params, path=path)
            return json.dumps(response([], offset=60))

        mp.fetch_api_page(RoutingSession(route), "giant defy", 3, "newest", (445, [462, 3112]))
        self.assertEqual(seen["path"], mp.SEARCH_API_PATH)
        self.assertEqual(seen["query"], ["giant defy"])
        self.assertEqual(seen["offset"], ["60"])
        self.assertEqual(seen["sortBy"], ["SORT_INDEX"])
        self.assertEqual(seen["sortOrder"], ["DECREASING"])
        self.assertEqual(seen["l1CategoryId"], ["445"])
        # Plural and repeated; the singular name is silently ignored.
        self.assertEqual(seen["l2CategoryIds"], ["462", "3112"])

    def test_optimized_is_the_default_order(self):
        seen = {}

        def route(path, params):
            seen.update(params)
            return json.dumps(response([]))

        mp.fetch_api_page(RoutingSession(route), "x", 1)
        self.assertEqual(seen["sortBy"], ["OPTIMIZED"])
        self.assertNotIn("l1CategoryId", seen)

    def test_something_other_than_a_listing_response_is_an_error(self):
        for body in ["<html>verificatie</html>", json.dumps({"iets": "anders"}), "[]"]:
            with self.subTest(body=body):
                with self.assertRaises(RuntimeError):
                    mp.fetch_api_page(RoutingSession(lambda p, q: body), "x", 1)


class ResolveCategoriesTest(unittest.TestCase):
    def facet(self):
        return response([], facets=category_facet(BIKES_L1, PARTS, BIKES, SPORT))

    def test_by_key_and_by_number(self):
        self.assertEqual(mp.resolve_categories(self.facet(), ["fietsonderdelen"]), (445, [462]))
        self.assertEqual(mp.resolve_categories(self.facet(), ["462", "Fietsen-Racefietsen"]), (445, [462, 464]))

    def test_a_main_category_covers_everything_under_it(self):
        self.assertEqual(mp.resolve_categories(self.facet(), ["fietsen-en-brommers", "fietsonderdelen"]), (445, []))

    def test_unknown_category_lists_what_is_there(self):
        with self.assertRaises(ValueError) as ctx:
            mp.resolve_categories(self.facet(), ["fietscomputers"])
        self.assertIn("fietsonderdelen (255)", str(ctx.exception))

    def test_categories_under_different_main_categories_are_refused(self):
        with self.assertRaises(ValueError):
            mp.resolve_categories(self.facet(), ["fietsonderdelen", "wielrennen"])


class CompletenessTest(unittest.TestCase):
    def html_session(self, pages: dict):
        return FakeSession({
            mp.BASE_URL + ("/q/test/" if n == 1 else f"/q/test/p/{n}/"): html(data)
            for n, data in pages.items()
        })

    def test_every_result_seen_is_complete(self):
        session = self.html_session({
            1: response([raw_listing(itemId="a")], total=2, max_page=2),
            2: response([raw_listing(itemId="b")], total=2, max_page=2),
        })
        result, _ = collect(session)
        self.assertEqual({l.item_id for l in result}, {"a", "b"})
        self.assertTrue(result.complete)

    def test_the_page_cap_makes_it_incomplete(self):
        session = self.html_session({1: response([raw_listing(itemId="a")], total=26354, max_page=1)})
        result, _ = collect(session)
        self.assertFalse(result.complete)
        self.assertIn("1 van de 26354", result.note)

    def test_a_failed_page_makes_it_incomplete(self):
        session = self.html_session({1: response([raw_listing(itemId="a")], total=2, max_page=2)})
        result, err = collect(session)
        self.assertEqual([l.item_id for l in result], ["a"])
        self.assertFalse(result.complete)
        self.assertIn("pagina 2", result.note)

    def test_a_listing_repeated_across_pages_makes_it_incomplete(self):
        # 2 slots, but one listing twice: the third result was never served.
        session = self.html_session({
            1: response([raw_listing(itemId="a")], total=2, max_page=2),
            2: response([raw_listing(itemId="a")], total=2, max_page=2),
        })
        result, _ = collect(session)
        self.assertFalse(result.complete)

    def test_a_shallow_crawl_is_not_complete(self):
        session = self.html_session({1: response([raw_listing(itemId="a")], total=2, max_page=2)})
        result, _ = collect(session, pages=1)
        self.assertFalse(result.complete)

    def test_listings_filtered_as_off_topic_still_count_as_seen(self):
        # Completeness is about what Marktplaats served, not what we kept.
        session = self.html_session({1: response(
            [raw_listing(itemId="a", categoryId=464), raw_listing(itemId="b", categoryId=1)],
            total=2, facets=category_facet(BIKES),
        )})
        result, _ = collect(session)
        self.assertEqual([l.item_id for l in result], ["a"])
        self.assertTrue(result.complete)


class CategoryTest(unittest.TestCase):
    def test_a_second_dominant_category_is_reported_not_silently_dropped(self):
        page = html(response(
            [raw_listing(itemId="fiets", categoryId=464), raw_listing(itemId="onderdeel", categoryId=462)],
            facets=category_facet(PARTS, BIKES),
        ))
        result, err = collect(FakeSession({mp.BASE_URL + "/q/test/": page}))
        self.assertEqual([l.item_id for l in result], ["fiets"])
        self.assertIn("fietsonderdelen (255)", err)
        self.assertIn("--category", err)

    def test_category_is_resolved_then_filtered_by_marktplaats(self):
        def route(path, params):
            if "l1CategoryId" not in params:
                # The resolving request: facets only matter here.
                return json.dumps(response([raw_listing(itemId="fiets", categoryId=464)],
                                           facets=category_facet(PARTS, BIKES)))
            self.assertEqual(params["l2CategoryIds"], ["462"])
            return json.dumps(response(
                [raw_listing(itemId="pm", categoryId=462)], total=1,
                # A restricted response still flags bikes as dominant; that
                # guess must not be applied on top of an explicit choice.
                facets=category_facet(PARTS, BIKES),
            ))

        result, _ = collect(RoutingSession(route), categories=["fietsonderdelen"])
        self.assertEqual([l.item_id for l in result], ["pm"])
        self.assertTrue(result.complete)

    def test_unknown_category_fetches_nothing_more(self):
        session = RoutingSession(lambda p, q: json.dumps(response([], facets=category_facet(PARTS))))
        result, err = collect(session, categories=["bestaat-niet"])
        self.assertEqual(len(session.requested), 1)
        self.assertEqual(list(result), [])
        self.assertFalse(result.complete)
        self.assertIn("bestaat-niet", err)

    def test_newest_goes_through_the_api(self):
        session = RoutingSession(lambda p, q: json.dumps(response([raw_listing(itemId="a")], total=1)))
        result, _ = collect(session, sort="newest")
        self.assertTrue(session.requested[0].startswith(mp.BASE_URL + mp.SEARCH_API_PATH))
        self.assertTrue(result.complete)


class WantedAdTest(unittest.TestCase):
    def test_titles_from_the_real_site(self):
        wanted = ["gezocht", "Gezocht!!!", "gezocht Carbon racefiets.",
                  "Gezocht: racefiets of gravelbike max 4 jaar — eerlijk bod",
                  "Gazelle innergy display (Gezocht)", "Garmin Edge 530 gezocht"]
        for title in wanted:
            with self.subTest(title=title):
                self.assertTrue(mp.is_wanted_ad(title))

    def test_a_sales_pitch_is_not_a_wanted_ad(self):
        for title in ["Veel gezocht model Giant Defy", "Gezochte kleur Canyon Endurace, maat 56",
                      "Gazelle Champion Mondial, veel gezocht!", "Wahoo Roam v1 — zeer gezocht",
                      "Wahoo Elemnt Roam v2"]:
            with self.subTest(title=title):
                self.assertFalse(mp.is_wanted_ad(title))

    def test_collect_skips_them(self):
        page = html(response([raw_listing(itemId="zoek", title="Gezocht: Wahoo Roam"),
                              raw_listing(itemId="aanbod", title="Wahoo Roam")], total=2))
        result, err = collect(FakeSession({mp.BASE_URL + "/q/test/": page}))
        self.assertEqual([l.item_id for l in result], ["aanbod"])
        self.assertIn("gezocht", err)
        # Still counted as seen: it is online, just not for sale.
        self.assertTrue(result.complete)


class FrameHeightDefaultTest(unittest.TestCase):
    listings = [
        make_listing(item_id="past", frame_height="53 tot 57 cm"),
        make_listing(item_id="te-klein", frame_height="Minder dan 49 cm"),
        make_listing(item_id="onbekend", frame_height=""),
    ]

    def test_function_keeps_unknown_only_when_asked(self):
        self.assertEqual({l.item_id for l in mp.filter_by_frame_height(self.listings, 54, 58)}, {"past"})
        self.assertEqual(
            {l.item_id for l in mp.filter_by_frame_height(self.listings, 54, 58, keep_unknown=True)},
            {"past", "onbekend"},
        )

    def test_cli_default_is_to_keep_unknown(self):
        self.assertFalse(mp.parse_args([]).strict_frame_height)
        self.assertTrue(mp.parse_args(["--strict-frame-height"]).strict_frame_height)


if __name__ == "__main__":
    unittest.main()
