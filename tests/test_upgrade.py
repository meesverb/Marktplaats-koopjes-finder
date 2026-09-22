"""upgrade.py — de upgrade-finder en biedlogica uit fase 5 (PLAN_FIETSWAARDE.md §7).

De drie acceptatie-eisen van de fase staan expliciet in deze suite:
met fixture-advertenties komt de verwachte volgorde eruit, een fiets buiten
de maat verschijnt nooit, en een biedadvertentie zonder opgehaald bod valt
niet stil terug op €0."""
import os
import sqlite3
import tempfile
import unittest

from helpers import make_listing, mp, repo_file

import db
import scoring as sc
import upgrade as up
import valuation as val


def config():
    return sc.load_config(repo_file("scoring_config.json"))


# De eigen fiets uit mijn_fiets.md: carbon endurance-frame uit 2012, Ultegra
# 10-speed mechanisch, velremmen, merk-carbon wielen, geen extra's.
OWNER_SPECS = {
    "frame_material": "carbon",
    "frame_tier": "composite (instapcarbon, endurance-geometrie)",
    "model_year": "2012",
    "size_cm": "56",
    "groupset_tier": "5   (Ultegra)",
    "speeds": "10",
    "electronic": "nee",
    "brake_type": "velrem",
    "wheel_type": "carbon clincher 50mm, CSC (Novatec-naven), velrem, 18mm binnen",
    "extras": "geen (de Roam gaat niet mee)",
    "budget_extra": "max €250 boven op de opbrengst",
}


def baseline_score(as_of_year=2026):
    build = sc.build_from_owner_specs(OWNER_SPECS)
    return sc.score_build(build, config(), as_of_year=as_of_year).total


def owner_wheels():
    build = sc.build_from_owner_specs(OWNER_SPECS)
    return (build.wheel_material, build.wheel_branded)


class SizeGateTest(unittest.TestCase):
    """De maatpoort uit §7: geen score maar een harde ja/nee."""

    def test_matching_bucket_fits(self):
        self.assertEqual(up.size_verdict("56 cm", 56), up.SIZE_FITS)

    def test_neighbouring_size_fits_within_tolerance(self):
        self.assertEqual(up.size_verdict("54 cm", 56), up.SIZE_FITS)

    def test_far_off_size_does_not_fit(self):
        self.assertEqual(up.size_verdict("48 cm", 56), up.SIZE_WRONG)
        self.assertEqual(up.size_verdict("62 cm", 56), up.SIZE_WRONG)

    def test_missing_size_is_unknown_not_wrong(self):
        # Op Marktplaats staat de maat vaak alleen in de omschrijving. Leeg is
        # iets anders dan "past niet", en dat onderscheid is de hele reden dat
        # deze functie drie uitkomsten heeft in plaats van twee.
        self.assertEqual(up.size_verdict("", 56), up.SIZE_UNKNOWN)
        self.assertEqual(up.size_verdict("onbekend", 56), up.SIZE_UNKNOWN)

    def test_tolerance_is_adjustable(self):
        self.assertEqual(up.size_verdict("53 cm", 56, tolerance_cm=0), up.SIZE_WRONG)
        self.assertEqual(up.size_verdict("53 cm", 56, tolerance_cm=4), up.SIZE_FITS)


class BrakeRouteTest(unittest.TestCase):
    def test_rim_and_disc(self):
        self.assertEqual(up.brake_route("velrem"), up.ROUTE_RIM)
        self.assertEqual(up.brake_route("schijfrem"), up.ROUTE_DISC)
        self.assertEqual(up.brake_route("hydraulische schijfrem"), up.ROUTE_DISC)
        self.assertEqual(up.brake_route("mechanische schijfrem"), up.ROUTE_DISC)

    def test_unknown_brake_type_is_not_read_as_rim(self):
        # Een onbekend remtype als velrem lezen zou de kandidaat een
        # wielsetbonus geven die hij misschien niet kan gebruiken.
        self.assertEqual(up.brake_route(None), up.ROUTE_UNKNOWN)
        self.assertEqual(up.brake_route(""), up.ROUTE_UNKNOWN)


