"""racebikes.py en /racefietsen in dashboard.py --serve: alle racefietsen,
wegzetten met de fietsredenen, een bod vastleggen, afstand."""
import http.client
import json
import re
import shutil
import tempfile
import threading
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from helpers import close_databases_before_cleanup, make_listing, repo_file

import dashboard
import db
import distance as dm
import flips as fl
import marks as mr
import racebikes as rb

BIKE_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsen-racefietsen/{}-x"
COMPUTER_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsaccessoires-fietscomputers/{}-x"
PART_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsonderdelen/{}-x"


def bike(item_id, price, title="Cube Attain racefiets", **kw):
    kw.setdefault("url", BIKE_URL.format(item_id))
    kw.setdefault("description", "Carbon frame, Shimano 105, velgremmen.")
    kw.setdefault("frame_height", "56 cm")
    kw.setdefault("image_urls", f"https://images.example/{item_id}.jpg")
    return make_listing(item_id=item_id, title=title, price_eur=price, **kw)


class Case(unittest.TestCase):
    # De server opent zijn verbindingen in een eigen thread; die kan de
    # opruimhulp niet sluiten (en de server sluit ze zelf).
    track_connections = True

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        if self.track_connections:
            close_databases_before_cleanup(self)
        self.db = str(self.dir / "koopjes.db")
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        market = [bike(f"a{i}", p, city="Zwolle", latitude=52.51, longitude=6.09)
                  for i, p in enumerate((500.0, 550.0, 600.0, 650.0))]
        cheap = bike("c", 300.0, title="Cube Attain racefiets <b>koopje</b>", city="Utrecht", latitude=52.09,
                     longitude=5.12, promotion="DAGTOPPER")
        old = bike("old", 400.0)
        computer = make_listing(item_id="g", title="Garmin Edge 530", price_eur=90.0, url=COMPUTER_URL.format("g"))
        conn = db.connect(self.db)
        db.sync_listings(conn, "racefiets", [old], (self.now - timedelta(days=20)).isoformat())
        db.sync_listings(conn, "racefiets", market + [cheap, computer], self.now.isoformat())
        conn.close()


class LoadTest(Case):
    def test_only_active_road_bikes_with_flip_and_value(self):
        base = rb.build_base(self.db, self.dir / "geen_fiets.md")
        ids = {r.listing.item_id for r in base.rows}
        self.assertEqual(ids, {"a0", "a1", "a2", "a3", "c"})  # geen computer, niet de oude
        c = base.row("c")
        self.assertEqual(c.listing.groupset_tier is not None, True)
        self.assertIn("56 cm", c.specs)
        self.assertIsNotNone(c.flip_margin)
        self.assertGreater(c.flip_margin, 0)
        self.assertGreater(c.value_ratio, 1)
        self.assertIn("geen_fiets.md", base.owner_problem)  # zonder eigen fiets geen upgradeoordeel
        self.assertFalse(c.upgrade_ok)

    def test_with_the_real_owner_bike_there_is_an_upgrade_verdict(self):
        base = rb.build_base(self.db, repo_file("mijn_fiets.md"))
        # mijn_fiets.md heeft verkoopprijs_handmatig, dus een budget, ook zonder comps.
        self.assertEqual(base.owner_problem, "")
        self.assertTrue(all(r.upgrade_why for r in base.rows))

    def test_bike_json_and_the_page(self):
        base = rb.build_base(self.db, self.dir / "geen_fiets.md")
        conn = db.connect(self.db)
        db.set_mark(conn, "a0", mr.DISMISSED, reason="geen racefiets", price_eur=500.0)
        db.set_note(conn, "c", "gevraagd of 280 kan")
        dm.save_home(conn, dm.Home("3511AB", 52.0952, 5.1161))
        conn.close()
        fresh = rb.load_fresh(self.db)
        c = rb.bike_json(base.row("c"), fresh)
        self.assertEqual((c["no"], c["promo"], c["m"]), ("gevraagd of 280 kan", "DAGTOPPER", ""))
        self.assertLess(c["km"], 5)
        self.assertEqual(rb.bike_json(base.row("a0"), fresh)["m"], "weg")
        html = rb.render(base, fresh, "tok")
        self.assertIn("Te beoordelen", html)
        self.assertIn("Afstand hemelsbreed vanaf <strong>3511AB</strong>", html)
        # De titel met <b> zit als JSON in een <script>: </ is ontsnapt, dus
        # geen tekst uit een advertentie kan het script afsluiten.
        self.assertIn("<b>koopje<\\/b>", html)
        self.assertNotIn("<b>koopje</b>", html)


class SparesTest(Case):
    """Reserves: losse onderdelen die de rondes al tegenkomen (spares.py),
    weergave Onderdelen op /racefietsen."""

    def setUp(self):
        super().setUp()
        conn = db.connect(self.db)
        parts = [make_listing(item_id="p1", title="Shimano 105 cassette 11-28", price_eur=18.0, url=PART_URL.format("p1")),
                 make_listing(item_id="p2", title="Ultegra cassette 12-25", price_eur=25.0, url=PART_URL.format("p2")),
                 make_listing(item_id="p3", title="Look Keo pedalen", price_eur=30.0, url=PART_URL.format("p3")),
                 make_listing(item_id="p4", title="Gezocht: cassette 10 speed", price_eur=1.0, url=PART_URL.format("p4")),
                 make_listing(item_id="p5", title="Selle Italia zadel", price_eur=15.0, url=BIKE_URL.format("p5")),
                 make_listing(item_id="p6", title="KMC ketting", price_eur=9.0, url=COMPUTER_URL.format("p6"))]
        db.sync_listings(conn, "x", parts + [bike("rb", 400.0, title="Giant Defy racefiets met nieuwe cassette")],
                         self.now.isoformat())
        db.sync_listings(conn, "x", [make_listing(item_id="old", title="Cassette 11-32", price_eur=5.0,
                                                  url=PART_URL.format("old"))],
                         (self.now - timedelta(days=20)).isoformat())
        conn.close()

    def test_what_counts_as_a_spare(self):
        import spares as sp
        found = {p.listing.item_id: p.kinds for p in sp.load(self.db)}
        # Geen gezocht, geen hele fiets, geen fietscomputer-categorie, niet te oud;
        # een zadel tussen de racefietsen wel.
        self.assertEqual(found, {"p1": ["cassette"], "p2": ["cassette"], "p3": ["pedalen"], "p5": ["zadel"]})
        self.assertEqual([p.listing.item_id for p in sp.cheapest(sp.load(self.db), per_kind=1)], ["p5", "p1", "p3"])
        self.assertEqual(sp.kinds_of("Zadelpen carbon", "fietsonderdelen"), ["zadelpen"])
        self.assertEqual(sp.kinds_of("Kettingslot Abus", "fietsonderdelen"), [])

    def test_the_owner_chooses_the_kinds(self):
        import spares as sp
        self.assertEqual(sp.load_choice(self.db), list(sp.DEFAULT_ON))
        self.assertEqual(sp.save_choice(self.db, ["pedalen", "onzin", "cassette"]), ["cassette", "pedalen"])
        self.assertEqual(sp.load_choice(self.db), ["cassette", "pedalen"])

    def test_on_the_page(self):
        base = rb.build_base(self.db, self.dir / "geen_fiets.md")
        html = rb.render(base, rb.load_fresh(self.db), "tok")
        data = json.loads(re.search(r"id='spares'>(.*?)</script>", html).group(1).replace("<\\/", "</"))
        self.assertEqual({p["id"] for p in data["parts"]}, {"p1", "p2", "p3", "p5"})
        self.assertIn(["cassette", "Cassettes", 2], data["kinds"])
        self.assertEqual(data["on"], ["cassette", "ketting", "zadel", "pedalen"])
        self.assertIn("data-view='spares'", html)


