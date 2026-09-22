"""check_reference_overlaps.py — the "is my pattern too broad?" check.

Matching in reference_prices.csv is first-match-wins in file order, and that
is the whole point of this check: only a pattern that sits ABOVE the row it
matches actually steals anything.
"""
import tempfile
import unittest
from pathlib import Path

from helpers import mp  # noqa: F401  (adds the repo root to sys.path)

import check_reference_overlaps as cro


class FindOverlapsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def overlaps(self, *rows: str):
        path = self.tmp / "ref.csv"
        path.write_text(
            "pattern,label,original_price_eur,specs,score,better_than_baseline\n"
            + "".join(f"{r},,,,\n" for r in rows),
            encoding="utf-8",
        )
        return cro.find_overlaps(mp.load_reference_data(str(path)))

    def test_a_broad_pattern_above_a_specific_row_is_reported(self):
        # "Mission" first means a "Mission 731" listing never reaches the
        # Mission 731 row.
        self.assertEqual(
            self.overlaps("Mission,Mission", "Mission 731,Mission 731"),
            [("Mission", "Mission 731")],
        )

    def test_the_same_pair_in_the_right_order_is_not_a_problem(self):
        # Specific first, broad below: exactly how the file is supposed to be
        # ordered, and it used to be reported as an overlap anyway.
        self.assertEqual(self.overlaps("Mission 731,Mission 731", "Mission,Mission"), [])

    def test_unrelated_rows_stay_quiet(self):
        self.assertEqual(self.overlaps("Mission,Mission", "Wharfedale,Wharfedale"), [])


class DeadPatternTest(FindOverlapsTest):
    """A typo in a pattern has no symptom: the row simply never matches."""

    def dead(self, *rows: str):
        path = self.tmp / "ref.csv"
        path.write_text(
            "pattern,label,original_price_eur,specs,score,better_than_baseline\n"
            + "".join(f"{r},,,,\n" for r in rows),
            encoding="utf-8",
        )
        return cro.find_dead_patterns(mp.load_reference_data(str(path)))

    def test_a_pattern_that_cannot_match_its_own_label_is_reported(self):
        self.assertEqual(self.dead(r"Mission\s*7[0-3]2,Mission 731"), ["Mission 731"])

    def test_a_working_pattern_is_not_reported(self):
        self.assertEqual(self.dead(r"Mission\s*73[12],Mission 731"), [])

    def test_the_real_reference_file_has_none(self):
        # Also a guard on the check itself: it should not start flagging the
        # 43 rows that are actually in use.
        self.assertEqual(cro.find_dead_patterns(mp.load_reference_data("reference_prices.csv")), [])


if __name__ == "__main__":
    unittest.main()
