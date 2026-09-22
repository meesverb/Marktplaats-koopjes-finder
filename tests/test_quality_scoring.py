"""scoring.py — de kwaliteitsscore uit fase 4 (PLAN_FIETSWAARDE.md §7).

Niet te verwarren met tests/test_scoring.py, dat racefiets_jev.score_listing()
(de prijs-gebaseerde deal_score) test — twee verschillende scores, zie
CLAUDE.md."""
import unittest

from helpers import mp, repo_file  # noqa: F401  (zet de repo-root in sys.path)

import scoring as sc


def load_config():
    return sc.load_config(repo_file("scoring_config.json"))


class WheelBrandDetectionTest(unittest.TestCase):
    def test_recognizes_known_brands(self):
        self.assertTrue(sc.detect_wheel_branded("CSC 50mm carbon, Novatec naven"))
        self.assertTrue(sc.detect_wheel_branded("Zipp 303 Firecrest"))

    def test_unbranded_text_is_not_flagged(self):
        self.assertFalse(sc.detect_wheel_branded("naamloze carbon wielset van AliExpress"))


class BuildFromListingTest(unittest.TestCase):
    def test_reads_specs_and_groupset(self):
        build = sc.build_from_listing(
            specs={
                "frame_material": "carbon",
                "brake_type": "hydraulische schijfrem",
                "speeds": "12",
                "wheel_type": "carbon",
                "has_powermeter": "1",
            },
            groupset_label="Shimano Ultegra (elektronisch)",
            groupset_tier=5,
            text="Zipp wielen, Shimano Ultegra Di2",
        )
        self.assertEqual(build.frame_material, "carbon")
        self.assertTrue(build.electronic)
        self.assertEqual(build.speeds, 12)
        self.assertEqual(build.brake_type, "hydraulische schijfrem")
        self.assertTrue(build.wheel_branded)
        self.assertTrue(build.has_powermeter)
        self.assertFalse(build.has_computer)

    def test_unbranded_carbon_wheel_not_flagged_as_branded(self):
        build = sc.build_from_listing(
            specs={"wheel_type": "carbon"},
            text="mooie fiets met carbon wielen",
        )
        self.assertFalse(build.wheel_branded)

    def test_missing_specs_leave_fields_unset(self):
        build = sc.build_from_listing(specs={})
        self.assertIsNone(build.frame_material)
        self.assertIsNone(build.groupset_tier)
        self.assertIsNone(build.speeds)
        self.assertFalse(build.electronic)


class BuildFromOwnerSpecsTest(unittest.TestCase):
    OWNER_SPECS = {
        "frame_material": "carbon",
        "frame_tier": "composite (instapcarbon, endurance-geometrie)",
        "model_year": "2012",
        "size_cm": "56",
        "groupset_tier": "5   (Ultegra, bestaande GROUPSET_CATALOG-schaal)",
        "speeds": "10",
        "electronic": "nee",
        "brake_type": "velrem",
        "wheel_type": "carbon clincher 50mm, CSC (Novatec-naven), velrem, 18mm binnen",
        "extras": "geen (de Roam gaat niet mee)",
    }

    def test_parses_the_scoring_block_from_mijn_fiets_md(self):
        build = sc.build_from_owner_specs(self.OWNER_SPECS)
        self.assertEqual(build.frame_material, "carbon")
        self.assertEqual(build.frame_class, "endurance")
        self.assertFalse(build.frame_carbon_high_mod)
        self.assertEqual(build.model_year, 2012)
        self.assertEqual(build.groupset_tier, 5)
        self.assertEqual(build.speeds, 10)
        self.assertFalse(build.electronic)
        self.assertEqual(build.brake_type, "velrem")
        self.assertEqual(build.wheel_material, "carbon")
        self.assertTrue(build.wheel_branded)  # CSC/Novatec worden herkend
        self.assertFalse(build.has_powermeter)
        self.assertFalse(build.has_computer)

    def test_electronic_yes_is_recognized(self):
        specs = dict(self.OWNER_SPECS, electronic="ja")
        self.assertTrue(sc.build_from_owner_specs(specs).electronic)

    def test_extras_are_detected_when_present(self):
        specs = dict(
            self.OWNER_SPECS,
            extras="powermeter en een extra wielset, plus pedalen",
        )
        build = sc.build_from_owner_specs(specs)
        self.assertTrue(build.has_powermeter)
        self.assertTrue(build.has_extra_wheelset)
        self.assertTrue(build.has_pedals)
        self.assertFalse(build.has_computer)