class OwnFlipsViewTest(Case):
    """Mijn flips op /racefietsen: de fietsen van /flips, niet de
    fietscomputers of spullen (elke pagina dezelfde weergaven, 02-10-2026)."""

    def test_only_bikes_with_cost_and_profit(self):
        self.assertEqual(rb.own_flips_html(self.db)[0], 0)
        conn = db.connect(self.db)
        running = fl.create_flip(conn, title="Cube Peloton Pro", market="fietsen", bought_at="2026-09-20",
                                 buy_price_eur=250.0, target_low_eur=400.0, target_high_eur=450.0)
        fl.add_task(conn, running, kind="onderdeel", title="ketting", est_eur=20.0)
        done = fl.create_flip(conn, title="Trek 1.2", market="fietsen", bought_at="2026-08-01", buy_price_eur=200.0)
        fl.sell(conn, done, sold_at="2026-08-20", price_eur=320.0)
        fl.create_flip(conn, title="Garmin Edge 530", market="fietscomputers", bought_at="2026-09-01",
                       buy_price_eur=90.0)
        fl.create_flip(conn, title="Fietsdrager", market="spullen", bought_at="2026-09-01", buy_price_eur=30.0)
        conn.close()

        count, html = rb.own_flips_html(self.db)
        self.assertEqual(count, 2)
        self.assertIn("Cube Peloton Pro", html)
        self.assertNotIn("Garmin", html)
        self.assertNotIn("Fietsdrager", html)
        # Lopend: winst op het midden van de doelprijs, min aankoop en de geplande ketting (425 − 250 − 20).
        self.assertIn("+€155,00 <span class=muted>verwacht", html)
        self.assertIn("+€20,00 gepland", html)
        self.assertIn("verdiend +€120,00", html)
        self.assertIn(f"href='/flips#flip-{running}'", html)
        self.assertLess(html.index("Cube Peloton Pro"), html.index("Trek 1.2"))  # lopend eerst
        self.assertNotIn("verkocht <span class=muted>0 d", html)

        base = rb.build_base(self.db, self.dir / "geen_fiets.md")
        page = rb.render(base, rb.load_fresh(self.db), "tok")
        self.assertIn("data-view='flips' data-label='Mijn flips (2)'", page)
        # Op de telefoon staan de filters achter één knop.
        self.assertIn("id='filtersbtn'", page)
        self.assertIn(".bar:not(.open) .filters", page)
        self.assertIn("<section id='flipview' hidden>", page)


class FindOneTest(Case):
    def test_one_bike_as_the_whole_list_gives_it(self):
        listings, _, _ = rb.load_listings(self.db)
        for listing in listings:
            one = rb.find_listing(self.db, listing.item_id)
            self.assertEqual((one.title, one.price_eur, one.city, one.latitude, one.promotion),
                             (listing.title, listing.price_eur, listing.city, listing.latitude, listing.promotion))
        self.assertIsNone(rb.find_listing(self.db, "old"))  # te lang niet gezien
        self.assertIsNone(rb.find_listing(self.db, "g"))  # geen racefiets
        self.assertIsNone(rb.find_listing(self.db, "bestaat-niet"))


class OpenEndedFrameTest(Case):
    def test_sixty_or_more_does_not_break_the_page_json(self):
        conn = db.connect(self.db)
        db.sync_listings(conn, "racefiets", [bike("big", 450.0, frame_height="60 cm of meer")], self.now.isoformat())
        conn.close()
        base = rb.build_base(self.db, self.dir / "geen_fiets.md")
        html = rb.render(base, rb.load_fresh(self.db), "tok")
        data = re.search(r"id='bikes'>(.*?)</script>", html).group(1)
        self.assertNotIn("Infinity", data)
        big = next(b for b in json.loads(data.replace("<\\/", "</")) if b["id"] == "big")
        self.assertEqual(big["fr"], [60.0, 999])


class PageJsonTest(unittest.TestCase):
    def test_nan_and_infinity_become_null_wherever_they_are(self):
        data = {"a": [1.5, float("nan"), {"b": float("inf")}], "t": "</script>", "c": (2, -float("inf"))}
        text = rb.page_json(data)
        self.assertNotIn("</", text)
        self.assertEqual(json.loads(text.replace("<\\/", "</")),
                         {"a": [1.5, None, {"b": None}], "t": "</script>", "c": [2, None]})
        self.assertEqual(rb.page_json({"x": [1, "é"]}), '{"x":[1,"é"]}')


