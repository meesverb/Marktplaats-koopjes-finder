"""sleepers.py — listings whose text says nothing about the bike.

The regression case is the Cannondale CAAD10 of 23-09-2026 (m2445771095):
"Heren racefiets", "Moet weg wegens verhuizing!", bieden zonder minimum,
gone for EUR 45 two hours after it went up. The raw dict below has the shape
of the search results the crawl reads, trimmed to the fields that matter.
"""
import json
import unittest
from pathlib import Path

from helpers import make_listing, mp, raw_listing

import koopjes
import sleepers

PHOTO = "https://images.marktplaats.com/api/v1/hz-mp-pro-listing/images/{}?rule=ecg_mp_eps$_{}.jpg"


def cannondale_raw(**overrides) -> dict:
    raw = raw_listing(
        itemId="m2445771095",
        title="Heren racefiets",
        description="Moet weg wegens verhuizing!",
        thinContent=True,
        reserved=False,
        priceInfo={"priceCents": 0, "priceType": "FAST_BID"},
        location={"cityName": "Gronsveld"},
        vipUrl="/v/fietsen-en-brommers/fietsen-racefietsen/m2445771095-heren-racefiets",
        extendedAttributes=[
            {"key": "brand", "value": "Overige merken"},
            {"key": "material", "value": "Carbon"},
        ],
        pictures=[
            {"url": PHOTO.format(n, "#"), "mediumUrl": PHOTO.format(n, 82), "largeUrl": PHOTO.format(n, 83)}
            for n in ("a", "b", "c", "d")
        ],
    )
    raw.update(overrides)
    return raw


def cannondale(**overrides) -> mp.Listing:
    """As the pipeline leaves it: no usable bid yet, first seen this run."""
    listing = mp.parse_listing(cannondale_raw())
    listing.bid_count = 0
    listing.is_new = True
    mp.apply_bid_flags([listing])
    for name, value in overrides.items():
        setattr(listing, name, value)
    return listing


def generic(**overrides) -> mp.Listing:
    fields = dict(title="Racefiets", description="", price_eur=None, price_type="FAST_BID",
                  price_is_bid=True)
    fields.update(overrides)
    return make_listing(**fields)


class CannondaleRegressionTest(unittest.TestCase):
    def test_the_cannondale_is_a_full_score_sleeper(self):
        listing = cannondale()
        sleepers.apply_sleeper_signals([listing])
        self.assertEqual(listing.sleeper_score, 100.0)
        self.assertTrue(sleepers.is_sleeper(listing))
        for reason in ("titel zonder merk of model", "beschrijving van 4 woorden",
                       'haast: "Moet weg"', "bieden, nog geen bod", "nieuw sinds vorige run"):
            self.assertIn(reason, listing.sleeper_reasons)

    def test_seen_before_it_is_still_a_sleeper(self):
        listing = cannondale(is_new=False)
        sleepers.apply_sleeper_signals([listing])
        self.assertEqual(listing.sleeper_score, 90.0)
        self.assertTrue(sleepers.is_sleeper(listing))

    def test_once_reserved_it_is_left_out(self):
        listing = mp.parse_listing(cannondale_raw(reserved=True))
        self.assertTrue(listing.reserved)
        self.assertEqual(sleepers.sleeper_signal(listing), (None, ""))

    def test_the_same_ad_with_its_brand_in_the_title_is_not_a_sleeper(self):
        listing = cannondale(title="Cannondale CAAD10 heren racefiets")
        self.assertIsNone(sleepers.sleeper_signal(listing)[0])


class ParseListingTest(unittest.TestCase):
    def test_search_result_fields_are_kept(self):
        listing = mp.parse_listing(cannondale_raw())
        self.assertTrue(listing.thin_content)
        self.assertFalse(listing.reserved)
        # Three at most, the large size, in order.
        self.assertEqual(listing.image_urls.split(),
                         [PHOTO.format(n, 83) for n in ("a", "b", "c")])

    def test_missing_or_odd_picture_data_leaves_no_photos(self):
        for pictures in (None, [], ["x"], [{"largeUrl": None}], [{"largeUrl": "//images/x.jpg"}]):
            with self.subTest(pictures=pictures):
                self.assertEqual(mp.parse_listing(raw_listing(pictures=pictures)).image_urls, "")

    def test_flags_only_count_when_marktplaats_says_true(self):
        listing = mp.parse_listing(raw_listing(thinContent="true", reserved=1))
        self.assertFalse(listing.thin_content)
        self.assertFalse(listing.reserved)

    def test_new_fields_come_last_so_existing_csv_columns_stay_put(self):
        self.assertEqual(
            mp.LISTING_FIELDS[-5:],
            ["thin_content", "reserved", "image_urls", "sleeper_score", "sleeper_reasons"],
        )
        self.assertEqual(mp.LISTING_FIELDS.index("deal_reasons"), len(mp.LISTING_FIELDS) - 6)