class BudgetTest(unittest.TestCase):
    def test_disc_route_may_spend_the_wheelset(self):
        budgets = up.budgets_from_valuation(800, wheelset_value_eur=200, extra_budget_eur=250)
        self.assertAlmostEqual(budgets.rim.amount, 1050)
        self.assertAlmostEqual(budgets.disc.amount, 1250)

    def test_without_wheelset_observations_both_budgets_are_equal(self):
        # Fase 3 liet dit expliciet liggen: zonder prijswaarnemingen van losse
        # wielsets is er geen bedrag, en dan wordt er geen bedrag verzonnen.
        budgets = up.budgets_from_valuation(800, wheelset_value_eur=None, extra_budget_eur=250)
        self.assertAlmostEqual(budgets.rim.amount, budgets.disc.amount)
        self.assertTrue(any("geen prijswaarnemingen" in r for r in budgets.disc.reasons))

    def test_unknown_brake_type_gets_the_conservative_budget(self):
        budgets = up.budgets_from_valuation(800, wheelset_value_eur=200, extra_budget_eur=250)
        self.assertEqual(budgets.for_route(up.ROUTE_UNKNOWN).amount, budgets.rim.amount)

    def test_every_budget_carries_its_sum(self):
        budgets = up.budgets_from_valuation(800, wheelset_value_eur=200, extra_budget_eur=250)
        self.assertTrue(budgets.rim.reasons)
        self.assertTrue(any("250" in r for r in budgets.rim.reasons))


class OwnerWheelsTest(unittest.TestCase):
    def test_better_wheels_move_along(self):
        build = sc.Build(wheel_material="aluminium")
        moved, reason = up.with_owner_wheels(build, ("carbon", True), config())
        self.assertEqual(moved.wheel_material, "carbon")
        self.assertTrue(moved.wheel_branded)
        self.assertIn("verhuist mee", reason)

    def test_candidate_with_better_wheels_keeps_its_own(self):
        # Een kandidaat met eigen merk-carbon gaat er niet op vooruit; dan
        # verandert er niets en is er ook geen reden om te tonen.
        build = sc.Build(wheel_material="carbon", wheel_branded=True)
        moved, reason = up.with_owner_wheels(build, ("carbon", True), config())
        self.assertIs(moved, build)
        self.assertIsNone(reason)

    def test_no_owner_wheels_is_a_no_op(self):
        build = sc.Build(wheel_material="aluminium")
        moved, reason = up.with_owner_wheels(build, (None, False), config())
        self.assertIs(moved, build)
        self.assertIsNone(reason)


class EffectivePriceTest(unittest.TestCase):
    def test_fixed_price_gets_the_negotiation_factor(self):
        listing = make_listing(price_eur=1000.0)
        price = up.effective_price(listing, negotiation_factor=0.9)
        self.assertAlmostEqual(price.amount, 900)
        self.assertEqual(price.asking_eur, 1000)
        self.assertIn("1000", price.basis)

    def test_asking_price_stays_visible_next_to_the_effective_one(self):
        # §7 eist allebei: een gecorrigeerd bedrag mag nooit voor een
        # vraagprijs worden aangezien.
        price = up.effective_price(make_listing(price_eur=500.0), negotiation_factor=0.8)
        self.assertNotEqual(price.amount, price.asking_eur)
        self.assertEqual(price.asking_eur, 500)

    def test_listing_without_a_price_has_no_effective_price(self):
        price = up.effective_price(make_listing(price_eur=None))
        self.assertIsNone(price.amount)


