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

    def test_a_category_without_results_today_is_skipped_if_another_has_them(self):
        # 28-09-2026: "tomtom" had nothing in activity-trackers, and the whole
        # query fetched nothing. Only when none of them is there is it an error.
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = mp.resolve_categories(self.facet(), ["fietsonderdelen", "fietscomputers"])
        self.assertEqual(result, (445, [462]))
        self.assertIn("'fietscomputers' heeft nu geen resultaten", err.getvalue())

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

    def test_one_failed_page_gets_a_second_try(self):
        # 28-09-2026: a single 403 between two good requests. The retry keeps
        # the crawl complete, so the nightly sweep still runs.
        session = self.html_session({
            1: response([raw_listing(itemId="a")], total=2, max_page=2),
            2: response([raw_listing(itemId="b")], total=2, max_page=2),
        })
        page_two = mp.BASE_URL + "/q/test/p/2/"
        good = session.pages.pop(page_two)
        real_get = session.get

        def flaky_get(url, timeout=0):
            response = real_get(url, timeout)  # the first try gets an empty page
            if url == page_two:
                session.pages[page_two] = good  # ... the second one works
            return response

        session.get = flaky_get
        result, err = collect(session)
        self.assertEqual({l.item_id for l in result}, {"a", "b"})
        self.assertTrue(result.complete)
        self.assertIn("trying once more", err)

    def test_a_listing_repeated_across_pages_makes_it_incomplete(self):
        # 2 slots, but one listing twice: the third result was never served.
        session = self.html_session({
            1: response([raw_listing(itemId="a")], total=2, max_page=2),
            2: response([raw_listing(itemId="a")], total=2, max_page=2),
        })
        result, _ = collect(session)
        self.assertFalse(result.complete)

    def test_one_missing_of_a_whole_crawl_is_near_complete(self):
        # Seen on the real site (27-09-2026): a listing sold while paging
        # shifts the rest up a place, and one goes unseen — 164 of 165.
        session = self.html_session({
            1: response([raw_listing(itemId="a")], total=3, max_page=2),
            2: response([raw_listing(itemId="b")], total=3, max_page=2),
        })
        result, _ = collect(session)
        self.assertFalse(result.complete)
        self.assertTrue(result.near_complete)

    def test_the_page_cap_and_a_failed_page_are_not_near_complete(self):
        capped, _ = collect(self.html_session(
            {1: response([raw_listing(itemId="a")], total=26354, max_page=1)}
        ))
        self.assertFalse(capped.near_complete)
        failed, _ = collect(self.html_session(
            {1: response([raw_listing(itemId="a")], total=2, max_page=2)}
        ))
        self.assertFalse(failed.near_complete)

    def test_a_complete_crawl_is_not_also_near_complete(self):
        result, _ = collect(self.html_session({1: response([raw_listing(itemId="a")], total=1)}))
        self.assertTrue(result.complete)
        self.assertFalse(result.near_complete)

    def test_the_tolerance_grows_with_the_query(self):
        self.assertEqual(mp.near_complete_max_missing(165), 3)
        self.assertEqual(mp.near_complete_max_missing(1000), 20)

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


class WindowCheckTest(unittest.TestCase):
    """Een ondiepe ronde op nieuwste-eerst (de fietscomputers overdag, 2
    pagina's): zegt het log het als er misschien nieuwe achter de laatste
    pagina lagen?"""

    def html_session(self, pages: dict):
        return FakeSession({
            mp.BASE_URL + ("/q/test/" if n == 1 else f"/q/test/p/{n}/"): html(data)
            for n, data in pages.items()
        })

    def test_a_crawl_cut_off_at_pages_remembers_its_last_page(self):
        session = self.html_session({
            1: response([raw_listing(itemId="a"), raw_listing(itemId="b")], total=90, max_page=3),
            2: response([raw_listing(itemId="c"), raw_listing(itemId="d")], total=90, max_page=3,
                        offset=30),
        })
        result, _ = collect(session, pages=2)
        self.assertEqual(result.cut_off_ids, ("c", "d"))

    def test_a_crawl_that_reached_the_end_was_not_cut_off(self):
        session = self.html_session({1: response([raw_listing(itemId="a")], total=1, max_page=1)})
        result, _ = collect(session, pages=2)
        self.assertEqual(result.cut_off_ids, ())

    def check(self, page, history, kept=None):
        return mp.window_too_small(page, history, set(page) if kept is None else kept)

    def test_all_new_at_the_bottom_means_the_window_may_be_too_small(self):
        page = tuple(f"n{i}" for i in range(30))
        self.assertTrue(self.check(page, {"oud": {}}))

    def test_one_known_listing_at_the_bottom_is_enough(self):
        page = tuple(f"n{i}" for i in range(29)) + ("oud",)
        self.assertFalse(self.check(page, {"oud": {}}))

    def test_known_dagtoppers_on_top_do_not_hide_a_gap(self):
        # Marktplaats zet betaalde Dagtoppers bovenaan pagina 1, ook bij nieuwste eerst.
        page = ("oud",) * 7 + tuple(f"n{i}" for i in range(23))
        self.assertTrue(self.check(page, {"oud": {}}))

    def test_listings_the_filters_dropped_do_not_count(self):
        # Te duur of verkeerde maat: nooit in de geschiedenis, dus altijd "nieuw".
        page = tuple(f"n{i}" for i in range(25)) + ("oud",) + tuple(f"duur{i}" for i in range(4))
        kept = set(page) - {f"duur{i}" for i in range(4)}
        self.assertFalse(self.check(page, {"oud": {}}, kept))
        self.assertFalse(self.check(("n1", "n2", "n3"), {"oud": {}}))  # te weinig om iets te zeggen

    def test_no_history_or_no_cut_off_says_nothing(self):
        self.assertFalse(self.check(tuple(f"n{i}" for i in range(30)), {}))
        self.assertFalse(self.check((), {"oud": {}}))


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

    def test_alle_keeps_every_category_without_a_resolving_request(self):
        # "giant defy" (29-09-2026): dominant in racefietsen, but Defys under
        # sportfietsen and omafietsen too — the guess dropped them all.
        def route(path, params):
            self.assertNotIn("l1CategoryId", params)
            return json.dumps(response(
                [raw_listing(itemId="race", categoryId=464), raw_listing(itemId="sport", categoryId=454)],
                total=2, facets=category_facet(PARTS, BIKES),
            ))

        session = RoutingSession(route)
        result, err = collect(session, sort="newest", categories=["Alle"])
        self.assertEqual({l.item_id for l in result}, {"race", "sport"})
        self.assertEqual(len(session.requested), 1)
        self.assertTrue(result.complete)
        self.assertNotIn("overgeslagen", err)

    def test_alle_also_works_through_the_search_page(self):
        page = html(response([raw_listing(itemId="fiets", categoryId=464),
                              raw_listing(itemId="onderdeel", categoryId=462)],
                             total=2, facets=category_facet(PARTS, BIKES)))
        result, _ = collect(FakeSession({mp.BASE_URL + "/q/test/": page}), categories=["alle"])
        self.assertEqual({l.item_id for l in result}, {"fiets", "onderdeel"})

    def test_alle_with_another_category_is_refused(self):
        session = RoutingSession(lambda p, q: self.fail("no request expected"))
        result, err = collect(session, categories=["alle", "fietsonderdelen"])
        self.assertEqual(session.requested, [])
        self.assertEqual(list(result), [])
        self.assertFalse(result.complete)
        self.assertIn("alle", err)

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