class GenericTitleTest(unittest.TestCase):
    def test_generic_titles(self):
        for title in ("Heren racefiets", "racefiets", "Racefiets 56cm", "Mooie dames racefiets maat 54",
                      "Race fiets", "Racefiets / Gravelbike - Framemaat 57 (175 - 183 cm)",
                      "Carbon racefiets z.g.a.n", "Vintage koersfiets"):
            with self.subTest(title=title):
                self.assertTrue(sleepers.is_generic_title(title))

    def test_titles_that_name_something(self):
        for title in ("Giant racefiets", "Racefiets shimano 105", "Cannondale CAAD10",
                      "Vintage Peugeot racefiets - Blauw", "", "56", "Racefiets Ultegra"):
            with self.subTest(title=title):
                self.assertFalse(sleepers.is_generic_title(title))


class BrandInDescriptionTest(unittest.TestCase):
    def test_a_brand_in_the_description_rules_it_out(self):
        for description in ("Keurig onderhouden trek racefiets.", "Koga myata triple",
                            "Mooie wegfiets van felt.", "Frame van Cannondale, moet weg"):
            with self.subTest(description=description):
                self.assertIsNone(sleepers.sleeper_signal(generic(description=description))[0])

    def test_words_that_only_look_like_brands_do_not(self):
        for description in ("Retro look, moet weg", "Weinig tijd om te fietsen, moet weg",
                            "Moet weg. Rosé kleur."):
            with self.subTest(description=description):
                self.assertIsNotNone(sleepers.sleeper_signal(generic(description=description))[0])

    def test_without_the_catalogue_the_extra_brands_still_count(self):
        brands = sleepers.load_brands(Path("bestaat-niet.csv"))
        self.assertIn("koga", brands)
        self.assertNotIn("giant", brands)

    def test_the_catalogue_brands_count(self):
        brands = sleepers.load_brands()
        for brand in ("giant", "cannondale", "specialized", "koga"):
            self.assertIn(brand, brands)
        self.assertNotIn("time", brands)


class UrgencyTest(unittest.TestCase):
    def test_phrases_that_mean_it_has_to_go(self):
        for text, phrase in (("Moet weg wegens verhuizing!", "Moet weg"),
                             ("ivm verhuizen", "verhuizen"), ("zsm ophalen", "zsm"),
                             ("z.s.m. weg", "z.s.m."), ("weg=weg", "weg=weg"),
                             ("Weg is weg", "Weg is weg"), ("Garage opruimen", "opruimen"),
                             ("moet de deur uit", "moet de deur uit"),
                             ("uit een nalatenschap", "nalatenschap")):
            with self.subTest(text=text):
                self.assertEqual(sleepers.urgency_phrase(text), phrase)

    def test_words_that_do_not(self):
        for text in ("Snelle fiets", "geschikt voor weg- en wielrennen", "rijdt heerlijk weg",
                     "zsmall", ""):
            with self.subTest(text=text):
                self.assertIsNone(sleepers.urgency_phrase(text))


class PriceSignalTest(unittest.TestCase):
    def reasons(self, listing):
        return sleepers.sleeper_signal(listing)[1]

    def test_a_running_fast_bid_is_no_price_signal(self):
        listing = generic(price_eur=45.0, bid_count=1, pct_of_median=5.0)
        self.assertNotIn("bieden", self.reasons(listing))
        self.assertNotIn("mediaan", self.reasons(listing))

    def test_a_cheap_min_bid_asking_price_counts(self):
        listing = generic(price_eur=150.0, price_type="MIN_BID", pct_of_median=30.0)
        self.assertIn("30% van mediaan", self.reasons(listing))

    def test_a_min_bid_nobody_bid_on_counts_as_open(self):
        listing = generic(price_eur=150.0, price_type="MIN_BID", bid_count=0, bid_open=True)
        self.assertIn("bieden, nog geen bod", self.reasons(listing))

    def test_a_fixed_price_at_the_median_does_not(self):
        listing = generic(price_eur=900.0, price_type="FIXED", price_is_bid=False, pct_of_median=100.0)
        self.assertNotIn("mediaan", self.reasons(listing))


