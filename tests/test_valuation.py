"""valuation.py — de waarderingsmotor uit fase 3.

De rekenkunde wordt op synthetische comps getest (bekende invoer → bekende
mediaan en band), de database-laag op een wegwerp-koopjes.db, en het geheel
één keer op de echte `mijn_fiets.md`, want dat bestand is de invoer waarop de
taxatie in de praktijk draait.
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from helpers import make_listing, mp  # noqa: F401  (zet de repo-root in sys.path)

import db
import valuation as val


def candidate(**overrides) -> val.CompCandidate:
    """Een comp-kandidaat met bruikbare defaults; geef alleen mee wat telt.

    Met `first_seen` gaat de kandidaat via het echte databasepad
    (candidate_from_row()) in plaats van days_online rechtstreeks op
    CompCandidate te zetten — zo dekt een test met deze helper ook de
    days_online-afleiding die fetch_comp_candidates() in het echt gebruikt,
    niet alleen een synthetische waarde die toevallig lijkt op wat die
    afleiding zou opleveren."""
    if "first_seen" in overrides:
        row = dict(
            item_id="m1",
            title="Giant Defy Composite 2012",
            description="",
            price_eur=500.0,
            url="https://www.marktplaats.nl/v/x/m1",
            is_bid=0,
            days_online=None,
            disappeared_at=None,
        )
        as_of = overrides.pop("as_of", None)
        specs = overrides.pop("specs", {})
        if overrides.pop("disappeared", False):
            overrides.setdefault("disappeared_at", "2020-01-01T00:00:00+00:00")
        row.update(overrides)
        return val.candidate_from_row(row, specs, as_of=as_of)

    fields = dict(
        item_id="m1",
        title="Giant Defy Composite 2012",
        url="https://www.marktplaats.nl/v/x/m1",
        price_eur=500.0,
        specs={"frame_material": "carbon", "brake_type": "velrem", "speeds": "10"},
        groupset_tier=5,
    )
    fields.update(overrides)
    # De ladder kijkt naar de kleingeschreven tekst; standaard is dat de titel.
    fields.setdefault("text", fields["title"].lower())
    return val.CompCandidate(**fields)


DEFY = val.Subject(
    label="Giant Defy Composite",
    model_patterns=("defy", "composite"),
    family_patterns=("defy",),
    exclude_patterns=("advanced",),
    model_year=2012,
    groupset_tier=5,
    frame_material="carbon",
    brake_type="velrem",
    speeds=10,
)


class PercentileTest(unittest.TestCase):
    def test_band_of_a_known_series(self):
        low, mid, high = val.price_band([400, 450, 500, 550, 600])
        self.assertEqual(mid, 500)
        self.assertAlmostEqual(low, 440)
        self.assertAlmostEqual(high, 560)

    def test_a_single_observation_is_its_own_band(self):
        self.assertEqual(val.price_band([325]), (325, 325, 325))

    def test_an_empty_series_has_no_percentile(self):
        # Beter een duidelijke fout dan een 0 die als prijs door het rapport reist.
        with self.assertRaises(ValueError):
            val.percentile([], 0.5)


class NegotiationFactorTest(unittest.TestCase):
    def candidates(self, quick: int, stale: int, quick_price=800.0, stale_price=1000.0):
        made = [
            candidate(item_id=f"q{i}", price_eur=quick_price, days_online=7, disappeared=True)
            for i in range(quick)
        ]
        made += [
            candidate(item_id=f"s{i}", price_eur=stale_price, days_online=90)
            for i in range(stale)
        ]
        return made

    def test_too_few_observations_means_no_measured_factor(self):
        self.assertIsNone(val.empirical_negotiation_factor(self.candidates(5, 40)))
        self.assertIsNone(val.empirical_negotiation_factor(self.candidates(40, 5)))

    def test_the_ratio_of_the_two_medians(self):
        factor = val.empirical_negotiation_factor(self.candidates(20, 20))
        self.assertIsNotNone(factor)
        self.assertAlmostEqual(factor[0], 0.8)
        self.assertEqual(factor[1:], (20, 20))

    def test_an_implausible_ratio_is_discarded(self):
        # Een factor van 0,2 zegt niets over onderhandelen en alles over een
        # scheve steekproef; dan blijft de heuristische default staan.
        self.assertIsNone(
            val.empirical_negotiation_factor(self.candidates(20, 20, quick_price=200.0))
        )

    def test_a_still_online_listing_counts_as_a_stayer_too(self):
        # Regression: days_online was only ever set by sweep_disappeared(),
        # so a listing that's simply been online for 90 days without being
        # swept had days_online=NULL and never made it into the "blijvers"
        # group at all — only the worst-priced tail that had disappeared did.
        as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
        first_seen_90_days_ago = (as_of - timedelta(days=90)).isoformat(timespec="seconds")
        quick = [
            candidate(item_id=f"q{i}", price_eur=800.0, days_online=7, disappeared=True)
            for i in range(20)
        ]
        still_online = [
            candidate(
                item_id=f"s{i}", price_eur=1000.0,
                first_seen=first_seen_90_days_ago, as_of=as_of,
            )
            for i in range(20)
        ]
        factor = val.empirical_negotiation_factor(quick + still_online)
        self.assertIsNotNone(factor)
        self.assertAlmostEqual(factor[0], 0.8)
        self.assertEqual(factor[1:], (20, 20))


class DeriveDaysOnlineTest(unittest.TestCase):
    """_derive_days_online() — the pure function candidate_from_row() calls
    to fill in days_online for a still-online listing whose column is NULL.
    Same two safety nets as sweep_disappeared() in db.py: import_legacy()
    can write an empty first_seen, and an unreadable date must not crash a
    taxatie run."""

    def test_missing_first_seen_yields_none(self):
        as_of = datetime.now(timezone.utc)
        self.assertIsNone(val._derive_days_online("", as_of))
        self.assertIsNone(val._derive_days_online(None, as_of))

    def test_unparseable_first_seen_yields_none(self):
        self.assertIsNone(val._derive_days_online("niet-een-datum", datetime.now(timezone.utc)))

    def test_derives_days_since_first_seen(self):
        as_of = datetime(2026, 4, 1, tzinfo=timezone.utc)
        first_seen = "2026-01-01T00:00:00+00:00"
        self.assertEqual(val._derive_days_online(first_seen, as_of), 90)


class CompLadderTest(unittest.TestCase):
    def test_the_highest_rung_with_enough_comps_wins(self):
        comps = [candidate(item_id=f"m{i}") for i in range(5)]
        # Eentje die alleen de familie deelt, om te zien dat trede 1 blijft staan.
        comps.append(candidate(item_id="other", title="Giant Defy 1 2013", groupset_tier=3))
        chosen = val.select_comps(DEFY, comps)
        self.assertEqual(chosen.rung, 1)
        self.assertEqual(chosen.n, 5)
        self.assertEqual(chosen.confidence, "hoog")

    def test_it_falls_through_to_a_broader_rung(self):
        # Zelfde familie, ander model en andere groepset: trede 1 vindt niets,
        # trede 2 wel.
        comps = [
            candidate(item_id=f"m{i}", title="Giant Defy 2 2013", groupset_tier=3)
            for i in range(6)
        ]
        chosen = val.select_comps(DEFY, comps)
        self.assertEqual(chosen.rung, 2)
        self.assertEqual(chosen.confidence, "midden")

    def test_too_few_comps_anywhere_is_indicative_at_best(self):
        comps = [candidate(item_id=f"m{i}") for i in range(2)]
        chosen = val.select_comps(DEFY, comps)
        self.assertEqual(chosen.rung, 1)
        self.assertEqual(chosen.n, 2)
        self.assertEqual(chosen.confidence, "indicatief")

    def test_a_dearer_trim_of_the_same_model_is_not_a_comp(self):
        # Defy Advanced is een hogere carbonlaag; meerekenen trekt de taxatie
        # omhoog (mijn_fiets.md, plan §4).
        comps = [
            candidate(item_id=f"a{i}", title="Giant Defy Advanced Composite 2012")
            for i in range(6)
        ]
        self.assertIsNone(val.select_comps(DEFY, comps))

    def test_a_year_in_the_title_counts_as_the_model_year(self):
        self.assertEqual(val.candidate_year(candidate(title="Giant Defy 2012")), 2012)

    def test_a_labelled_year_in_the_specs_wins_over_the_title(self):
        # De titel kan een ander jaartal dragen ("koopje 2024!"); een gelabeld
        # bouwjaar uit extract_specs() is harder.
        found = candidate(title="Giant Defy Composite koopje 2024", specs={"model_year": "2012"})
        self.assertEqual(val.candidate_year(found), 2012)

    def test_without_a_year_an_ad_is_not_comparable(self):
        comps = [
            candidate(item_id=f"m{i}", title="Giant Defy Composite racefiets")
            for i in range(6)
        ]
        self.assertIsNone(val.select_comps(DEFY, comps))

    def test_nothing_comparable_at_all(self):
        # Ander segment op alle drie de kenmerken die trede 3 gebruikt.
        stadsfiets = candidate(
            title="Batavus stadsfiets 2012",
            specs={"frame_material": "aluminium", "brake_type": "schijfrem", "speeds": "8"},
            groupset_tier=None,
        )
        self.assertIsNone(val.select_comps(DEFY, [stadsfiets]))

    def test_another_brand_in_the_same_segment_is_a_rung_three_comp(self):
        # Trede 3 is expres merkonafhankelijk (§6): carbon, velrem, 10-11 speed
        # en het juiste bouwjaarvenster maken een fiets vergelijkbaar, ook als
        # er geen Giant op staat.
        comps = [
            candidate(item_id=f"m{i}", title="Cube Peloton Race 2013", groupset_tier=3)
            for i in range(6)
        ]
        chosen = val.select_comps(DEFY, comps)
        self.assertEqual(chosen.rung, 3)
        self.assertEqual(chosen.confidence, "laag")


class ValueSubjectTest(unittest.TestCase):
    def comps(self, prices):
        return [
            candidate(item_id=f"m{i}", price_eur=price) for i, price in enumerate(prices)
        ]

    def test_the_band_is_the_corrected_comp_band(self):
        result = val.value_subject(DEFY, self.comps([400, 450, 500, 550, 600]))
        # Mediaan 500 en 20e/80e percentiel 440/560, maal de heuristische
        # E2-correctie (0,85 / 0,875 / 0,90).
        self.assertAlmostEqual(result.mid_eur, 437.5)
        self.assertAlmostEqual(result.low_eur, 374.0)
        self.assertAlmostEqual(result.high_eur, 504.0)
        self.assertEqual(result.confidence, "hoog")

    def test_every_number_shown_has_an_evidence_line(self):
        result = val.value_subject(DEFY, self.comps([400, 450, 500, 550, 600]))
        kinds = [e.kind for e in result.evidence]
        self.assertIn("comp", kinds)
        self.assertIn("depreciation", kinds)
        self.assertGreaterEqual(len(result.evidence), 5)
        # De gebruikte trede en de n staan er met zoveel woorden in.
        self.assertTrue(any("trede 1" in e.note and "n=5" in e.note for e in result.evidence))
        # En elke comp is terug te klikken.
        self.assertTrue(all(e.ref_url for e in result.evidence if e.ref_id))

    def test_a_measured_factor_replaces_the_heuristic_one(self):
        result = val.value_subject(
            DEFY, self.comps([400, 450, 500, 550, 600]), negotiation=(0.80, 25, 30)
        )
        self.assertAlmostEqual(result.mid_eur, 400.0)
        self.assertTrue(any("gemeten correctie" in e.note for e in result.evidence))
        self.assertTrue(any("niet hetzelfde als verkocht" in e.note for e in result.evidence))

    def test_no_comps_means_no_valuation(self):
        # Liever geen getal dan een getal uit de lucht.
        stadsfiets = candidate(
            title="Batavus stadsfiets 2012",
            specs={"frame_material": "aluminium", "brake_type": "schijfrem", "speeds": "8"},
            groupset_tier=None,
        )
        self.assertIsNone(val.value_subject(DEFY, [stadsfiets]))

    def test_a_thin_comp_set_says_so_and_scores_lower(self):
        thin = val.value_subject(DEFY, self.comps([400, 600]))
        thick = val.value_subject(DEFY, self.comps([400, 450, 500, 550, 600]))
        self.assertEqual(thin.confidence, "indicatief")
        self.assertEqual(thick.confidence, "hoog")
        self.assertTrue(any("onder de 5 comps" in e.note for e in thin.evidence))

    def test_parts_are_summed_with_the_bundle_factor(self):
        result = val.value_subject(
            DEFY,
            self.comps([400, 450, 500, 550, 600]),
            components=[
                val.Component("frame", (300.0,)),
                val.Component("wielset", (200.0,)),
            ],
        )
        self.assertTrue(any("bundelfactor" in e.note for e in result.evidence))
        # E3 = (300 + 200) * 0,80 = 400, meegewogen naast E1 van 437,50.
        self.assertLess(result.mid_eur, 437.5)
        self.assertGreater(result.mid_eur, 400.0)

    def test_a_component_without_observations_weighs_nothing(self):
        with_nothing = val.value_subject(
            DEFY, self.comps([400, 450, 500, 550, 600]),
            components=[val.Component("wielset")],
        )
        without = val.value_subject(DEFY, self.comps([400, 450, 500, 550, 600]))
        self.assertEqual(with_nothing.mid_eur, without.mid_eur)
        self.assertTrue(
            any("geen prijswaarnemingen" in e.note for e in with_nothing.evidence)
        )

    def test_an_extra_only_counts_for_what_a_buyer_pays_for_it(self):
        base = val.value_subject(DEFY, self.comps([400, 450, 500, 550, 600]))
        with_wheels = val.value_subject(
            DEFY,
            self.comps([400, 450, 500, 550, 600]),
            extras=[val.Component("CSC carbon wielset", (300.0,))],
        )
        # Los €300 waard, waarvan de helft meetelt bij een complete fiets.
        self.assertAlmostEqual(with_wheels.mid_eur - base.mid_eur, 150.0)
        self.assertTrue(any("andermans upgrades" in e.note for e in with_wheels.evidence))

    def test_an_extra_without_a_price_is_named_not_guessed(self):
        base = val.value_subject(DEFY, self.comps([400, 450, 500, 550, 600]))
        with_wheels = val.value_subject(
            DEFY, self.comps([400, 450, 500, 550, 600]),
            extras=[val.Component("CSC carbon wielset")],
        )
        self.assertEqual(with_wheels.mid_eur, base.mid_eur)
        self.assertTrue(
            any("ligt hoger dan hier staat" in e.note for e in with_wheels.evidence)
        )


class OwnerBikeTest(unittest.TestCase):
    """De echte mijn_fiets.md is de invoer waarop dit in de praktijk draait."""

    def setUp(self):
        self.text = Path(__file__).resolve().parent.parent.joinpath("mijn_fiets.md").read_text(
            encoding="utf-8"
        )

    def test_the_intake_document_parses(self):
        bike = val.parse_owner_bike(self.text)
        self.assertEqual(bike.label, "Giant Defy Composite")
        self.assertEqual(bike.specs["model_year"], "2012")
        self.assertEqual(bike.specs["frame_material"], "carbon")
        self.assertEqual(bike.wheelset_price_eur, 300.0)

    def test_the_subject_derived_from_it(self):
        subject = val.subject_from_owner_bike(val.parse_owner_bike(self.text))
        self.assertEqual(subject.model_year, 2012)
        self.assertEqual(subject.groupset_tier, 5)
        self.assertEqual(subject.speeds, 10)
        self.assertEqual(subject.brake_type, "velrem")
        # Composite mag niet met Advanced vergeleken worden.
        self.assertIn("advanced", subject.exclude_patterns)
        self.assertEqual(subject.family_patterns, ("defy",))

    def test_a_document_without_the_scoring_block_is_an_error(self):
        # Stil doorgaan zou een taxatie opleveren op een fiets die niemand
        # heeft ingevuld.
        with self.assertRaises(ValueError):
            val.parse_owner_bike("# Mijn fiets\n\nGeen tabel, geen blok.\n")


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.conn = db.connect(str(Path(self._tmp.name) / "koopjes.db"))
        self.addCleanup(self.conn.close)
        self.now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def add_listings(self, listings, query="giant defy"):
        db.sync_listings(self.conn, query, listings, self.now)

    def test_candidates_come_back_with_their_specs(self):
        self.add_listings([make_listing(item_id="a", title="Giant Defy Composite 2012",
                                        price_eur=600.0)])
        db.sync_listing_specs(self.conn, {"a": {"frame_material": "carbon", "speeds": "10"}})

        (found,) = val.fetch_comp_candidates(self.conn)
        self.assertEqual(found.item_id, "a")
        self.assertEqual(found.specs["frame_material"], "carbon")
        self.assertEqual(found.price_eur, 600.0)

    def test_the_groupset_tier_is_derived_from_the_text(self):
        # Hij staat niet in `spec` — extract_specs() laat de groepset met opzet
        # aan detect_groupset() over.
        self.add_listings([make_listing(item_id="a", title="Giant Defy Composite 2012",
                                        description="Shimano Ultegra", price_eur=600.0)])
        (found,) = val.fetch_comp_candidates(self.conn)
        self.assertEqual(found.groupset_tier, 5)

    def test_bids_and_priceless_listings_stay_out_of_the_comps(self):
        self.add_listings([
            make_listing(item_id="vast", price_eur=500.0),
            make_listing(item_id="bod", price_eur=500.0, price_is_bid=True),
            make_listing(item_id="geenprijs", price_eur=None),
        ])
        found = {c.item_id for c in val.fetch_comp_candidates(self.conn)}
        self.assertEqual(found, {"vast"})

    def test_listings_outside_the_window_are_left_out(self):
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(timespec="seconds")
        db.sync_listings(self.conn, "giant defy", [make_listing(item_id="oud", price_eur=500.0)], old)
        self.add_listings([make_listing(item_id="nieuw", price_eur=500.0)])

        recent = {c.item_id for c in val.fetch_comp_candidates(self.conn)}
        self.assertEqual(recent, {"nieuw"})
        everything = {c.item_id for c in val.fetch_comp_candidates(self.conn, window_days=0)}
        self.assertEqual(everything, {"oud", "nieuw"})

    def test_an_owned_item_is_updated_in_place(self):
        first = val.upsert_owned_item(self.conn, kind="bike", label="Giant Defy Composite",
                                      specs={"model_year": "2012"})
        again = val.upsert_owned_item(self.conn, kind="bike", label="Giant Defy Composite",
                                      specs={"model_year": "2012", "speeds": "10"})
        self.assertEqual(first, again)
        rows = val.load_owned_items(self.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0]["specs_json"])["speeds"], "10")

    def test_a_valuation_is_stored_with_its_evidence(self):
        valuation = val.Valuation(
            subject_type="owned_item", subject_id="1", scenario="compleet",
            low_eur=400.0, mid_eur=500.0, high_eur=600.0, confidence="midden",
            evidence=(
                val.Evidence(kind="comp", note="trede 2, n=7", price_eur=500.0,
                             ref_id="m1", ref_url="https://example.invalid/m1"),
                val.Evidence(kind="depreciation", note="×0,875"),
            ),
        )
        valuation_id = val.save_valuation(self.conn, valuation)

        (stored,) = self.conn.execute("SELECT * FROM valuation").fetchall()
        self.assertEqual(stored["mid_eur"], 500.0)
        self.assertEqual(stored["method_version"], val.METHOD_VERSION)
        self.assertIsNotNone(stored["created_at"])
        evidence = self.conn.execute(
            "SELECT * FROM valuation_evidence WHERE valuation_id = ?", (valuation_id,)
        ).fetchall()
        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[0]["ref_url"], "https://example.invalid/m1")

    def test_a_valuation_never_lands_in_the_raw_observations(self):
        # De regel uit §5: listing_price en component_price zijn waarneming.
        # Zodra een taxatie daarin belandt, voedt de waardering zichzelf.
        self.add_listings([make_listing(item_id="a", price_eur=500.0)])
        before = self.conn.execute("SELECT COUNT(*) AS n FROM listing_price").fetchone()["n"]

        val.save_valuation(self.conn, val.Valuation(
            subject_type="owned_item", subject_id="1", scenario="compleet",
            low_eur=400.0, mid_eur=500.0, high_eur=600.0, confidence="midden",
            evidence=(val.Evidence(kind="comp", note="x", price_eur=500.0),),
        ))

        after = self.conn.execute("SELECT COUNT(*) AS n FROM listing_price").fetchone()["n"]
        self.assertEqual(after, before)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) AS n FROM component_price").fetchone()["n"], 0
        )

    def test_negotiation_factor_counts_still_online_listings_via_the_real_db_path(self):
        # 20 quick sales: added now, then swept a week later so
        # sweep_disappeared() marks them gone with days_online=7.
        quick = [make_listing(item_id=f"quick{i}", price_eur=800.0) for i in range(20)]
        self.add_listings(quick)
        a_week_later = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(timespec="seconds")
        db.sweep_disappeared(self.conn, "giant defy", set(), a_week_later)

        # 20 stayers: added afterwards with a first_seen 90 days back and
        # never swept, so days_online is NULL on disk and must be derived
        # from first_seen on read, not left out of the "blijvers" group.
        old_first_seen = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds")
        stayers = [make_listing(item_id=f"stayer{i}", price_eur=1000.0) for i in range(20)]
        db.sync_listings(self.conn, "giant defy", stayers, old_first_seen)

        candidates = val.fetch_comp_candidates(self.conn)
        factor = val.empirical_negotiation_factor(candidates)
        self.assertIsNotNone(factor)
        self.assertAlmostEqual(factor[0], 0.8)
        self.assertEqual(factor[1:], (20, 20))

    def test_component_prices_are_read_per_model(self):
        self.conn.execute(
            "INSERT INTO model (kind, pattern, model) VALUES ('wheelset', 'csc 50', 'CSC 50mm')"
        )
        model_id = self.conn.execute(
            "SELECT id FROM model WHERE pattern = 'csc 50'"
        ).fetchone()["id"]
        for price in (180.0, 220.0):
            self.conn.execute(
                "INSERT INTO component_price (model_id, observed_at, price_eur) VALUES (?, ?, ?)",
                (model_id, self.now, price),
            )
        self.conn.commit()

        self.assertEqual(sorted(val.fetch_component_prices(self.conn, model_id)), [180.0, 220.0])
        self.assertEqual(val.fetch_component_prices(self.conn, model_id + 99), [])


class EndToEndTest(DatabaseTest):
    """De acceptatie-eis van fase 3: de eigen fiets levert een band met
    minstens vijf bewijsregels, en elk getal is terug te voeren op er een."""

    def test_the_owners_bike_gets_a_band_and_its_evidence(self):
        prices = [550.0, 600.0, 650.0, 700.0, 750.0, 800.0]
        listings = [
            make_listing(
                item_id=f"m{i}",
                title=f"Giant Defy Composite 2012 maat 56 - {price:.0f} euro",
                description="Shimano Ultegra, carbon, velremmen, 10 speed",
                price_eur=price,
            )
            for i, price in enumerate(prices)
        ]
        # Een Advanced en een bied-advertentie die er niet in horen.
        listings.append(make_listing(item_id="adv", title="Giant Defy Advanced 2012",
                                     description="Shimano Ultegra", price_eur=1400.0))
        listings.append(make_listing(item_id="bod", title="Giant Defy Composite 2012",
                                     description="Shimano Ultegra", price_eur=1200.0,
                                     price_is_bid=True))
        self.add_listings(listings)
        db.sync_listing_specs(
            self.conn,
            {l.item_id: {"frame_material": "carbon", "brake_type": "velrem", "speeds": "10"}
             for l in listings},
        )

        text = Path(__file__).resolve().parent.parent.joinpath("mijn_fiets.md").read_text(
            encoding="utf-8"
        )
        bike = val.parse_owner_bike(text)
        subject = val.subject_from_owner_bike(bike)
        candidates = val.fetch_comp_candidates(self.conn)
        result = val.value_subject(
            subject, candidates, subject_id="1", scenario="compleet met carbon wielset"
        )

        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result.evidence), 5)
        self.assertLess(result.low_eur, result.mid_eur)
        self.assertLess(result.mid_eur, result.high_eur)
        # De mediaan van de zes comps is 675; de taxatie ligt daar met de
        # E2-correctie onder, en zeker niet op het niveau van de Advanced.
        self.assertLess(result.mid_eur, 675.0)
        self.assertNotIn("adv", [e.ref_id for e in result.evidence])
        self.assertNotIn("bod", [e.ref_id for e in result.evidence])

        valuation_id = val.save_valuation(self.conn, result)
        stored = self.conn.execute(
            "SELECT COUNT(*) AS n FROM valuation_evidence WHERE valuation_id = ?",
            (valuation_id,),
        ).fetchone()["n"]
        self.assertEqual(stored, len(result.evidence))


if __name__ == "__main__":
    unittest.main()