class DimensionScoringTest(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_unknown_frame_material_scores_neutral_with_a_reason(self):
        result = sc.score_frame(sc.Build(), self.config, as_of_year=2026)
        self.assertEqual(result.score, self.config["frame"]["material_score_unknown"])
        self.assertIn("onbekend", result.reasons[0])

    def test_older_bikes_decay_but_not_below_the_cap(self):
        recent = sc.score_frame(
            sc.Build(frame_material="carbon", model_year=2024), self.config, as_of_year=2026
        )
        ancient = sc.score_frame(
            sc.Build(frame_material="carbon", model_year=1990), self.config, as_of_year=2026
        )
        self.assertGreater(recent.score, ancient.score)
        cfg = self.config["frame"]
        min_expected = cfg["material_score"]["carbon"] * cfg["tier_multiplier_unknown"] * (
            1 - cfg["age_decay_max"]
        )
        self.assertAlmostEqual(ancient.score, min_expected, places=6)

    def test_high_mod_carbon_scores_above_plain_carbon(self):
        plain = sc.score_frame(sc.Build(frame_material="carbon"), self.config, as_of_year=2026)
        high_mod = sc.score_frame(
            sc.Build(frame_material="carbon", frame_carbon_high_mod=True),
            self.config,
            as_of_year=2026,
        )
        self.assertGreater(high_mod.score, plain.score)

    def test_drivetrain_rewards_electronic_and_extra_speeds(self):
        mechanical_10 = sc.score_drivetrain(sc.Build(groupset_tier=5, speeds=10), self.config)
        electronic_12 = sc.score_drivetrain(
            sc.Build(groupset_tier=5, speeds=12, electronic=True), self.config
        )
        self.assertGreater(electronic_12.score, mechanical_10.score)

    def test_unrecognized_groupset_tier_falls_back_to_the_unknown_score(self):
        result = sc.score_drivetrain(sc.Build(groupset_tier=99), self.config)
        self.assertEqual(result.score, self.config["drivetrain"]["tier_score_unknown"])

    def test_brake_ranking_matches_plan_order(self):
        rim = sc.score_brakes(sc.Build(brake_type="velrem"), self.config).score
        mech_disc = sc.score_brakes(sc.Build(brake_type="mechanische schijfrem"), self.config).score
        hydro_disc = sc.score_brakes(sc.Build(brake_type="hydraulische schijfrem"), self.config).score
        self.assertLess(rim, mech_disc)
        self.assertLess(mech_disc, hydro_disc)

    def test_wheel_ranking_matches_plan_order(self):
        alu = sc.score_wheels(sc.Build(wheel_material="aluminium"), self.config).score
        unbranded_carbon = sc.score_wheels(
            sc.Build(wheel_material="carbon", wheel_branded=False), self.config
        ).score
        branded_carbon = sc.score_wheels(
            sc.Build(wheel_material="carbon", wheel_branded=True), self.config
        ).score
        self.assertLess(alu, unbranded_carbon)
        self.assertLess(unbranded_carbon, branded_carbon)

    def test_extras_score_zero_with_nothing_present(self):
        result = sc.score_extras(sc.Build(), self.config)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.reasons, ("geen extra's",))

    def test_powermeter_counts_in_full_computer_is_discounted_when_already_owned(self):
        full = sc.score_extras(sc.Build(has_computer=True), self.config)
        discounted = sc.score_extras(
            sc.Build(has_computer=True), self.config, owner_already_has=frozenset({"computer"})
        )
        self.assertGreater(full.score, discounted.score)
        self.assertGreater(discounted.score, 0.0)

    def test_extras_score_never_exceeds_the_configured_max(self):
        build = sc.Build(
            has_powermeter=True, has_computer=True, has_extra_wheelset=True, has_pedals=True
        )
        # Zet de posten kunstmatig hoog zodat de som zonder cap boven 100 zou
        # uitkomen, en controleer dat de cap ('max') daadwerkelijk knijpt.
        config = load_config()
        config["extras"] = dict(config["extras"], powermeter=80, computer=80, max=100)
        result = sc.score_extras(build, config)
        self.assertEqual(result.score, 100.0)