class ModelComparisonTest(Case):
    """Vergelijken op merk, model en bouwjaar (bike_identity.py), niet op
    onderdelen alleen: een Ultegra-fiets van 2012 is geen maat voor een van 2023."""

    def test_identity_from_title_and_text(self):
        import bike_identity as bi
        me = bi.identify(bike("x", 900.0, title="Trek Emonda SL6 2019 maat 56",
                              description="Ultegra Di2, schijfremmen, carbon"))
        self.assertEqual((me.model, me.year, me.disc, me.electronic, me.material),
                         ("trek emonda", 2019, True, True, "carbon"))
        # Het modelwoord hoort bij één merk: dan is dat het merk.
        self.assertEqual(bi.identify(bike("y", 500.0, title="Émonda ALR 5", description="")).model, "trek emonda")
        self.assertIsNone(bi.identify(bike("z", 500.0, title="Mooie racefiets", description="")).model)

    def test_only_the_same_model_from_the_same_years_counts(self):
        conn = db.connect(self.db)
        # Vijf: minder is geen trede (bike_identity.MIN_COMPS), dan zou de
        # opbouw met de Madones het worden.
        old = [bike(f"o{i}", p, title=f"Giant Defy 2012 {i}") for i, p in enumerate((300.0, 310.0, 320.0, 330.0, 340.0))]
        new = [bike(f"n{i}", p, title=f"Giant Defy Advanced 2023 {i}") for i, p in enumerate((1500.0, 1600.0, 1700.0))]
        other = [bike(f"t{i}", 2500.0, title=f"Trek Madone 2012 {i}") for i in range(5)]
        me = bike("me", 350.0, title="Giant Defy 2013")
        db.sync_listings(conn, "racefiets", old + new + other + [me], self.now.isoformat())
        conn.close()
        row = rb.build_base(self.db, self.dir / "geen_fiets.md").row("me")
        self.assertEqual(row.level, "model+jaar")
        self.assertEqual({c[1] for c in row.comps}, {300.0, 310.0, 320.0, 330.0, 340.0})
        self.assertAlmostEqual(row.resale, 320.0 * 0.875)
        self.assertIn("Giant Defy", row.flip_basis.replace("giant defy", "Giant Defy"))

    def test_linked_to_the_reference_model_and_compared_with_what_hangs_on_it(self):
        conn = db.connect(self.db)
        same = [bike(f"c{i}", p, title=f"Giant Defy Composite 1 racefiets {i}")
                for i, p in enumerate((600.0, 650.0, 700.0, 750.0, 800.0))]
        higher = [bike(f"a{i}", 1400.0, title=f"Giant Defy Advanced 2 {i}") for i in range(4)]
        me = bike("me", 450.0, title="Giant Defy Composite 1 maat 56")
        db.sync_listings(conn, "racefiets", same + higher + [me], self.now.isoformat())
        conn.close()
        base = rb.build_base(self.db, self.dir / "geen_fiets.md")
        row = base.row("me")
        self.assertEqual(row.identity.reference, "Giant Defy Composite 1")
        self.assertEqual(row.level, "model")
        self.assertEqual({c[1] for c in row.comps}, {600.0, 650.0, 700.0, 750.0, 800.0})
        self.assertEqual(row.linked, 6)  # de vijf andere en hijzelf
        data = rb.bike_json(row, rb.load_fresh(self.db))
        # €450 tegen de schatting 700 × 0,875 = 612,50: 27% goedkoper.
        self.assertEqual((data["grp"], data["ref"], data["src"], data["pc"]),
                         ("Giant Defy Composite 1", True, "referentie", -27))
        self.assertIn("Modellen", rb.render(base, rb.load_fresh(self.db), "tok"))

    def test_without_a_model_there_is_no_estimate_rather_than_a_wrong_one(self):
        conn = db.connect(self.db)
        db.sync_listings(conn, "racefiets", [bike("anon", 200.0, title="Racefiets maat 56")], self.now.isoformat())
        conn.close()
        row = rb.build_base(self.db, self.dir / "geen_fiets.md").row("anon")
        self.assertIsNone(row.resale)
        self.assertIn("model niet herkend", row.flip_basis)


class FoldTest(unittest.TestCase):
    def test_accents_case_and_nothing(self):
        import bike_identity as bi
        self.assertEqual([bi.fold(t) for t in ("Émonda", "TREK Domane", "Cervélo R3", "", None)],
                         ["emonda", "trek domane", "cervelo r3", "", ""])


class ReferenceIndexTest(unittest.TestCase):
    """bike_identity.reference_model() slaat patronen over waarvan geen
    beginwoord in de tekst staat; de uitkomst moet die van alle patronen op
    volgorde blijven."""

    def test_the_words_a_pattern_needs(self):
        import bike_identity as bi
        self.assertEqual(bi.needles(r"Defy.{0,20}Advanced.{0,3}SL"), {"defy"})
        self.assertEqual(bi.needles(r"Giant.{0,10}Defy\s*[0-5]\b|Defy.{0,10}Aluxx"), {"giant", "defy"})
        self.assertEqual(bi.needles(r"\bTCR\s*(Composite|Aluxx|SL|[0-3])\b"), {"tcr"})
        self.assertEqual(bi.needles(r"Aluxx?"), {"alux"})  # de laatste x is optioneel
        self.assertEqual(bi.needles(r"Emond{0,1}a"), {"emon"})
        self.assertIsNone(bi.needles(r"(?:Trek|Giant) Domane"))
        self.assertIsNone(bi.needles(r"[Tt]rek"))
        self.assertIsNone(bi.needles(r"Trek|(Giant)"))
        self.assertEqual(bi._alternatives(r"a(b|c)|d[|]|e\|f"), ["a(b|c)", "d[|]", "e\\|f"])

    def test_same_answer_as_every_pattern_in_order(self):
        import bike_identity as bi
        rows = bi.reference_rows()
        texts = [r["label"] for r in rows] + [
            "Giant Defy Advanced 2 2019 maat M", "GIANT DEFY COMPOSITE 1", "Trek Domane SL6 disc",
            "Canyon Endurace CF SL Disc 8.0", "racefiets Gazelle", "Specialized S-Works Roubaix",
            "Cube Attain GTC", "TCR advanced pro", "giant tcr 2", "Émonda ALR 5", "Cervélo R3", ""]
        for text in texts:
            listing = make_listing(title=text, description="")
            slow = next((r["label"] for r in rows if r["regex"].search(f"{text} ")), None)
            self.assertEqual(bi.reference_model(listing), slow, text)


