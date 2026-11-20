"""De dealscore (0-100) per advertentie: hoe goed is de *prijs*, uit % van de
mediaan van de zoekopdracht, % van het 2e-hands gemiddelde (de eigen
prijshistorie) en % van de nieuwprijs, plus bonussen voor een prijsdaling en
een referentiematch "beter dan baseline". Met de onderbouwing per signaal in
`Listing.deal_reasons`. Ook de koopjesvlag (`flag_bargains()`: ≤ een
fractie van de mediaan) en de prijsstatistiek van een zoekopdracht.

Niet te verwarren met de kwaliteitsscore (scoring.py: hoe goed is de fiets)
of de waardescore (geschatte waarde / prijs). Uitleg en weging:
docs/rapport.md → "Dealscore".
"""
from __future__ import annotations

import statistics

import crawl


def flag_bargains(listings: list[crawl.Listing], bargain_ratio: float) -> list[crawl.Listing]:
    priced = crawl.market_prices(listings)
    if len(priced) < 2:
        return listings

    median_price = statistics.median(priced)
    threshold = median_price * bargain_ratio
    for listing in listings:
        if listing.price_eur is not None:
            listing.pct_of_median = round(listing.price_eur / median_price * 100, 1)
            if listing.price_eur <= threshold:
                listing.is_bargain = True
        # What being the first bidder would cost, on the same scale — for a
        # listing whose accepted minimum bid sits well under the asking price,
        # that's the number that says whether it's worth a try.
        if listing.bid_minimum is not None:
            listing.bid_minimum_pct_of_median = round(
                listing.bid_minimum / median_price * 100, 1
            )
    return listings


def price_stats(listings: list[crawl.Listing]) -> dict:
    # Same definition as flag_bargains uses, so the median printed under the
    # table is the median the "% v. mediaan" column is measured against.
    priced = crawl.market_prices(listings)
    if not priced:
        return {"count": 0, "mean": None, "median": None}
    return {
        "count": len(priced),
        "mean": statistics.mean(priced),
        "median": statistics.median(priced),
    }


# (best ratio -> 100, worst ratio -> 0, weight). Each range is centered so
# that sitting exactly on its benchmark scores 50 — that way a 50 means the
# same thing ("priced normally") no matter which signals a listing happened to
# have, and the weights below are the only thing that shifts the balance.
SCORE_MEDIAN_RANGE = (0.30, 1.70, 1.0)


# The secondhand average is the strongest signal — it's what this exact model
# actually goes for, observed first-hand, rather than a retail price from
# whenever it was new. It needs a couple of sightings to mean anything.
SCORE_MARKET_RANGE = (0.40, 1.60, 2.0)


SCORE_MARKET_MIN_OBSERVATIONS = 2


# Original retail price is the weakest: for anything vintage, every listing
# sits far below it, so it barely separates a good deal from a bad one.
SCORE_ORIGINAL_RANGE = (0.15, 0.85, 0.75)


SCORE_DROP_BONUS_MAX = 10.0


SCORE_BETTER_BONUS = 8.0


# (score at or above -> label, CSS class for the HTML score pill), best first.
SCORE_LABELS = [
    (80.0, "Topdeal", "top"),
    (65.0, "Goede deal", "good"),
    (45.0, "Redelijk", "ok"),
    (25.0, "Aan de prijs", "low"),
    (0.0, "Duur", "low"),
]


TOP_DEAL_SCORE = SCORE_LABELS[0][0]


def ratio_score(ratio: float, best: float, worst: float) -> float:
    """Map a price ratio (1.0 = at the benchmark) onto 0-100, where `best`
    (a low ratio, i.e. cheap) is 100 and `worst` (a high ratio) is 0."""
    if ratio <= best:
        return 100.0
    if ratio >= worst:
        return 0.0
    return (worst - ratio) / (worst - best) * 100.0


def score_listing(listing: crawl.Listing) -> None:
    """Fill in deal_score / deal_label / deal_reasons for one listing."""
    if listing.price_eur is None:
        return

    parts: list[tuple[float, float, str]] = []  # (score, weight, explanation)

    if listing.pct_of_median is not None:
        best, worst, weight = SCORE_MEDIAN_RANGE
        ratio = listing.pct_of_median / 100
        parts.append(
            (ratio_score(ratio, best, worst), weight, f"{listing.pct_of_median:.0f}% van mediaan")
        )

    if (
        listing.ref_market_avg
        and listing.ref_market_count >= SCORE_MARKET_MIN_OBSERVATIONS
    ):
        best, worst, weight = SCORE_MARKET_RANGE
        ratio = listing.price_eur / listing.ref_market_avg
        parts.append(
            (
                ratio_score(ratio, best, worst),
                weight,
                f"{ratio * 100:.0f}% van 2e-hands gem. (n={listing.ref_market_count})",
            )
        )

    if listing.ref_pct_of_original is not None:
        best, worst, weight = SCORE_ORIGINAL_RANGE
        ratio = listing.ref_pct_of_original / 100
        parts.append(
            (
                ratio_score(ratio, best, worst),
                weight,
                f"{listing.ref_pct_of_original:.0f}% van nieuwprijs",
            )
        )

    if not parts:
        return

    total_weight = sum(w for _, w, _ in parts)
    score = sum(s * w for s, w, _ in parts) / total_weight
    reasons = [text for _, _, text in parts]

    # Bonuses, on top of the price signals rather than averaged into them: a
    # listing without a price drop shouldn't be scored as if it had a bad one.
    if listing.price_dropped and listing.price_drop_from:
        drop_pct = (listing.price_drop_from - listing.price_eur) / listing.price_drop_from * 100
        bonus = min(SCORE_DROP_BONUS_MAX, drop_pct / 2)
        score += bonus
        reasons.append(f"prijsdaling {drop_pct:.0f}% (+{bonus:.0f})")

    if listing.ref_better:
        score += SCORE_BETTER_BONUS
        reasons.append(f"beter dan referentie (+{SCORE_BETTER_BONUS:.0f})")

    # A bid listing's price is where the bidding stands now, not what it will
    # sell for, so its score is an upper bound — say so rather than quietly
    # ranking it above fixed-price listings it may well end up more expensive
    # than.
    if listing.price_is_bid:
        reasons.append("bod — eindprijs kan hoger uitvallen")

    # Rounded to a whole number, and the label/threshold work off that same
    # number — otherwise a 79.6 would show as "80" while being sorted and
    # counted as something below the Topdeal cutoff. Whole numbers are also
    # about as much precision as a heuristic like this honestly has.
    listing.deal_score = float(round(max(0.0, min(100.0, score))))
    listing.deal_reasons = " · ".join(reasons)
    for threshold, label, _ in SCORE_LABELS:
        if listing.deal_score >= threshold:
            listing.deal_label = label
            break


def score_listings(listings: list[crawl.Listing]) -> None:
    """Combine every price signal collected so far into one score per listing.
    Run this last — it reads pct_of_median, the reference match, the observed
    secondhand average and the price-drop flag, so all of those have to be
    filled in already."""
    for listing in listings:
        score_listing(listing)


def sort_by_score(listings: list[crawl.Listing]) -> list[crawl.Listing]:
    """Best deal first; unscored listings (no price) last."""
    return sorted(
        listings,
        key=lambda l: (
            l.deal_score is None,
            -(l.deal_score if l.deal_score is not None else 0),
            l.price_eur if l.price_eur is not None else float("inf"),
        ),
    )