class ThresholdTest(unittest.TestCase):
    def test_a_generic_title_alone_is_not_enough(self):
        listing = generic(description=" ".join(["woord"] * 40), price_type="FIXED",
                          price_is_bid=False, price_eur=900.0, is_new=True)
        score, _ = sleepers.sleeper_signal(listing)
        self.assertEqual(score, 45.0)
        listing.sleeper_score = score
        self.assertFalse(sleepers.is_sleeper(listing))

    def test_order_is_strongest_then_newest(self):
        a = generic(item_id="a", description="Moet weg", is_new=False)
        b = generic(item_id="b", description="Moet weg", is_new=True)
        c = generic(item_id="c", description="kort", is_new=True)
        sleepers.apply_sleeper_signals([a, b, c])
        self.assertEqual([l.item_id for l in sleepers.sleepers([a, b, c])], ["b", "a", "c"])


class PriceTextTest(unittest.TestCase):
    def test_price_text_says_what_the_price_is(self):
        self.assertEqual(sleepers.price_text(generic()), "bieden zonder minimum")
        self.assertEqual(sleepers.price_text(generic(price_eur=45.0, bid_count=1)), "€45 (bod)")
        self.assertEqual(sleepers.price_text(generic(price_eur=150.0, bid_count=0)),
                         "minimumbod €150, nog geen bod")
        self.assertEqual(sleepers.price_text(generic(price_eur=150.0, price_type="MIN_BID")),
                         "€150 (vraagprijs, bieden)")
        self.assertEqual(sleepers.price_text(generic(price_eur=90.0, price_type="FIXED",
                                                     price_is_bid=False)), "€90")


class ReportTest(unittest.TestCase):
    def test_the_panel_shows_photos_and_escapes(self):
        listing = cannondale(description="Moet weg <b>nu</b>")
        other = make_listing(item_id="m2", title="Giant Defy")
        sleepers.apply_sleeper_signals([listing, other])
        count, html = sleepers.render_panel([listing, other])
        self.assertEqual(count, 1)
        self.assertIn(PHOTO.format("a", 83), html)
        self.assertIn("&lt;b&gt;nu&lt;/b&gt;", html)
        self.assertNotIn("Giant Defy", html)

    def test_an_empty_panel_says_so(self):
        self.assertEqual(sleepers.render_panel([make_listing()]),
                         (0, sleepers.render_panel([])[1]))
        self.assertIn("Geen slapers", sleepers.render_panel([])[1])

    def test_the_report_has_a_sleepers_tab_with_its_count(self):
        listing = cannondale()
        sleepers.apply_sleeper_signals([listing])
        html = mp.render_html([listing, make_listing(item_id="m2")], "racefiets")
        self.assertIn('data-panel="sleepers">Slapers (1)', html)
        self.assertIn('id="panel-sleepers"', html)


class SummaryTest(unittest.TestCase):
    def summary(self, listings):
        return mp.run_summary(listings, name="racefietsen", query="racefiets", finished_at="t",
                              report_path=None, crawl_complete=True, crawl_note="")

    def test_only_new_sleepers_go_to_the_overview(self):
        new = cannondale()
        old = cannondale(item_id="m-old", is_new=False)
        sleepers.apply_sleeper_signals([new, old])
        items = self.summary([new, old])["sleepers"]
        self.assertEqual([i["url"] for i in items], [new.url])
        self.assertEqual(items[0]["price"], "bieden zonder minimum")
        self.assertEqual(items[0]["image"], PHOTO.format("a", 83))
        json.dumps(items)  # it goes into runs.jsonl

    def test_the_overview_page_shows_them(self):
        import tempfile
        from test_koopjes import write_config

        listing = cannondale()
        sleepers.apply_sleeper_signals([listing])
        summary = self.summary([listing])
        summary.update(report="r.html", listings=1, new=1, better=0, top_deals=0, price_drops=0)
        with tempfile.TemporaryDirectory() as tmp:
            config = koopjes.load_config(write_config(Path(tmp)))
            page = koopjes.render_overview(config, {"racefietsen": summary}, [])
        self.assertIn("Slapers", page)
        self.assertIn("Heren racefiets", page)
        self.assertIn("slaper 100", page)

    def test_an_old_summary_without_sleepers_still_renders(self):
        import tempfile
        from test_koopjes import write_config

        summary = {"name": "racefietsen", "query": "racefiets", "finished_at": "t", "listings": 0}
        with tempfile.TemporaryDirectory() as tmp:
            config = koopjes.load_config(write_config(Path(tmp)))
            page = koopjes.render_overview(config, {"racefietsen": summary}, [])
        self.assertIn("Geen nieuwe slapers", page)


if __name__ == "__main__":
    unittest.main()