class VariantTest(unittest.TestCase):
    """Model + uitvoering uit de titel (bike_identity.variant_of()), de
    voorbeelden uit opdrachten/fietsmodellen.md."""

    def ident(self, title, description="", **kw):
        import bike_identity as bi
        return bi.identify(bike("x", 500.0, title=title, description=description), **kw)

    def test_the_five_examples(self):
        for title, family, variant, name in (
                ("Giant Defy Advanced 2 maat M", "defy", "advanced 2", "Giant Defy Advanced 2"),
                ("Trek Domane SL6 Gen 4", "domane", "sl6", "Trek Domane SL6"),
                ("Trek Domane AL 2 2024", "domane", "al 2", "Trek Domane AL 2"),
                ("Canyon Aeroad CF SLX 8", "aeroad", "cf slx 8", "Canyon Aeroad CF SLX 8"),
                ("Cube Attain racefiets", "attain", None, None)):
            me = self.ident(title)
            self.assertEqual((me.family, me.variant), (family, variant), title)
            if name:
                self.assertEqual(me.name, name, title)
        self.assertEqual(self.ident("Trek Domane AL 2 2024").year, 2024)

    def test_spaces_do_not_make_another_model(self):
        self.assertEqual(self.ident("Trek Domane SL 6").exact, self.ident("trek domane sl6 maat 56").exact)
        self.assertNotEqual(self.ident("Trek Domane SL6").exact, self.ident("Trek Domane AL 2").exact)
        self.assertEqual(self.ident("Trek Domane SL6").coarse, self.ident("Trek Domane AL 2").coarse)

    def test_a_reference_model_only_wins_when_it_says_more(self):
        # "Trek Domane" in reference_bikes.csv is een vangnet voor de hele
        # lijn; de titel zegt hier meer.
        self.assertEqual(self.ident("Trek Domane SL6").reference, "Trek Domane")
        self.assertEqual(self.ident("Trek Domane SL6").source, "automatisch")
        composite = self.ident("Giant Defy Composite 1 maat 56")
        self.assertEqual((composite.name, composite.source), ("Giant Defy Composite 1", "referentie"))

    def test_the_owners_link_goes_first(self):
        link = {"model_id": 7, "model": "Koga Kinsei Pro", "brand": "koga", "family": "kinsei", "variant": "pro",
                "year": 2016, "confirmed": 1}
        me = self.ident("Giant Defy Composite 1 bouwjaar 2012", "Bouwjaar 2012.", link=link)
        self.assertEqual((me.name, me.source, me.own_id, me.year, me.own_year, me.confirmed),
                         ("Koga Kinsei Pro", "eigen", 7, 2016, True, True))
        self.assertEqual(me.coarse, "kogakinsei")

    def test_a_typed_name(self):
        import bike_identity as bi
        self.assertEqual(bi.split_name("Koga  Kinsei Pro"), ("Koga Kinsei Pro", "koga", "kinsei", "pro"))
        self.assertEqual(bi.split_name("De Rosa Merak"), ("De Rosa Merak", "de rosa", "merak", None))
        # Een modelwoord van één merk krijgt dat merk erbij.
        self.assertEqual(bi.split_name("Emonda SL6")[0], "Trek Emonda SL6")


class LadderTest(unittest.TestCase):
    """De vergelijkingstrap (bike_identity.comparables()): minstens 5 per
    trede, anders een stap grover."""

    def pool(self, *groups):
        import bike_identity as bi
        items = []
        for title, n in groups:
            for i in range(n):
                listing = bike(f"{title}-{i}", 500.0 + i, title=title)
                items.append((bi.identify(listing), listing.price_eur, (listing.item_id, title, "", "", False)))
        return bi.Pool(items)

    def me(self, title):
        import bike_identity as bi
        return bi.identify(bike("me", 400.0, title=title))

    def test_same_model_within_two_years_only(self):
        pool = self.pool(("Trek Domane SL6 2018", 5), ("Trek Domane SL6 2012", 5))
        level, found, few = pool.comparables(self.me("Trek Domane SL6 2019"), "me")
        self.assertEqual((level, few), ("model+jaar", False))
        self.assertEqual({c[0].year for c in found}, {2018})
        self.assertEqual(len(found), 5)

    def test_too_few_of_the_exact_model_goes_to_the_family(self):
        import bike_identity as bi
        pool = self.pool(("Trek Domane SL6 2019", 3), ("Trek Domane AL 2 2020", 6))
        level, found, few = pool.comparables(self.me("Trek Domane SL6 2019"), "me")
        self.assertEqual((level, len(found), few), ("familie+jaar", 9, False))
        self.assertEqual(bi.LEVEL_LABELS[level], "modelfamilie, ±2 jaar")

    def test_three_is_few_but_better_than_nothing(self):
        pool = self.pool(("Trek Domane SL6 2019", 3))
        self.assertEqual(pool.comparables(self.me("Trek Domane SL6 2019"), "me")[::2], ("model+jaar", True))

    def test_never_the_median_of_all_road_bikes(self):
        pool = self.pool(("Trek Domane SL6 2019", 8))
        self.assertEqual(pool.comparables(self.me("Mooie racefiets maat 56"), "me"), ("", [], False))
        # En nooit de fiets zelf.
        level, found, _ = pool.comparables(self.me("Trek Domane SL6 2019"), "Trek Domane SL6 2019-0")
        self.assertEqual(len(found), 7)

    def test_replace_moves_one_bike(self):
        import bike_identity as bi
        pool = self.pool(("Trek Domane SL6 2019", 3))
        moved = bi.identify(bike("Trek Domane SL6 2019-0", 500.0, title="Koga Kinsei Pro"))
        old = pool.replace("Trek Domane SL6 2019-0", moved)
        self.assertEqual(old.exact, "trekdomanesl6")
        self.assertEqual(len(pool.by_exact["trekdomanesl6"]), 2)
        self.assertEqual(len(pool.by_exact["kogakinseipro"]), 1)
        self.assertIs(pool.identity_of["Trek Domane SL6 2019-0"], moved)
        self.assertIsNone(pool.replace("onbekend", moved))