class BidEntryPriceTest(unittest.TestCase):
    """De acceptatie-eis: een biedadvertentie zonder opgehaald bod valt niet
    stil terug op €0."""

    def test_unfetched_bid_does_not_fall_back_to_zero(self):
        listing = make_listing(
            price_type="MIN_BID", price_is_bid=True, price_eur=200.0, bid_count=None
        )
        price = up.effective_price(listing)
        self.assertEqual(price.amount, 200.0)
        self.assertIn("niet opgehaald", price.basis)

    def test_unfetched_bid_without_any_price_stays_unknown(self):
        listing = make_listing(
            price_type="FAST_BID", price_is_bid=True, price_eur=None, bid_count=None
        )
        price = up.effective_price(listing)
        self.assertIsNone(price.amount)
        self.assertNotEqual(price.amount, 0)

    def test_unfetched_bid_never_uses_the_minimum_bid(self):
        # bid_minimum kan uit een eerdere run blijven staan; zonder biedaantal
        # weten we niet of dat minimum nog geldt.
        listing = make_listing(
            price_type="MIN_BID",
            price_is_bid=True,
            price_eur=200.0,
            bid_minimum=120.0,
            bid_count=None,
        )
        self.assertEqual(up.effective_price(listing).amount, 200.0)

    def test_no_bids_yet_means_the_minimum_is_the_way_in(self):
        listing = make_listing(
            price_type="MIN_BID",
            price_is_bid=True,
            price_eur=200.0,
            bid_minimum=120.0,
            bid_count=0,
        )
        price = up.effective_price(listing)
        self.assertEqual(price.amount, 120.0)
        self.assertIn("nog geen bod", price.basis)
        # De vraagprijs blijft ernaast staan: hij is niet overschreven door het
        # minimumbod (CLAUDE.md, "Valkuilen").
        self.assertEqual(price.asking_eur, 200.0)

    def test_standing_bid_on_a_fast_bid_is_the_entry_price(self):
        listing = make_listing(
            price_type="FAST_BID", price_is_bid=True, price_eur=150.0, bid_count=3
        )
        price = up.effective_price(listing)
        self.assertEqual(price.amount, 150.0)
        self.assertEqual(price.basis, "huidig bod")

    def test_min_bid_with_bids_is_labelled_for_what_it_is(self):
        # Bij een MIN_BID staat in price_eur de hoogste van vraagprijs en bod;
        # welke van de twee is niet te zien, dus zegt het etiket dat ook.
        listing = make_listing(
            price_type="MIN_BID", price_is_bid=True, price_eur=220.0, bid_count=2
        )
        self.assertIn("hoogste bod", up.effective_price(listing).basis)

    def test_a_bid_is_never_negotiated_down(self):
        listing = make_listing(
            price_type="FAST_BID", price_is_bid=True, price_eur=150.0, bid_count=1
        )
        self.assertEqual(up.effective_price(listing, negotiation_factor=0.5).amount, 150.0)


class ValueEstimateTest(unittest.TestCase):
    def test_observed_secondhand_average_beats_the_search_median(self):
        listing = make_listing(
            ref_label="Giant TCR", ref_market_avg=900.0, ref_market_count=4
        )
        estimate = up.estimate_value(listing, median_eur=500.0, negotiation_factor=1.0)
        self.assertAlmostEqual(estimate.amount, 900.0)
        self.assertIn("Giant TCR", estimate.basis)

    def test_thin_reference_data_falls_back_to_the_median(self):
        listing = make_listing(ref_market_avg=900.0, ref_market_count=1)
        estimate = up.estimate_value(listing, median_eur=500.0, negotiation_factor=1.0)
        self.assertAlmostEqual(estimate.amount, 500.0)

    def test_no_benchmark_means_no_estimate(self):
        estimate = up.estimate_value(make_listing(), median_eur=None)
        self.assertIsNone(estimate.amount)

    def test_asking_price_benchmarks_are_corrected_downwards(self):
        # Zowel het 2e-hands gemiddelde als de mediaan zijn vraagprijzen; zonder
        # de E2-correctie zou elke biedadvertentie gunstig uitvallen puur omdat
        # er nog niet geboden is.
        estimate = up.estimate_value(make_listing(), median_eur=1000.0, negotiation_factor=0.85)
        self.assertAlmostEqual(estimate.amount, 850.0)