class SplitCrawlTest(unittest.TestCase):
    """--split: meer resultaten dan Marktplaats doorbladert (~5000), in delen
    per staat en prijsschijf (gemeten 30-09-2026 op de racefietsen)."""

    def setUp(self):
        self.addCleanup(setattr, mp, "SPLIT_CAP", mp.SPLIT_CAP)
        self.addCleanup(setattr, mp, "SPLIT_PAGE_SIZE", mp.SPLIT_PAGE_SIZE)
        self.addCleanup(setattr, mp, "SPLIT_PRICE_BANDS_EUR", mp.SPLIT_PRICE_BANDS_EUR)
        mp.SPLIT_CAP, mp.SPLIT_PAGE_SIZE, mp.SPLIT_PRICE_BANDS_EUR = 4, 2, (0, 500)

    def run_split(self, everything):
        """`everything`: (id, staat, prijs in cent of None). Nieuwste eerst =
        de volgorde van de lijst; de server bladert hooguit SPLIT_CAP diep."""
        condition = [{"key": "condition", "attributeGroup": [
            {"attributeValueId": 30, "histogramCount": sum(1 for x in everything if x[1] == 30)},
            {"attributeValueId": 32, "histogramCount": sum(1 for x in everything if x[1] == 32)}]}]

        def route(path, q):
            items = list(everything)
            if "attributesById[]" in q:
                items = [x for x in items if str(x[1]) == q["attributesById[]"][0]]
            if "attributeRanges[]" in q:
                lo, hi = q["attributeRanges[]"][0].split(":")[1:]
                items = [x for x in items if x[2] is not None and int(lo) <= x[2] <= (int(hi) if hi else 10**12)]
            if q.get("sortOrder") == ["INCREASING"]:
                items.reverse()
            limit, offset = int(q["limit"][0]), int(q["offset"][0])
            page = items[offset:offset + limit] if offset < mp.SPLIT_CAP else []
            listings = [raw_listing(itemId=i, title=f"Fiets {i}", priceInfo={"priceCents": c or 0,
                                    "priceType": "FIXED" if c else "FAST_BID"}) for i, _, c in page]
            data = response(listings, total=len(items), max_page=-(-mp.SPLIT_CAP // limit),
                            facets=category_facet(BIKES, BIKES_L1) + condition)
            data["searchRequest"] = {"pagination": {"offset": offset, "limit": limit}}
            return json.dumps(data)

        return collect(RoutingSession(route), categories=["fietsen-racefietsen"], sort="newest", split=True)

    def test_every_listing_through_condition_both_ways_and_price_bands(self):
        everything = ([(f"m{n}", 32, 10000 + n) for n in range(7)]   # gebruikt: 7 > cap, dus ook oudste eerst
                      + [(f"n{n}", 30, None) for n in range(3)]      # nieuw, bieden zonder prijs
                      + [("x1", None, 20000), ("x2", None, 90000)])  # zonder staat: via de prijsschijven
        result, log = self.run_split(everything)
        self.assertEqual({l.item_id for l in result}, {x[0] for x in everything})
        self.assertTrue(result.complete, log)
        self.assertIn("in delen", log)

    def test_what_no_part_reaches_makes_it_incomplete(self):
        everything = [(f"m{n}", 32, 10000) for n in range(4)] + [("lost", None, None)]
        result, _ = self.run_split(everything)
        self.assertNotIn("lost", {l.item_id for l in result})
        self.assertFalse(result.complete)
        self.assertFalse(result.near_complete)  # elke week gemist: nooit als verdwenen vegen
        self.assertIn("4 van de 5", result.note)