class FastSoldTest(Case):
    """Vergelijken met wat snel wegging (≤ 7 dagen, of gereserveerd en dan weg)."""

    def add(self, fast_ids, for_sale=5):
        conn = db.connect(self.db)
        early = (self.now - timedelta(days=10)).isoformat()
        sold = [bike(f"f{i}", p, title="Trek Domane SL6 racefiets") for i, p in enumerate((600.0, 620.0, 640.0))]
        db.sync_listings(conn, "racefiets", sold, early)
        listed = [bike(f"s{i}", 800.0 + 25 * i, title="Trek Domane SL6 racefiets") for i in range(for_sale)]
        db.sync_listings(conn, "racefiets", listed + [bike("me", 500.0, title="Trek Domane SL6 racefiets")],
                         self.now.isoformat())
        for item_id in fast_ids:
            conn.execute("UPDATE listing SET disappeared_at = ?, days_online = 3 WHERE item_id = ?",
                         ((self.now - timedelta(days=7)).isoformat(), item_id))
        conn.commit()
        conn.close()
        return rb.build_base(self.db, self.dir / "geen_fiets.md").row("me")

    def test_three_sold_fast_set_the_price(self):
        row = self.add(["f0", "f1", "f2"])
        self.assertEqual(row.level, "model")
        self.assertEqual(row.resale, 620.0)  # hun mediaan, zonder afdingfactor
        self.assertEqual(row.fast, (3, 620.0))
        self.assertEqual(row.for_sale, (5, 850.0))
        self.assertIn("snel verkochte", row.flip_basis)
        data = rb.bike_json(row, rb.load_fresh(self.db))
        self.assertEqual((data["sv"], data["tk"], data["pc"]), ([3, 620], [5, 850], -19))
        self.assertEqual(sum(1 for c in data["cmp"] if c[5]), 3)

    def test_two_are_not_enough(self):
        row = self.add(["f0", "f1"])
        prices = [600.0, 620.0, 640.0, 800.0, 825.0, 850.0, 875.0, 900.0]
        import statistics
        self.assertAlmostEqual(row.resale, statistics.median(prices) * 0.875)
        self.assertIn("nog maar 2 snel verkocht", row.flip_basis)

    def test_what_counts_as_fast(self):
        gone = (self.now - timedelta(days=1)).isoformat()
        first = (self.now - timedelta(days=30)).isoformat()
        base = {"disappeared_at": gone, "reserved_at": None, "days_online": None, "first_seen": first}
        self.assertFalse(rb.sold_fast(base))
        self.assertTrue(rb.sold_fast(dict(base, reserved_at=first)))  # gereserveerd en dan weg
        self.assertTrue(rb.sold_fast(dict(base, days_online=7)))
        self.assertFalse(rb.sold_fast(dict(base, days_online=8)))
        self.assertTrue(rb.sold_fast(dict(base, first_seen=(self.now - timedelta(days=6)).isoformat())))
        self.assertFalse(rb.sold_fast(dict(base, disappeared_at=None, reserved_at=first)))


class OwnLinkTest(Case):
    """De eigen koppeling (bike_link/bike_model, migratie 19) via
    racebikes.apply_model(), zonder server."""

    def setUp(self):
        super().setUp()
        conn = db.connect(self.db)
        db.sync_listings(conn, "racefiets", [bike("y", 450.0, title="Cube Attain racefiets",
                                                   description="Bouwjaar 2012, carbon, velgremmen.")],
                         self.now.isoformat())
        conn.close()
        self.base = rb.build_base(self.db, self.dir / "geen_fiets.md")

    def links(self):
        conn = db.connect(self.db)
        try:
            return db.list_bike_models(conn), db.list_bike_links(conn)
        finally:
            conn.close()

    def test_link_to_a_new_model_and_back(self):
        message, row, keys = rb.apply_model(self.base, self.db, {"item_id": "c", "model": "Koga  Kinsei Pro"})
        self.assertIn("na de volgende ronde", message)
        (model,), links = self.links()
        self.assertEqual((model["name"], model["brand"], model["family"], model["variant"]),
                         ("Koga Kinsei Pro", "koga", "kinsei", "pro"))
        self.assertEqual((links["c"]["model_id"], links["c"]["confirmed"]), (model["id"], 1))
        self.assertIs(self.base.row("c"), row)
        self.assertEqual((row.identity.name, row.identity.source, row.name), ("Koga Kinsei Pro", "eigen", "Koga Kinsei Pro"))
        self.assertEqual(keys, {"cubeattain", "kogakinseipro"})
        # Verplaatst in de pool: weg bij Cube Attain, bij het nieuwe model.
        self.assertEqual([c[2][0] for c in self.base.pool.by_exact["kogakinseipro"]], ["c"])
        self.assertNotIn("c", [c[2][0] for c in self.base.pool.by_exact["cubeattain"]])
        # Een volle herberekening leest de koppeling uit de database.
        self.assertEqual(rb.build_base(self.db, self.dir / "geen_fiets.md").row("c").identity.own, "Koga Kinsei Pro")

        _, row, _ = rb.apply_model(self.base, self.db, {"item_id": "c", "clear": "1"})
        self.assertEqual(self.links()[1], {})
        self.assertEqual((row.identity.own, row.identity.exact), (None, "cubeattain"))
        self.assertIn("c", [c[2][0] for c in self.base.pool.by_exact["cubeattain"]])

    def test_the_owners_year_goes_before_the_text(self):
        self.assertEqual(self.base.row("y").identity.year, 2012)
        _, row, _ = rb.apply_model(self.base, self.db, {"item_id": "y", "year": "2016"})
        self.assertEqual((row.identity.year, row.identity.own_year, row.identity.own), (2016, True, None))
        self.assertIn("2016", row.specs)
        self.assertEqual(self.links()[1]["y"]["model_id"], None)
        _, row, _ = rb.apply_model(self.base, self.db, {"item_id": "y", "year": ""})
        self.assertEqual((row.identity.year, row.identity.own_year), (2012, False))

    def test_klopt_keeps_the_model_and_marks_it_checked(self):
        before = self.base.row("c").identity.exact
        _, row, _ = rb.apply_model(self.base, self.db, {"item_id": "c", "confirm": "1"})
        (model,), _ = self.links()
        self.assertEqual(model["name"], "Cube Attain (overig)")
        self.assertEqual((row.identity.exact, row.identity.confirmed), (before, True))
        self.assertTrue(rb.bike_json(row, rb.load_fresh(self.db))["ok"])
        # Een tweede fiets aan hetzelfde model maakt geen tweede model.
        rb.apply_model(self.base, self.db, {"item_id": "a0", "model": "cube attain"})
        self.assertEqual(len(self.links()[0]), 1)

    def test_checks(self):
        for form, why in (({"item_id": "c", "year": "1899"}, "bouwjaar"),
                          ({"item_id": "c", "model": "Koga"}, "merk en minstens één woord"),
                          ({"item_id": "c", "model": "K" * 81 + " x"}, "tekens"),
                          ({"item_id": "weg", "model": "Koga Kinsei"}, "niet (meer) op de pagina"),
                          ({"item_id": "c"}, "niets te koppelen")):
            data = rb.model_update(self.base, self.db, form)
            self.assertIn("Niet opgeslagen", data["message"])
            self.assertIn(why, data["message"])
        self.assertEqual(self.links(), ([], {}))

    def test_an_own_model_without_listings_is_in_the_list(self):
        data = rb.model_update(self.base, self.db, {"model": "Koga Kinsei Pro"})
        self.assertEqual(data["models"][0]["n"], "Koga Kinsei Pro")
        html = rb.render(rb.build_base(self.db, self.dir / "geen_fiets.md"), rb.load_fresh(self.db), "tok")
        models = json.loads(re.search(r"id='models'>(.*?)</script>", html).group(1).replace("<\\/", "</"))
        koga = next(m for m in models if m["n"] == "Koga Kinsei Pro")
        self.assertEqual((koga["s"], koga["a"], koga["lk"]), ("eigen", 0, 0))
        attain = next(m for m in models if m["k"] == "cubeattain")
        self.assertEqual((attain["a"], attain["lk"], attain["s"]), (6, 7, "referentie"))