class BidHeadroomTest(unittest.TestCase):
    def test_headroom_is_value_minus_entry_price(self):
        listing = make_listing(
            price_type="FAST_BID", price_is_bid=True, price_eur=300.0, bid_count=2
        )
        row = up.bid_headroom(listing, median_eur=1000.0, negotiation_factor=1.0)
        self.assertAlmostEqual(row.headroom_eur, 700.0)

    def test_no_entry_price_means_no_headroom_not_a_full_one(self):
        listing = make_listing(
            price_type="FAST_BID", price_is_bid=True, price_eur=None, bid_count=None
        )
        row = up.bid_headroom(listing, median_eur=1000.0)
        self.assertIsNone(row.headroom_eur)
        self.assertTrue(row.note)

    def test_no_estimate_means_no_headroom(self):
        listing = make_listing(
            price_type="FAST_BID", price_is_bid=True, price_eur=300.0, bid_count=1
        )
        row = up.bid_headroom(listing, median_eur=None)
        self.assertIsNone(row.headroom_eur)

    def test_panel_sorts_on_headroom_and_skips_fixed_prices(self):
        bargain = make_listing(
            item_id="cheap", price_type="FAST_BID", price_is_bid=True,
            price_eur=200.0, bid_count=1,
        )
        pricey = make_listing(
            item_id="dear", price_type="FAST_BID", price_is_bid=True,
            price_eur=800.0, bid_count=1,
        )
        fixed = make_listing(item_id="fixed", price_eur=100.0)
        rows = up.bid_panel([pricey, fixed, bargain], median_eur=1000.0, negotiation_factor=1.0)
        self.assertEqual([r.listing.item_id for r in rows], ["cheap", "dear"])

    def test_unknown_headroom_sinks_to_the_bottom(self):
        known = make_listing(
            item_id="known", price_type="FAST_BID", price_is_bid=True,
            price_eur=900.0, bid_count=1,
        )
        unknown = make_listing(
            item_id="unknown", price_type="FAST_BID", price_is_bid=True,
            price_eur=None, bid_count=None,
        )
        rows = up.bid_panel([unknown, known], median_eur=1000.0, negotiation_factor=1.0)
        self.assertEqual([r.listing.item_id for r in rows], ["known", "unknown"])


def upgrade_listing(**overrides):
    """Een advertentie die op elke dimensie boven de eigen fiets uitkomt."""
    fields = dict(
        item_id="up1",
        title="Giant TCR Advanced 2019 carbon racefiets",
        description=(
            "Bouwjaar 2019, carbon frame, Shimano Ultegra Di2 11 speed, "
            "hydraulische schijfremmen, carbon wielen van Zipp."
        ),
        frame_height="56 cm",
        groupset="Shimano Ultegra (elektronisch)",
        groupset_tier=5,
        price_eur=1000.0,
    )
    fields.update(overrides)
    return make_listing(**fields)


def find(listings, **overrides):
    kwargs = dict(
        baseline=baseline_score(),
        config=config(),
        budgets=up.budgets_from_valuation(1000, extra_budget_eur=250),
        target_size_cm=56.0,
        owner_wheels=owner_wheels(),
        owner_already_has=frozenset({"computer"}),
        negotiation_factor=1.0,
        as_of_year=2026,
    )
    kwargs.update(overrides)
    return up.find_upgrades(listings, **kwargs)


