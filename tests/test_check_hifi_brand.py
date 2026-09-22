"""check_hifi_brand.py — the hifidatabase.com lookup used while filling in
reference_prices.csv.

No network here: the site's HTML is canned and requests.get is swapped out.
"""
import unittest
from unittest import mock

from helpers import mp  # noqa: F401  (adds the repo root to sys.path)

import check_hifi_brand as chb


PAGE = """
<div id="l1" class="linklisting">
<h4 class="linktitle">
WHARFEDALE
<a href="https://www.hifidatabase.com/detail/diamond">Diamond 9.1</a>
</h4>
<div class="small">Speaker (1,234 views : 5 votes : 2 reviews)</div>
</div>
"""


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        pass


class CheckBrandTest(unittest.TestCase):
    def fetch(self, brand: str, page: str = PAGE):
        requested = []

        def fake_get(url, headers=None, timeout=0):
            requested.append(url)
            return FakeResponse(page)

        with mock.patch.object(chb.requests, "get", fake_get):
            try:
                models = chb.check_brand(brand)
            except RuntimeError:
                models = None
        return requested[0], models

    def test_the_brand_is_url_encoded_not_just_despaced(self):
        # A brand with "/", "#" or "?" in it used to end up as a path
        # separator, a fragment or a query string instead of the brand.
        url, _ = self.fetch("AC/DC #2")
        self.assertTrue(url.endswith("/Manufacturer_Index_Detailed/AC%2FDC%20%232/"))

    def test_a_plain_brand_still_looks_the_way_it_always_did(self):
        url, _ = self.fetch("Wharfedale")
        self.assertTrue(url.endswith("/Manufacturer_Index_Detailed/Wharfedale/"))

    def test_the_page_spelling_the_brand_differently_still_matches(self):
        # The page shouts "WHARFEDALE"; you typed "Wharfedale". Reporting
        # "could not find any models" for that is a confusing way to spend an
        # evening.
        _, models = self.fetch("Wharfedale")
        self.assertEqual(
            models, [("Diamond 9.1", "https://www.hifidatabase.com/detail/diamond", 1234, 5, 2)]
        )


if __name__ == "__main__":
    unittest.main()