class RuleTest(Case):
    """Regels leren (stap 2 F): na drie dezelfde correcties een voorstel,
    pas na toepassen een regel (bike_rule, migratie 20)."""

    def setUp(self):
        super().setUp()
        conn = db.connect(self.db)
        db.sync_listings(conn, "racefiets", [bike("d9", 640.0, title="Trek Domane racefiets")],
                         (self.now - timedelta(days=20)).isoformat())
        db.sync_listings(conn, "racefiets", [bike(f"d{i}", 600.0 + 10 * i, title="Trek Domane racefiets")
                                             for i in range(5)], self.now.isoformat())
        conn.close()
        self.base = rb.build_base(self.db, self.dir / "geen_fiets.md")

    def correct(self, *ids, model="Trek Domane AL 2"):
        for item_id in ids:
            data = rb.model_update(self.base, self.db, {"item_id": item_id, "model": model})
        return data

    def test_three_corrections_make_a_proposal(self):
        self.correct("d0", "d1")
        self.assertEqual(rb.rules_json(self.base)["p"], [])
        data = self.correct("d2")
        self.assertIn("voorstel voor een regel", data["message"])
        (proposal,) = data["rules"]["p"]
        self.assertEqual((proposal["k"], proposal["kn"], proposal["m"], proposal["n"]),
                         ("trekdomane", "Trek Domane", "Trek Domane AL 2", 3))
        # Klopt op het herkende model is geen correctie: geen voorstel.
        rb.model_update(self.base, self.db, {"item_id": "a0", "confirm": "1"})
        self.assertEqual(len(rb.rules_json(self.base)["p"]), 1)

    def test_apply_moves_every_bike_with_that_recognition(self):
        self.correct("d0", "d1", "d2")
        rb.model_update(self.base, self.db, {"item_id": "d3", "model": "Trek Domane SL6"})  # eigen koppeling gaat voor
        model_id = rb.rules_json(self.base)["p"][0]["id"]
        data = rb.rule_update(self.base, self.db, {"from_key": "trekdomane", "model_id": str(model_id),
                                                    "answer": "toepassen"})
        self.assertIn("Regel toegepast", data["message"])
        self.assertEqual({b["id"]: b["src"] for b in data["bikes"]},
                         {"d0": "eigen", "d1": "eigen", "d2": "eigen", "d3": "eigen", "d4": "regel"})
        self.assertEqual(self.base.row("d4").identity.name, "Trek Domane AL 2")
        self.assertEqual(self.base.row("d3").identity.name, "Trek Domane SL6")
        # Ook de verdwenen/oudere fiets in de pool, waar niemand op klikte.
        self.assertEqual(self.base.pool.identity_of["d9"].own, "Trek Domane AL 2")
        self.assertEqual(data["rules"], {"p": [], "r": [{"k": "trekdomane", "kn": "Trek Domane", "id": model_id,
                                                         "m": "Trek Domane AL 2", "n": 2}]})
        # Een volle herberekening leest de regel uit de database.
        again = rb.build_base(self.db, self.dir / "geen_fiets.md")
        self.assertEqual((again.row("d4").identity.source, again.row("d3").identity.name), ("regel", "Trek Domane SL6"))

        data = rb.rule_update(self.base, self.db, {"from_key": "trekdomane", "model_id": str(model_id), "answer": "weg"})
        self.assertIn("Regel weggehaald", data["message"])
        self.assertEqual(self.base.row("d4").identity.source, "referentie")
        self.assertEqual(rb.rules_json(self.base)["r"], [])

    def test_no_is_remembered(self):
        self.correct("d0", "d1", "d2")
        model_id = rb.rules_json(self.base)["p"][0]["id"]
        data = rb.rule_update(self.base, self.db, {"from_key": "trekdomane", "model_id": str(model_id), "answer": "nee"})
        self.assertIn("Onthouden", data["message"])
        self.assertEqual(data["rules"], {"p": [], "r": []})
        self.correct("d4")
        self.assertEqual(rb.rules_json(self.base)["p"], [])  # vraagt het niet opnieuw
        self.assertEqual(self.base.row("d3").identity.source, "referentie")
        self.assertIn("Niet opgeslagen", rb.rule_update(self.base, self.db, {"from_key": "x", "model_id": "999",
                                                                             "answer": "toepassen"})["message"])