class FindUpgradesTest(unittest.TestCase):
    def test_a_modern_bike_beats_the_baseline(self):
        result = find([upgrade_listing()])
        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertGreater(candidate.quality.total, baseline_score())
        self.assertEqual(candidate.budget.route, up.ROUTE_DISC)

    def test_a_bike_outside_the_size_never_appears(self):
        """Acceptatie-eis van de fase."""
        wrong = upgrade_listing(item_id="wrong", frame_height="48 cm")
        result = find([wrong])
        self.assertEqual(result.candidates, ())
        self.assertEqual(len(result.rejected), 1)
        self.assertIn(up.SIZE_WRONG, result.rejected[0].reason)

    def test_size_gate_holds_even_for_a_free_bike(self):
        # De poort staat vóór de prijs: geen enkele korting maakt een fiets
        # die niet past alsnog een kandidaat.
        wrong = upgrade_listing(item_id="wrong", frame_height="48 cm", price_eur=1.0)
        self.assertEqual(find([wrong]).candidates, ())

    def test_unknown_size_is_kept_but_flagged(self):
        result = find([upgrade_listing(frame_height="")])
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].size, up.SIZE_UNKNOWN)
        self.assertTrue(any("framemaat" in r for r in result.candidates[0].reasons))

    def test_strict_size_drops_the_unknowns(self):
        result = find([upgrade_listing(frame_height="")], allow_unknown_size=False)
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.rejected[0].reason, up.SIZE_UNKNOWN)

    def test_a_worse_bike_is_rejected_with_a_reason(self):
        worse = make_listing(
            item_id="worse",
            title="Aluminium racefiets Shimano Sora",
            description="Aluminium frame, Shimano Sora 8 speed, velremmen, aluminium wielen.",
            frame_height="56 cm",
            groupset_tier=2,
            price_eur=200.0,
        )
        result = find([worse])
        self.assertEqual(result.candidates, ())
        self.assertIn("niet beter", result.rejected[0].reason)

    def test_over_budget_is_rejected(self):
        result = find([upgrade_listing(price_eur=5000.0)])
        self.assertEqual(result.candidates, ())
        self.assertIn("boven budget", result.rejected[0].reason)

    def test_free_listing_does_not_become_an_infinite_bargain(self):
        result = find([upgrade_listing(price_eur=0.0)])
        self.assertEqual(result.candidates, ())
        self.assertIn("€0", result.rejected[0].reason)

    def test_bid_listing_without_a_fetched_bid_is_not_free(self):
        """Acceptatie-eis: geen stille terugval op €0, dus ook geen
        kandidaat met een oneindige upgrade per euro."""
        listing = upgrade_listing(
            price_type="FAST_BID", price_is_bid=True, price_eur=None, bid_count=None
        )
        result = find([listing])
        self.assertEqual(result.candidates, ())
        self.assertIn("geen bruikbare prijs", result.rejected[0].reason)

    def test_expected_order_on_upgrade_per_euro(self):
        """Acceptatie-eis: met fixture-advertenties komt de verwachte
        volgorde eruit. Dezelfde fiets, drie prijzen — de goedkoopste wint,
        want de kwaliteitswinst is gelijk."""
        listings = [
            upgrade_listing(item_id="duur", price_eur=1200.0),
            upgrade_listing(item_id="goedkoop", price_eur=400.0),
            upgrade_listing(item_id="middel", price_eur=800.0),
        ]
        result = find(listings)
        self.assertEqual(
            [c.listing.item_id for c in result.candidates], ["goedkoop", "middel", "duur"]
        )

    def test_a_bigger_jump_wins_at_the_same_price(self):
        modest = make_listing(
            item_id="bescheiden",
            title="Giant Defy 2016 carbon",
            description="Carbon frame, bouwjaar 2016, Shimano 105 11 speed, velremmen.",
            frame_height="56 cm",
            groupset_tier=4,
            price_eur=600.0,
        )
        big = upgrade_listing(item_id="groot", price_eur=600.0)
        result = find([modest, big])
        self.assertEqual(result.candidates[0].listing.item_id, "groot")

    def test_rim_brake_candidate_carries_the_wheelset_over(self):
        rim = make_listing(
            item_id="velrem",
            title="Giant TCR 2016 carbon racefiets",
            description=(
                "Carbon frame uit 2016, Shimano Ultegra Di2 11 speed, "
                "velremmen, aluminium wielen."
            ),
            frame_height="56 cm",
            groupset="Shimano Ultegra (elektronisch)",
            groupset_tier=5,
            price_eur=800.0,
        )
        result = find([rim])
        candidate = result.candidates[0]
        self.assertEqual(candidate.budget.route, up.ROUTE_RIM)
        self.assertTrue(any("verhuist mee" in r for r in candidate.reasons))
        # Zonder de meeverhuizende wielset zou de wieldimensie op aluminium
        # (40) blijven staan; met de CSC-set erbij is het merk-carbon (85).
        self.assertEqual(candidate.quality.dimensions["wheels"].score, 85)

    def test_disc_candidate_may_spend_the_wheelset_proceeds(self):
        budgets = up.budgets_from_valuation(1000, wheelset_value_eur=300, extra_budget_eur=250)
        listing = upgrade_listing(price_eur=1500.0)
        # Boven het velrembudget (€1250), binnen het schijfrembudget (€1550).
        self.assertEqual(find([listing], budgets=budgets).candidates[0].listing.item_id, "up1")
        rim_only = up.Budgets(rim=budgets.rim, disc=budgets.rim)
        self.assertEqual(find([listing], budgets=rim_only).candidates, ())

    def test_disc_candidates_are_not_filtered_out_up_front(self):
        # Het plan is hier uitgesproken over: juist een uitgesproken koopje bij
        # de schijfremmen is de reden dat dit gereedschap bestaat.
        result = find([upgrade_listing(price_eur=400.0)])
        self.assertEqual(result.candidates[0].budget.route, up.ROUTE_DISC)

    def test_margin_keeps_near_identical_bikes_out(self):
        # Zonder marge is elk afrondingsverschil al "beter", en dan staat de
        # lijst vol fietsen die in de praktijk hetzelfde zijn.
        listing = upgrade_listing()
        score = find([listing]).candidates[0].quality.total
        just_under = score - baseline_score() + 0.1
        self.assertEqual(find([listing], margin=just_under).candidates, ())
        self.assertEqual(len(find([listing], margin=0.0).candidates), 1)


