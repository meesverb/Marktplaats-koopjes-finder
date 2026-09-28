"""reference_sport_watches.csv: de hygiëne van het bestand en de herkenning
van echte Marktplaats-titels. Het bestand wordt gelezen met
computers.load_catalog() — zelfde vorm als reference_bike_computers.csv,
eigen kolommen."""
import unittest

from helpers import repo_file

import computers as pc

WATCHES = pc.load_catalog(repo_file("reference_sport_watches.csv"))


def first_match(title: str):
    """Het model dat de titel krijgt: de eerste rij waarvan het patroon past
    (de bestandsvolgorde is de matchvolgorde, net als bij de computers)."""
    title = pc.normalize_title(title)
    return next((m for m in WATCHES if m.pattern.search(title)), None)


class CatalogHygieneTest(unittest.TestCase):
    def test_file_loads(self):
        self.assertGreater(len(WATCHES), 20)

    def test_every_row_has_a_source(self):
        # CLAUDE.md: geen marktfeiten zonder bron.
        for m in WATCHES:
            with self.subTest(model=m.label):
                self.assertTrue(m.get("bron_url").startswith("https://"))

    def test_every_euro_price_has_its_own_source(self):
        # Een europrijs alleen waar een bron euro's noemt; een dollarprijs
        # staat apart in nieuwprijs_usd en wordt nooit omgerekend.
        for m in WATCHES:
            if m.get("nieuwprijs_eur"):
                with self.subTest(model=m.label):
                    self.assertTrue(m.get("prijs_bron").startswith("https://"))

    def test_fixed_words(self):
        for m in WATCHES:
            with self.subTest(model=m.label):
                self.assertIn(m.get("kaarten_op_horloge"), ("", "ja", "nee"))
                self.assertRegex(m.get("introductiejaar"), r"^20\d\d$")
                if m.get("nieuwprijs_usd"):
                    float(m.get("nieuwprijs_usd"))

    def test_no_model_is_shadowed_by_an_earlier_row(self):
        for m in WATCHES:
            with self.subTest(model=m.label):
                self.assertIs(first_match(f"{m.merk} {m.model}"), m)


class RealTitlesTest(unittest.TestCase):
    """Titels uit de Marktplaats-zoekresultaten van 28-09-2026 ('garmin
    fenix', 'garmin forerunner', 'garmin epix')."""

    def assert_model(self, title: str, expected):
        found = first_match(title)
        self.assertEqual(found.model if found else None, expected, title)

    def test_variants_land_on_their_own_row(self):
        cases = {
            "Garmin Fenix 6X Pro GPS Smartwatch -m": "Fenix 6 Pro",
            "Garmin Fenix 6S 42 mm zwart met een zwarte siliconen": "Fenix 6",
            "Garmin Fēnix 7S Pro Sapphire Solar – Soft Gold": "Fenix 7 Pro",
            "Garmin Fenix 7x solar 51mm": "Fenix 7",
            "Garmin fēnix 8 AMOLED 47mm Titanium-Nieuw in doos-Garantie": "Fenix 8",
            "Garmin Fenix 5X Plus Bluetooth 51 mm - Zwart": "Fenix 5 Plus",
            "Garmin Fenix 5S Sapphire 42mm": "Fenix 5",
            "Garmin Epix Pro (Gen 2) Sapphire 47mm in uitstekende staat": "Epix Pro",
            "Garmin - EPIX PRO 51 mm (GEN 2) - Unisex - 2024": "Epix Pro",
            "Garmin - EPIX 47 mm GEN 2 - Sapphire": "Epix (Gen 2)",
            "Garmin Forerunner 265 46 mm wit/zwart met een blauw/wit": "Forerunner 265",
            "Garmin Forerunner 570 Sporthorloge 42mm Zwart": "Forerunner 570",
            "Garmin Forerunner 45 zwart met een zwarte siliconen polsband": "Forerunner 45",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assert_model(title, expected)

    def test_models_not_in_the_file_stay_unrecognised(self):
        # Niet opgezocht, dus niet herkend — en zeker niet als een buurmodel.
        for title in (
            "Garmin Forerunner 235",
            "Garmin Fenix 3 HR - 51 mm",
            "Garmin Fenix E - als nieuw",
            "Garmin Fenix 9 - 43mm - Splinternieuw en ongebruikt",
            "Garmin Edge 830 scherm vervangen",
        ):
            with self.subTest(title=title):
                self.assert_model(title, None)

    def test_short_numbers_need_the_forerunner_name(self):
        # "Garmin 55" of "45 mm" zegt niets; alleen met Forerunner/FR ervoor.
        self.assert_model("Garmin horloge 45 mm", None)
        self.assert_model("Garmin FR55", "Forerunner 55")


if __name__ == "__main__":
    unittest.main()
