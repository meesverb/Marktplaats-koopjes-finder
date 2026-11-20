"""Wat een ronde in de console schrijft: de tabel gesorteerd op dealscore,
het bied-overzicht (met de speelruimte per biedadvertentie) en de slapers.
Kolomkoppen van de hoofdtabel zijn historisch Engels; de rest Nederlands.
"""
from __future__ import annotations

from typing import Optional

import crawl
import dealscore
import sleepers
import upgrade


def print_table(listings: list[crawl.Listing], stats: Optional[dict] = None) -> None:
    if not listings:
        print("No listings found.")
        return

    rows = dealscore.sort_by_score(listings)
    print(
        f"{'':6} {'SCORE':>6} {'PRICE':>8} {'%MED':>6}  {'FRAME':<12} {'GROUPSET':<22} "
        f"{'CONDITION':<20} {'CITY':<15} {'TITLE'}"
    )
    for l in rows:
        mark = (
            ("N" if l.is_new else " ")
            + ("*" if l.is_bargain else " ")
            + ("B" if l.price_is_bid else " ")
            + ("!" if l.ref_better else " ")
            + ("v" if l.price_dropped else " ")
        )
        if l.price_eur is None:
            price_str = l.price_type
        elif l.price_eur < 1:
            price_str = f"€{l.price_eur:.2f}"
        else:
            price_str = f"€{l.price_eur:.0f}"
        pct_str = f"{l.pct_of_median:.0f}%" if l.pct_of_median is not None else "—"
        score_str = f"{l.deal_score:.0f}" if l.deal_score is not None else "—"
        print(
            f"{mark:6} {score_str:>6} {price_str:>8} {pct_str:>6}  {l.frame_height[:12]:<12} "
            f"{l.groupset[:22]:<22} {l.condition[:20]:<20} {l.city[:15]:<15} {l.title[:60]}"
        )
        print(f"      {l.url}")
        if l.deal_score is not None:
            print(f"      score {l.deal_score:.0f}/100 ({l.deal_label}): {l.deal_reasons}")
        if l.price_is_bid:
            bid_info = crawl.format_bid_info(l)
            if bid_info:
                print(f"      bieden: {bid_info}")
        if l.price_dropped:
            print(f"      prijsverlaging: €{l.price_drop_from:.0f} → €{l.price_eur:.0f}")
        if l.ref_label:
            bits = [l.ref_label]
            if l.ref_original_price is not None:
                bits.append(f"nieuw €{l.ref_original_price:.0f}")
            if l.ref_pct_of_original is not None:
                bits.append(f"nu {l.ref_pct_of_original:.0f}% daarvan")
            if l.ref_market_count > 0:
                bits.append(f"tweedehands gem. €{l.ref_market_avg:.0f} (n={l.ref_market_count})")
            if l.ref_specs:
                bits.append(f"specs: {l.ref_specs}")
            if l.ref_score:
                bits.append(f"score: {l.ref_score}")
            marker = " [BETER DAN REFERENTIE]" if l.ref_better else ""
            print(f"      referentie{marker}: {' · '.join(bits)}")

    bargains = [l for l in listings if l.is_bargain]
    new_ones = [l for l in listings if l.is_new]
    bids = [l for l in listings if l.price_is_bid]
    better = [l for l in listings if l.ref_better]
    dropped = [l for l in listings if l.price_dropped]
    open_bids = crawl.open_bid_listings(listings)
    top_deals = [l for l in listings if l.deal_score is not None and l.deal_score >= dealscore.TOP_DEAL_SCORE]
    print(
        f"\n{len(listings)} listings, {len(bargains)} bargains (*), "
        f"{len(new_ones)} new since last run (N), {len(bids)} bidding (B, price = huidig/minimum bod, "
        f"waarvan {len(open_bids)} zonder bod), "
        f"{len(better)} beter dan referentie (!), {len(dropped)} prijsverlaging (v), "
        f"{len(top_deals)} topdeals (score >= {dealscore.TOP_DEAL_SCORE:.0f})"
    )

    if stats is None:
        stats = dealscore.price_stats(listings)
    if stats["count"] >= 2:
        shown_count = len(crawl.market_prices(listings))
        suffix = f" ({shown_count} van {stats['count']} getoond)" if shown_count != stats["count"] else ""
        print(
            f"gemiddelde prijs: €{stats['mean']:.0f} · mediaan: €{stats['median']:.0f} "
            f"(over {stats['count']} geprijsde advertenties){suffix}"
        )