class ScoreBuildTest(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_the_owner_bike_gets_a_baseline(self):
        build = sc.build_from_owner_specs(BuildFromOwnerSpecsTest.OWNER_SPECS)
        quality = sc.score_build(build, self.config, as_of_year=2026)
        self.assertTrue(0 < quality.total < 100)
        self.assertEqual(set(quality.dimensions), {"frame", "drivetrain", "brakes", "wheels", "extras"})

    def test_a_modern_electronic_disc_bike_scores_higher_than_the_baseline(self):
        baseline = sc.build_from_owner_specs(BuildFromOwnerSpecsTest.OWNER_SPECS)
        modern = sc.Build(
            frame_material="carbon",
            frame_class="race",
            model_year=2024,
            groupset_tier=5,
            electronic=True,
            speeds=12,
            brake_type="hydraulische schijfrem",
            wheel_material="carbon",
            wheel_branded=True,
        )
        baseline_score = sc.score_build(baseline, self.config, as_of_year=2026).total
        modern_score = sc.score_build(modern, self.config, as_of_year=2026).total
        self.assertGreater(modern_score, baseline_score)

    def test_an_aluminium_sora_bike_scores_lower_than_the_baseline(self):
        baseline = sc.build_from_owner_specs(BuildFromOwnerSpecsTest.OWNER_SPECS)
        alu_sora = sc.Build(
            frame_material="aluminium",
            model_year=2015,
            groupset_tier=2,
            speeds=9,
            brake_type="velrem",
            wheel_material="aluminium",
        )
        baseline_score = sc.score_build(baseline, self.config, as_of_year=2026).total
        alu_score = sc.score_build(alu_sora, self.config, as_of_year=2026).total
        self.assertLess(alu_score, baseline_score)

    def test_reweighing_a_dimension_changes_the_total_predictably(self):
        build = sc.Build(
            frame_material="carbon", model_year=2012, groupset_tier=5,
            brake_type="velrem", wheel_material="carbon", wheel_branded=True,
        )
        base_total = sc.score_build(build, self.config, as_of_year=2026).total

        heavier_wheels = dict(self.config, weights=dict(self.config["weights"], wheels=0.60,
                                                          frame=0.10, drivetrain=0.10,
                                                          brakes=0.10, extras=0.10))
        reweighed_total = sc.score_build(build, heavier_wheels, as_of_year=2026).total
        # Wielen scoren voor deze build het hoogst van de vijf dimensies, dus
        # meer gewicht daarop moet het totaal predictable omhoog trekken.
        self.assertGreater(reweighed_total, base_total)

    def test_breakdown_per_dimension_is_queryable(self):
        build = sc.build_from_owner_specs(BuildFromOwnerSpecsTest.OWNER_SPECS)
        quality = sc.score_build(build, self.config, as_of_year=2026)
        for name, dimension in quality.dimensions.items():
            self.assertIsInstance(dimension.score, float)
            self.assertTrue(dimension.reasons, msg=f"{name} heeft geen reden-tekst")


class FitsFrameSizeTest(unittest.TestCase):
    def test_within_tolerance_fits(self):
        self.assertTrue(sc.fits_frame_size((54.0, 57.0), target_cm=56.0))

    def test_outside_tolerance_does_not_fit(self):
        self.assertFalse(sc.fits_frame_size((48.0, 50.0), target_cm=56.0))

    def test_unknown_bounds_do_not_fit(self):
        self.assertFalse(sc.fits_frame_size(None, target_cm=56.0))


class ConfigLoadingTest(unittest.TestCase):
    def test_the_shipped_config_loads_and_has_all_weighted_dimensions(self):
        config = load_config()
        self.assertEqual(
            set(config["weights"]),
            {"frame", "drivetrain", "brakes", "wheels", "extras"},
        )


if __name__ == "__main__":
    unittest.main()