class CandidateExplainabilityTest(unittest.TestCase):
    def test_every_candidate_carries_its_dimension_breakdown(self):
        # §7: "Uitlegbaarheid is een eis, geen extra."
        candidate = find([upgrade_listing()]).candidates[0]
        self.assertEqual(
            set(candidate.quality.dimensions),
            {"frame", "drivetrain", "brakes", "wheels", "extras"},
        )
        for dimension in candidate.quality.dimensions.values():
            self.assertTrue(dimension.reasons)

    def test_points_per_100_eur_matches_the_ranking_value(self):
        candidate = find([upgrade_listing()]).candidates[0]
        self.assertAlmostEqual(
            candidate.points_per_100_eur, candidate.upgrade_per_euro * 100
        )

    def test_formatting_does_not_crash_on_a_bid_candidate(self):
        listing = upgrade_listing(
            price_type="MIN_BID", price_is_bid=True, price_eur=400.0, bid_count=0,
            bid_minimum=250.0,
        )
        candidate = find([listing]).candidates[0]
        text = up.format_candidate(candidate, 1)
        self.assertIn("€250", text)
        self.assertIn("€400", text)


class OwnerIntakeTest(unittest.TestCase):
    def test_reads_the_target_size_and_budget(self):
        self.assertEqual(up.target_size_from(OWNER_SPECS), 56.0)
        self.assertEqual(up.extra_budget_from(OWNER_SPECS), 250.0)

    def test_missing_size_is_none_rather_than_a_guess(self):
        self.assertIsNone(up.target_size_from({}))
        self.assertIsNone(up.target_size_from({"size_cm": "onbekend"}))

    def test_missing_budget_falls_back_to_the_default(self):
        self.assertEqual(up.extra_budget_from({}), up.DEFAULT_EXTRA_BUDGET_EUR)

    def test_kept_computer_is_read_from_the_intake_table(self):
        kept = "| Fietscomputer | Wahoo Elemnt Roam (v1) — **gaat niet mee bij verkoop** |"
        self.assertEqual(up.owner_extras_kept(kept), frozenset({"computer"}))

    def test_a_computer_sold_along_is_not_kept(self):
        sold = "| Fietscomputer | Wahoo Elemnt Roam (v1), gaat mee bij verkoop |"
        self.assertEqual(up.owner_extras_kept(sold), frozenset())

    def test_real_intake_file_parses(self):
        with open(repo_file("mijn_fiets.md"), encoding="utf-8") as f:
            text = f.read()
        bike = val.parse_owner_bike(text)
        self.assertEqual(up.target_size_from(bike.specs), 56.0)
        self.assertEqual(up.extra_budget_from(bike.specs), 250.0)
        self.assertEqual(up.owner_extras_kept(text), frozenset({"computer"}))


class FetchCandidateListingsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "koopjes.db")
        self.addCleanup(self.dir.cleanup)

    def sync(self, listings, query="racefiets"):
        conn = db.connect(self.path)
        db.sync_listings(conn, query, listings, observed_at="2026-09-22T10:00:00+00:00")
        return conn

    def test_bid_listings_are_kept_unlike_in_the_comps(self):
        # Fase 3 houdt biedadvertenties juist buiten de comps; hier zijn ze
        # eersterangs (§3).
        conn = self.sync([
            make_listing(item_id="fixed", price_eur=500.0),
            make_listing(item_id="bid", price_type="FAST_BID", price_is_bid=True, price_eur=300.0),
        ])
        self.addCleanup(conn.close)
        found = {l.item_id: l for l in up.fetch_candidate_listings(conn)}
        self.assertEqual(set(found), {"fixed", "bid"})
        self.assertTrue(found["bid"].price_is_bid)

    def test_rehydrated_bid_listing_has_no_bid_count(self):
        # bid_count staat niet in het schema van §5, dus een uit de database
        # herbouwde biedadvertentie is er een waarvan het bod niet opgehaald
        # is — en die valt niet terug op €0.
        conn = self.sync([
            make_listing(item_id="bid", price_type="MIN_BID", price_is_bid=True, price_eur=300.0),
        ])
        self.addCleanup(conn.close)
        listing = up.fetch_candidate_listings(conn)[0]
        self.assertIsNone(listing.bid_count)
        self.assertEqual(up.effective_price(listing).amount, 300.0)

    def test_disappeared_listings_are_left_out(self):
        conn = self.sync([make_listing(item_id="gone", price_eur=500.0)])
        self.addCleanup(conn.close)
        conn.execute("UPDATE listing SET disappeared_at = ? WHERE item_id = 'gone'",
                     ("2026-09-20T10:00:00+00:00",))
        conn.commit()
        self.assertEqual(up.fetch_candidate_listings(conn), [])

    def test_groupset_is_detected_from_the_stored_text(self):
        conn = self.sync([
            make_listing(
                item_id="u", title="Racefiets met Shimano Ultegra", price_eur=500.0
            ),
        ])
        self.addCleanup(conn.close)
        self.assertEqual(up.fetch_candidate_listings(conn)[0].groupset_tier, 5)

    def test_query_filter(self):
        conn = self.sync([make_listing(item_id="a", price_eur=500.0)], query="racefiets")
        self.addCleanup(conn.close)
        self.assertEqual(len(up.fetch_candidate_listings(conn, query="racefiets")), 1)
        self.assertEqual(up.fetch_candidate_listings(conn, query="luidsprekers"), [])


class SharedConstantsTest(unittest.TestCase):
    def test_market_observation_threshold_is_the_one_the_deal_score_uses(self):
        self.assertEqual(up.MIN_MARKET_OBSERVATIONS, mp.SCORE_MARKET_MIN_OBSERVATIONS)

    def test_default_negotiation_factor_comes_from_the_valuation_engine(self):
        # Eén bron van waarheid: fase 3 stelt de factor vast, fase 5 gebruikt
        # hem. Deze test valt om zodra iemand er een tweede getal van maakt.
        listing = make_listing(price_eur=100.0)
        self.assertAlmostEqual(
            up.effective_price(listing).amount, 100.0 * val.NEGOTIATION_DEFAULT[1]
        )


if __name__ == "__main__":
    unittest.main()