def bid_overview_order(
    bids: list[crawl.Listing], headroom: Optional[dict[str, Optional[float]]] = None
) -> list[crawl.Listing]:
    """The order the bid overview is printed in.

    Without headroom figures this is the original order: listings nobody has
    bid on yet first (there the minimum bid is still the real price), each
    group by deal score. With them, the panel sorts on headroom instead —
    estimated value minus what it costs to get in — because that, not the
    price column, is what says which bid listing is underbid (see
    PLAN_FIETSWAARDE.md §7). Listings whose headroom is unknown keep the old
    ordering and sink below the ones that have a number: unknown is not the
    same as no room."""
    known: list[crawl.Listing] = []
    unknown = bids
    if headroom:
        known = [l for l in bids if headroom.get(l.item_id) is not None]
        known.sort(key=lambda l: headroom[l.item_id], reverse=True)
        unknown = [l for l in bids if headroom.get(l.item_id) is None]
    return (
        known
        + dealscore.sort_by_score([l for l in unknown if l.bid_open])
        + dealscore.sort_by_score([l for l in unknown if not l.bid_open])
    )


def print_bid_overview(
    listings: list[crawl.Listing],
    limit: int = 25,
    headroom: Optional[dict[str, Optional[float]]] = None,
) -> None:
    """A separate look at the bidding listings — what it would cost to be the
    first bidder, how much room there is between that and what the thing is
    worth, and how it compares to the median and to what the model is known to
    go for."""
    bids = crawl.bid_listings(listings)
    if not bids:
        return

    open_bids = crawl.open_bid_listings(listings)
    print(f"\nBIED-OVERZICHT — {len(bids)} bied-advertenties, waarvan {len(open_bids)} nog zonder bod")
    room_header = f"{'RUIMTE':>8} " if headroom else ""
    print(
        f"  {'SCORE':>5} {'PRIJS':>8} {'%MED':>6} {room_header} {'BOD':<42} "
        f"{'REFERENTIE':<28} TITEL"
    )

    ordered = bid_overview_order(bids, headroom)
    for l in ordered[:limit]:
        score_str = f"{l.deal_score:.0f}" if l.deal_score is not None else "—"
        price_str = f"€{l.price_eur:.0f}" if l.price_eur is not None else l.price_type
        pct_str = f"{l.pct_of_median:.0f}%" if l.pct_of_median is not None else "—"
        room_str = ""
        if headroom:
            room = headroom.get(l.item_id)
            # A missing headroom prints as a dash, never as EUR 0 — that
            # distinction is the whole point of the column.
            room_str = f"{('€%.0f' % room) if room is not None else '—':>8} "
        status = crawl.format_bid_info(l) or "bod"
        if l.ref_label:
            ref = l.ref_label
            if l.ref_market_count > 0:
                ref += f" (2e-hands gem. €{l.ref_market_avg:.0f})"
            elif l.ref_original_price is not None:
                ref += f" (nieuw €{l.ref_original_price:.0f})"
        else:
            ref = "—"
        print(
            f"  {score_str:>5} {price_str:>8} {pct_str:>6} {room_str} {status[:42]:<42} "
            f"{ref[:28]:<28} {l.title[:40]}"
        )
        print(f"        {l.url}")

    if len(ordered) > limit:
        print(f"  ... en nog {len(ordered) - limit} (zie het HTML-rapport, tab 'Bieden')")


def print_sleepers(listings: list[crawl.Listing], limit: int = 10) -> None:
    """The sleepers (sleepers.py), after the bid overview: short, because
    the point is to go and look at the photos, which the console can't show."""
    found = sleepers.sleepers(listings)
    if not found:
        return
    print(f"\nSLAPERS — {len(found)} advertentie(s) zonder merk of model; bekijk de foto's")
    for l in found[:limit]:
        new = "N" if l.is_new else " "
        print(
            f"  {new} {l.sleeper_score:>3.0f} {sleepers.price_text(l)[:22]:<22} "
            f"{l.city[:16]:<16} {l.title[:40]}"
        )
        print(f"        {l.sleeper_reasons}")
        print(f"        {l.url}")
    if len(found) > limit:
        print(f"  ... en nog {len(found) - limit} (zie het HTML-rapport, tab 'Slapers')")


def bid_headroom_by_id(
    listings: list[crawl.Listing], median: Optional[float]
) -> dict[str, Optional[float]]:
    """Headroom per bidding listing, for the overview above. A plain dict of
    euros, so nothing else here has to know about upgrade.py's types."""
    # A rough estimate (only the query's median behind it) gets no figure
    # here: it would rank a €20 seat post in the racefietsen category above
    # every real bike. Those listings fall back to the deal-score order below
    # the ones with a real estimate — and the deal score already is that
    # same comparison with the median.
    return {
        row.listing.item_id: None if row.estimate.rough else row.headroom_eur
        for row in upgrade.bid_panel(listings, median)
    }
