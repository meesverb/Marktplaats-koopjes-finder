"""extract_specs() — PLAN_FIETSWAARDE.md fase 2.

Runs a fixture set of ~50 representative racefiets ad texts (title +
description, as apply_reference_data() and extract_specs() see them)
against known-good extraction. Precision over coverage: several fixtures
deliberately check that an ambiguous or out-of-range mention is *not*
extracted rather than guessed — a wrong spec would silently pollute the
comps fase 3 builds on top of `spec`.
"""
import json
import unittest
from pathlib import Path

from helpers import mp

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "spec_extraction.json"


def load_fixtures() -> list[dict]:
    with open(FIXTURES_PATH, encoding="utf-8") as f:
        return json.load(f)


class ExtractSpecsFixtureTest(unittest.TestCase):
    def test_fixture_set_matches_expected_extraction(self):
        fixtures = load_fixtures()
        self.assertGreaterEqual(
            len(fixtures), 50, "fixture set should hold ~50 ad texts per fase 2's acceptance criteria"
        )
        failures = []
        for i, fixture in enumerate(fixtures):
            got = mp.extract_specs(fixture["text"])
            if got != fixture["expected"]:
                failures.append(
                    f"[{i}] {fixture.get('note', '')}\n"
                    f"    text:     {fixture['text']}\n"
                    f"    expected: {fixture['expected']}\n"
                    f"    got:      {got}"
                )
        self.assertFalse(failures, "\n" + "\n".join(failures))


class ExtractSpecsUnitTest(unittest.TestCase):
    """A few targeted cases the fixture set doesn't spell out on its own."""

    def test_no_specs_returns_empty_dict(self):
        self.assertEqual(mp.extract_specs("Racefiets te koop, nette staat."), {})

    def test_frame_material_ignores_a_wheel_only_carbon_mention(self):
        # The known pitfall this fase's acceptance criteria calls out:
        # "carbon" in the same ad as an aluminium frame, but only because
        # the wheels are carbon. See mijn_fiets.md — Giant Defy Composite
        # 2012, carbon frame, *and* a separately-bought carbon wheelset is
        # exactly this shape of ad.
        specs = mp.extract_specs(
            "Aluminium frame, later voorzien van een carbon wielset."
        )
        self.assertEqual(specs.get("frame_material"), "aluminium")
        self.assertEqual(specs.get("wheel_type"), "carbon")

    def test_frame_material_matches_a_structured_frame_clause(self):
        specs = mp.extract_specs("Frame: carbon. Wielen: aluminium.")
        self.assertEqual(specs.get("frame_material"), "carbon")

    def test_speeds_outside_racefiets_range_is_not_extracted(self):
        self.assertNotIn("speeds", mp.extract_specs("21 speed kinderfiets"))
        self.assertNotIn("speeds", mp.extract_specs("7 speed oldtimer"))

    def test_model_year_requires_an_explicit_label(self):
        self.assertNotIn("model_year", mp.extract_specs("Sinds 2015 in mijn bezit"))
        self.assertEqual(
            mp.extract_specs("Bouwjaar 2015").get("model_year"), "2015"
        )


class ExtractListingSpecsTest(unittest.TestCase):
    def test_keyed_by_item_id(self):
        from helpers import make_listing

        listings = [
            make_listing(item_id="a", title="Carbon frame", description="velgrem"),
            make_listing(item_id="b", title="Niks bijzonders", description=""),
        ]
        result = mp.extract_listing_specs(listings)
        self.assertEqual(result["a"]["frame_material"], "carbon")
        self.assertEqual(result["a"]["brake_type"], "velrem")
        self.assertEqual(result["b"], {})


if __name__ == "__main__":
    unittest.main()
