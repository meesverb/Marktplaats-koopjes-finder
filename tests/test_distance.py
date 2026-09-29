"""distance.py: de afstand van elke advertentie tot de eigen postcode."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from helpers import close_databases_before_cleanup, make_listing, raw_listing

import db
import distance as dm
import racefiets_jev as mp
import recheck as rc

HOME = (52.0952, 5.1161)  # rond 3511AB, zoals op 29-09-2026 gemeten
PLACES = [(52.3700, 4.9000), (51.9200, 4.4800), (52.5100, 6.0900), (51.4400, 5.4700), (53.2200, 6.5700),
          (52.1600, 5.3900), (52.0100, 4.3600), (51.5900, 4.7800), (52.2200, 6.8900), (50.8500, 5.6900),
          (52.6300, 4.7500), (51.8400, 5.8600)]


def search_json(points, zeros: int = 3) -> str:
    """Zoekresultaten zoals Marktplaats ze met een postcode geeft: per
    advertentie de plek en distanceMeters, afgerond op hele km. Plus een paar
    met afstand 0 (onbekend, sommige winkels) en een zonder plek."""
    listings = [{"location": {"latitude": lat, "longitude": lon,
                              "distanceMeters": round(dm.haversine_km(*HOME, lat, lon)) * 1000}}
                for lat, lon in points]
    listings += [{"location": {"latitude": 53.0, "longitude": 6.0, "distanceMeters": 0}}] * zeros
    listings.append({"location": {"latitude": 0, "longitude": 0, "onCountryLevel": True, "distanceMeters": 0}})
    return json.dumps({"listings": listings})


class PostcodeTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(dm.normalize_postcode(" 3511 ab "), "3511AB")
        self.assertEqual(dm.normalize_postcode("3511"), "3511")
        for bad in ("0123AB", "351", "3511 ABC", "", "utrecht"):
            self.assertIsNone(dm.normalize_postcode(bad), bad)

    def test_fit_finds_the_place_from_rounded_distances(self):
        points = [(lat, lon, round(dm.haversine_km(*HOME, lat, lon))) for lat, lon in PLACES]
        lat, lon, rms = dm.fit_home(points)
        self.assertLess(dm.haversine_km(lat, lon, *HOME), 1.0)
        self.assertLess(rms, 0.6)

    def test_locate_with_one_search_request_and_zero_means_unknown(self):
        self.addCleanup(setattr, rc, "MIN_INTERVAL_S", rc.MIN_INTERVAL_S)
        rc.MIN_INTERVAL_S = 0
        session = SearchSession(search_json(PLACES))
        home = dm.locate_postcode("3511 ab", session)
        self.assertEqual(home.postcode, "3511AB")
        self.assertLess(dm.haversine_km(home.latitude, home.longitude, *HOME), 1.0)
        (url,) = session.requested
        self.assertIn("postcode=3511AB", url)

    def test_too_few_distances_or_no_listings_is_an_error_not_a_guess(self):
        self.addCleanup(setattr, rc, "MIN_INTERVAL_S", rc.MIN_INTERVAL_S)
        rc.MIN_INTERVAL_S = 0
        for text, expected in ((search_json(PLACES[:3]), "maar 3"), ("{}", "geen advertentielijst")):
            with self.assertRaisesRegex(dm.LocateError, expected):
                dm.locate_postcode("3511AB", SearchSession(text))
        session = SearchSession("{}")
        with self.assertRaisesRegex(dm.LocateError, "geen Nederlandse postcode"):
            dm.locate_postcode("hallo", session)
        self.assertEqual(session.requested, [])  # geen verzoek voor iets dat geen postcode is


class SearchSession:
    """Geeft op elk verzoek dezelfde zoekresultaten terug."""

    def __init__(self, text):
        self.text, self.requested, self.headers = text, [], {}

    def get(self, url, timeout=0):
        from helpers import FakeResponse
        self.requested.append(url)
        return FakeResponse(self.text)


class DistanceTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        close_databases_before_cleanup(self)
        self.db = str(self.dir / "koopjes.db")

    def test_search_results_give_a_place_but_not_for_a_country_only_seller(self):
        l = mp.parse_listing(raw_listing(location={"cityName": "Zwolle", "latitude": 52.51, "longitude": 6.09,
                                                   "distanceMeters": -1000}, priorityProduct="DAGTOPPER",
                                         traits=["DAG_TOPPER_7DAYS", "PACKAGE_PREMIUM", 3]))
        self.assertEqual((l.latitude, l.longitude, l.promotion, l.traits),
                         (52.51, 6.09, "DAGTOPPER", "DAG_TOPPER_7DAYS PACKAGE_PREMIUM"))
        country = mp.parse_listing(raw_listing(location={"latitude": 0, "longitude": 0, "onCountryLevel": True},
                                               priorityProduct="NONE"))
        self.assertEqual((country.latitude, country.longitude, country.promotion), (None, None, ""))

    def test_distances_from_the_stored_place_and_by_city_for_older_listings(self):
        conn = db.connect(self.db)
        with_place = make_listing(item_id="p", city="Zwolle", latitude=52.51, longitude=6.09)
        older = make_listing(item_id="o", city="Zwolle")  # van vóór migratie 18: geen plek
        nowhere = make_listing(item_id="n", city="Ergens")
        db.sync_listings(conn, "q", [with_place, older, nowhere], "2026-09-29T10:00:00+00:00")
        self.assertEqual(dm.distances(conn, None), {})
        dm.save_home(conn, dm.Home("3511AB", *HOME))
        home = dm.load_home(conn)
        self.assertEqual(home.postcode, "3511AB")
        found = dm.distances(conn, home)
        self.assertAlmostEqual(found["p"].km, dm.haversine_km(*HOME, 52.51, 6.09), places=3)
        self.assertFalse(found["p"].approx)
        self.assertTrue(found["o"].approx)
        self.assertTrue(found["o"].label.startswith("ca. "))
        self.assertNotIn("n", found)
        # Een latere waarneming zonder plek (een oude aanroeper) laat hem staan.
        db.sync_listings(conn, "q", [make_listing(item_id="p", city="Zwolle")], "2026-09-29T11:00:00+00:00")
        self.assertEqual(db.list_places(conn)["p"][:2], (52.51, 6.09))
        dm.save_home(conn, None)
        self.assertIsNone(dm.load_home(conn))
        conn.close()


if __name__ == "__main__":
    unittest.main()