class YearLookupTest(Case):
    """Bouwjaar opzoeken voor kanshebbers (stap 2 G): racefietsen zonder jaar
    die goedkoop lijken, hooguit `budget` per ronde, nooit twee keer."""

    PAGE = ('<html><body><div class="Description-module-description"><div data-collapsable="description">'
            "Mooie Cube Attain.<br />Bouwjaar 2016, carbon, Shimano 105.</div></div></body></html>")

    def setUp(self):
        super().setUp()
        import recheck as rc
        patcher = mock.patch.object(rc, "MIN_INTERVAL_S", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def session(self, pages):
        from helpers import FakeSession
        return FakeSession(pages)

    def test_only_cheap_bikes_without_a_year(self):
        (target,) = rb.plan_years(self.db, 20)
        self.assertEqual((target.item_id, target.price), ("c", 300.0))
        self.assertIn("% onder de schatting", target.why)
        self.assertEqual(rb.plan_years(self.db, 0), [])
        conn = db.connect(self.db)
        db.sync_listings(conn, "racefiets", [bike("c", 300.0, title="Cube Attain 2015 racefiets")],
                         self.now.isoformat())
        conn.close()
        self.assertEqual(rb.plan_years(self.db, 20), [])  # het jaar staat er nu in
        conn = db.connect(self.db)
        db.sync_listings(conn, "racefiets", [bike("c", 300.0, title="Cube Attain racefiets")], self.now.isoformat())
        db.set_mark(conn, "c", mr.DISMISSED, reason="niet waard", price_eur=300.0)
        conn.close()
        self.assertEqual(rb.plan_years(self.db, 20), [])  # weggezet

    def test_fetch_stores_the_description_and_the_year_counts(self):
        session = self.session({BIKE_URL.format("c"): self.PAGE})
        lines = []
        self.assertEqual(rb.lookup_years(self.db, 20, session=session, log=lines.append), 1)
        self.assertEqual(session.requested, [BIKE_URL.format("c")])
        self.assertIn("bouwjaar 2016", lines[-1])
        row = rb.build_base(self.db, self.dir / "geen_fiets.md").row("c")
        self.assertEqual(row.identity.year, 2016)
        self.assertIn("Bouwjaar 2016", row.text)
        # Nooit twee keer dezelfde.
        self.assertEqual(rb.plan_years(self.db, 20), [])
        self.assertEqual(rb.lookup_years(self.db, 20, session=session, log=lines.append), 0)
        self.assertEqual(len(session.requested), 1)

    def test_gone_forbidden_and_a_changed_page(self):
        from helpers import FakeResponse
        lines = []
        rb.lookup_years(self.db, 20, session=self.session({BIKE_URL.format("c"): FakeResponse("", status_code=410)}),
                        log=lines.append)
        self.assertIn("weg", lines[-1])
        conn = db.connect(self.db)
        self.assertIsNotNone(conn.execute("SELECT disappeared_at FROM listing WHERE item_id = 'c'").fetchone()[0])
        conn.execute("UPDATE listing SET disappeared_at = NULL, days_online = NULL WHERE item_id = 'c'")
        conn.commit()
        conn.close()
        lines = []
        rb.lookup_years(self.db, 20, session=self.session({BIKE_URL.format("c"): FakeResponse("", status_code=403)}),
                        log=lines.append)
        self.assertIn("403", lines[-1])
        lines = []
        rb.lookup_years(self.db, 20, session=self.session({BIKE_URL.format("c"): "<html>iets anders</html>"}),
                        log=lines.append)
        self.assertIn("paginastructuur gewijzigd", lines[-1])
        self.assertEqual([t.item_id for t in rb.plan_years(self.db, 20)], ["c"])  # niets opgeslagen: volgende keer weer

    def test_by_hand_at_most_twenty(self):
        import io
        from contextlib import redirect_stderr
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(rb.main(["jaar", "21", "--db", self.db]), 2)
        self.assertIn("Hooguit 20", err.getvalue())


class PermanentReasonTest(unittest.TestCase):
    def test_no_road_bike_stays_away_when_the_price_drops(self):
        listing = make_listing(price_eur=100.0)
        for reason, back in (("te hoge vraagprijs", True), ("geen racefiets", False)):
            mark = mr.Mark("m1", mr.DISMISSED, "2026-09-29", reason=reason, price_eur=150.0)
            self.assertEqual(mr.is_dismissed(mark, listing), not back, reason)


class LiveTest(Case):
    track_connections = False

    def setUp(self):
        super().setUp()
        self.httpd = dashboard.make_server(self.db, 0, intake_path=self.dir / "geen_fiets.md")
        self.port = self.httpd.server_address[1]
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, fields=None, live=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": f"127.0.0.1:{self.port}"}
        if live:
            headers["X-Live"] = "1"
        body = None
        if fields is not None:
            body = urllib.parse.urlencode(fields)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body, headers)
        r = conn.getresponse()
        text = r.read().decode()
        conn.close()
        return r.status, urllib.parse.unquote(r.getheader("Location") or ""), text

    def token(self):
        return re.search(r"data-token='([^']+)'", self.request("GET", rb.PATH)[2]).group(1)

    def live(self, path, fields):
        status, _, text = self.request("POST", path, {"token": self.token(), "markt": rb.MARKET_KEY, **fields},
                                       live=True)
        self.assertEqual(status, 200)
        return json.loads(text)

    def test_page_mark_note_and_bid_without_reloading(self):
        status, _, page = self.request("GET", rb.PATH)
        self.assertEqual(status, 200)
        self.assertIn("id='bikes'", page)
        data = self.live("/markeer", {"item_id": "c", "soort": "niet doorverkoopbaar"})
        self.assertIn("Weggezet (niet doorverkoopbaar)", data["message"])
        self.assertEqual((data["bike"]["m"], data["bike"]["mr"]), ("weg", "niet doorverkoopbaar"))
        self.assertEqual(self.live("/markeer", {"item_id": "c", "soort": "geen"})["bike"]["m"], "")
        self.assertEqual(self.live("/notitie", {"item_id": "c", "notitie": "ophalen za"})["bike"]["no"], "ophalen za")

        data = self.live("/bod", {"item_id": "c", "bedrag": "275"})
        self.assertIn("€275", data["message"])
        self.assertEqual(data["bike"]["b"][0]["s"], "open")
        self.assertIn("Niet opgeslagen", self.live("/bod", {"item_id": "c", "bedrag": "-5"})["message"])
        data = self.live("/bod/status", {"item_id": "c", "status": "geaccepteerd"})
        self.assertIn("/flips", data["message"])
        self.assertTrue(data["bike"]["own"])
        (flip,) = fl.load_book(self.db, with_market_check=False).flips
        self.assertEqual((flip.trade.market, flip.trade.buy_price_eur, flip.stage), ("fietsen", 275.0, "gekocht"))

    def test_model_link_updates_one_bike_without_recomputing_the_page(self):
        self.request("GET", rb.PATH)  # de berekening staat nu in de cache
        with mock.patch.object(rb, "build_base", wraps=rb.build_base) as built:
            data = self.live(rb.MODEL_PATH, {"item_id": "c", "model": "Koga Kinsei Pro", "year": "2016"})
            self.assertEqual((data["bike"]["grp"], data["bike"]["src"], data["bike"]["yr"], data["bike"]["ok"]),
                             ("Koga Kinsei Pro", "eigen", 2016, True))
            self.assertIn("na de volgende ronde", data["message"])
            self.assertIn("Koga Kinsei Pro", {m["n"] for m in data["models"]})
            self.assertIn("Koga Kinsei Pro", self.request("GET", rb.PATH)[2])
            self.assertIn("Niet opgeslagen", self.live(rb.MODEL_PATH, {"item_id": "c", "year": "1800"})["message"])
            data = self.live(rb.MODEL_PATH, {"model": "Ridley Fenix SL"})
            self.assertEqual(data["models"][0]["n"], "Ridley Fenix SL")
        built.assert_not_called()
        status, _, text = self.request("POST", rb.MODEL_PATH, {"token": "fout", "item_id": "c", "clear": "1"}, live=True)
        self.assertTrue(json.loads(text)["reload"])

    def test_rule_without_recomputing_the_page(self):
        for i in range(3):
            self.live(rb.MODEL_PATH, {"item_id": f"a{i}", "model": "Cube Attain C:62"})
        _, _, page = self.request("GET", rb.PATH)
        rules = json.loads(re.search(r"id='rules'>(.*?)</script>", page).group(1).replace("<\\/", "</"))
        (proposal,) = rules["p"]
        with mock.patch.object(rb, "build_base", wraps=rb.build_base) as built:
            data = self.live(rb.RULE_PATH, {"from_key": proposal["k"], "model_id": proposal["id"], "answer": "toepassen"})
        built.assert_not_called()
        self.assertEqual({b["id"] for b in data["bikes"] if b["src"] == "regel"}, {"a3", "c"})
        self.assertEqual(data["rules"]["r"][0]["m"], "Cube Attain C:62")

    def test_a_busy_database_is_a_message_not_a_traceback(self):
        import sqlite3

        def busy(db_path, form):
            raise sqlite3.OperationalError("database is locked")

        with mock.patch.dict(dashboard.ACTIONS, {"/markeer": busy}):
            data = self.live("/markeer", {"item_id": "c", "soort": "niet waard"})
        self.assertEqual(data["message"], dashboard.DB_BUSY)
        with mock.patch.object(rb, "model_update", side_effect=sqlite3.OperationalError("database is locked")):
            self.assertEqual(self.live(rb.MODEL_PATH, {"item_id": "c", "confirm": "1"})["message"], dashboard.DB_BUSY)
        with mock.patch.object(rb, "reserve_update", side_effect=sqlite3.OperationalError("database is locked")):
            self.assertEqual(self.live(rb.RESERVE_PATH, {"soorten": "cassette"})["message"], dashboard.DB_BUSY)

    def test_spares_choice_and_marking_a_part(self):
        conn = db.connect(self.db)
        db.sync_listings(conn, "x", [make_listing(item_id="p1", title="Shimano cassette 11-28", price_eur=18.0,
                                                  url=PART_URL.format("p1"))], self.now.isoformat())
        conn.close()
        self.request("GET", rb.PATH)
        data = self.live(rb.RESERVE_PATH, {"soorten": "pedalen,cassette"})
        self.assertEqual(data["on"], ["cassette", "pedalen"])
        self.assertIn("Niet opgeslagen", self.live(rb.RESERVE_PATH, {"soorten": "raketten"})["message"])
        data = self.live("/markeer", {"item_id": "p1", "soort": "favoriet"})
        self.assertEqual((data["bike"], data["part"]["m"]), (None, "favoriet"))
        data = self.live("/bod", {"item_id": "p1", "bedrag": "12"})
        self.assertEqual(data["part"]["b"][0]["a"], 12.0)

    def test_computer_page_has_the_bid_control_and_tab(self):
        conn = db.connect(self.db)
        market = [make_listing(item_id=f"g{i}", title="Garmin Edge 530", price_eur=p, url=COMPUTER_URL.format(f"g{i}"))
                  for i, p in enumerate((160.0, 180.0, 200.0, 220.0))]
        db.sync_listings(conn, "garmin", market, self.now.isoformat())
        conn.close()
        _, _, page = self.request("GET", "/")
        self.assertIn("ik heb geboden", page)
        self.assertIn("Mijn biedingen", page)
        token = re.search(r"data-token='([^']+)'", page).group(1)
        status, _, text = self.request("POST", "/bod", {"token": token, "item_id": "g", "bedrag": "70"}, live=True)
        data = json.loads(text)
        self.assertIn("biedingen", data["panels"])
        self.assertEqual(data["tabs"]["biedingen"], "Mijn biedingen (1)")
        self.assertIn("jouw bod €70", data["item"]["mine"])

    def test_postcode_sets_the_distances(self):
        with mock.patch.object(dm, "locate_postcode", return_value=dm.Home("3511AB", 52.0952, 5.1161)) as found:
            status, where, _ = self.request("POST", "/afstand", {"token": self.token(), "markt": rb.MARKET_KEY,
                                                                 "item_id": "postcode", "postcode": "3511ab"})
        found.assert_called_once_with("3511ab")
        self.assertEqual(status, 303)
        self.assertTrue(where.startswith(rb.PATH + "?melding=Afstanden gemeten vanaf 3511AB"))
        _, _, page = self.request("GET", "/")
        self.assertIn("id='km-max'", page)
        with mock.patch.object(dm, "locate_postcode", side_effect=dm.LocateError("te weinig")):
            _, where, _ = self.request("POST", "/afstand", {"token": self.token(), "markt": "fietscomputers",
                                                            "item_id": "postcode", "postcode": "9999"})
        self.assertIn("Niet opgeslagen: te weinig", where)
        self.assertTrue(where.startswith("/?melding="))


if __name__ == "__main__":
    unittest.main()
