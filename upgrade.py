"""Upgrade-finder en biedlogica — PLAN_FIETSWAARDE.md fase 5.

Zet de twee motoren van fase 3 en 4 aan elkaar: de taxatie levert het budget,
de kwaliteitsscore levert de baseline, en dit bestand beantwoordt de vraag
waar het plan om begonnen is — *welke fiets kan hij hiervoor terugkopen, en
welke biedadvertentie is onderbeboden.*

Vier dingen gebeuren hier, en alle vier staan ze in §7 van het plan:

1. **De maatpoort.** Geen score maar een harde ja/nee op de framemaat. Let op
   het onderscheid tussen *buiten de maat* en *maat onbekend*: het eerste valt
   af, het tweede blijft zichtbaar met een vlag. Op Marktplaats staat de maat
   vaak alleen in de omschrijving, en alles zonder `frameHeight`-attribuut
   weggooien kost meer kandidaten dan het oplevert.
2. **Het budget hangt aan de kandidaat, niet andersom.** De CSC-wielset is een
   velremset. Bij een velremkandidaat verhuist hij mee (dan telt hij in de
   *score* van die kandidaat, niet in het budget); bij een schijfremkandidaat
   moet hij verkocht worden (dan telt hij in het *budget*, niet in de score).
   Eén budget vooraf kiezen zou die hele afweging wegpoetsen.
3. **De effectieve prijs.** Een vaste prijs maal een onderhandelingsfactor, of
   wat het kost om een biedadvertentie binnen te komen. Vraagprijs én
   effectieve prijs blijven allebei zichtbaar: het plan vraagt dat expliciet.
4. **Speelruimte.** `geschatte waarde − instapprijs` per biedadvertentie. Dat
   is waar de koopjes zitten, omdat deze advertenties onzichtbaar zijn voor
   wie op prijs sorteert.

Wat hier met opzet *niet* gebeurt: bieden of reageren op advertenties. Dit
gereedschap rangschikt en legt uit; de eigenaar doet de rest zelf (§11).

De rekenkunde is puur en zonder database of netwerk testbaar; alleen
`fetch_candidate_listings()` en `main()` raken `koopjes.db` aan.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import statistics
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

import db
import racefiets_jev as mp
import scoring as sc
import valuation as val

# Hoeveel punten een kandidaat boven de baseline moet zitten voordat hij een
# upgrade heet. Zonder marge is elk afrondingsverschil al "beter", en dan
# staat de lijst vol fietsen die in de praktijk hetzelfde zijn.
DEFAULT_SCORE_MARGIN = 5.0

# mijn_fiets.md noemt "max €250 boven op de opbrengst". Dat bedrag wordt uit
# dat bestand gelezen; dit is de terugval als het er niet in staat.
DEFAULT_EXTRA_BUDGET_EUR = 250.0

# Framemaat: de doelmaat komt uit mijn_fiets.md (56). De tolerantie is dezelfde
# als scoring.fits_frame_size() aanhoudt — een 54 of 58 is met een andere
# zadelpen en stuurpen vaak nog te rijden, een 52 of 61 niet.
DEFAULT_SIZE_TOLERANCE_CM = 2.0

# Evenveel waarnemingen als score_listing() eist voordat het 2e-hands
# gemiddelde meetelt: onder twee sightings is het geen gemiddelde maar een
# toevalstreffer. Bewust dezelfde drempel, zodat de twee niet uit elkaar lopen.
MIN_MARKET_OBSERVATIONS = mp.SCORE_MARKET_MIN_OBSERVATIONS

SIZE_FITS = "past"
SIZE_WRONG = "buiten de maat"
SIZE_UNKNOWN = "maat onbekend"

ROUTE_RIM = "velrem"
ROUTE_DISC = "schijfrem"
ROUTE_UNKNOWN = "remtype onbekend"


# --- Maatpoort (§7: geen score, een harde ja/nee) --------------------------


def size_verdict(
    frame_height: str, target_cm: float, tolerance_cm: float = DEFAULT_SIZE_TOLERANCE_CM
) -> str:
    """SIZE_FITS / SIZE_WRONG / SIZE_UNKNOWN voor één Marktplaats-maatveld.

    Drie uitkomsten en niet twee, want `frame_height_bounds()` geeft None
    zowel voor "veld leeg" als voor "onleesbaar", en dat is iets anders dan
    een maat die niet past. scoring.fits_frame_size() vouwt die twee samen tot
    False en laat de afweging bewust aan de aanroeper; dit is die afweging."""
    bounds = mp.frame_height_bounds(frame_height)
    if bounds is None:
        return SIZE_UNKNOWN
    return SIZE_FITS if sc.fits_frame_size(bounds, target_cm, tolerance_cm) else SIZE_WRONG


# --- Remtype → welke route de wielset neemt --------------------------------


def brake_route(brake_type: Optional[str]) -> str:
    """Welk van de twee scenario's uit §7 op deze kandidaat van toepassing is.

    Onbekend is expliciet een eigen uitkomst en wordt níet als velrem gelezen.
    Een velremstempel geeft de kandidaat een wielsetbonus in de score die hij
    misschien helemaal niet kan gebruiken — en dat is een fout die je pas ziet
    als de fiets voor de deur staat. Onbekend krijgt daarom geen bonus, en het
    lagere van de twee budgetten (zie `Budgets.for_route()`)."""
    if not brake_type:
        return ROUTE_UNKNOWN
    lowered = brake_type.lower()
    if "schijf" in lowered:
        return ROUTE_DISC
    if "velrem" in lowered:
        return ROUTE_RIM
    return ROUTE_UNKNOWN


# --- Budget (§7: hangt af van de kandidaat) --------------------------------


@dataclass(frozen=True)
class Budget:
    """Wat er voor een kandidaat van dit remtype te besteden is, met de
    optelsom erbij — een budget zonder herkomst is niet te controleren."""

    amount: float
    route: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Budgets:
    rim: Budget
    disc: Budget

    def for_route(self, route: str) -> Budget:
        """Het budget dat bij deze kandidaat hoort. Een onbekend remtype krijgt
        het velrembudget: dat is het lagere van de twee, en zolang niet
        vaststaat dat de wielset verkocht kan worden, is zijn opbrengst geen
        besteedbaar geld."""
        return self.disc if route == ROUTE_DISC else self.rim


def budgets_from_valuation(
    bike_mid_eur: float,
    *,
    wheelset_value_eur: Optional[float] = None,
    extra_budget_eur: float = DEFAULT_EXTRA_BUDGET_EUR,
) -> Budgets:
    """De twee budgetten uit §7, uit de taxatie van scenario B.

    `bike_mid_eur` is de midden-taxatie van de fiets mét de originele wielen —
    het fietsdeel van scenario B, dus zónder de carbon wielset. Wat die wielset
    los opbrengt is `wheelset_value_eur`, en die post verschilt per route:

    - **velrem**: de wielset verhuist mee naar de nieuwe fiets. Hij wordt niet
      verkocht, dus hij levert geen besteedbaar geld op — hij komt terug in de
      *score* van de kandidaat (zie `with_owner_wheels()`).
    - **schijfrem**: de wielset past niet op de nieuwe fiets en moet verkocht
      worden. Dan is zijn opbrengst wél budget.

    Zonder prijswaarnemingen van losse wielsets is `wheelset_value_eur` None.
    De twee budgetten vallen dan samen; dat staat als bewijsregel in de uitvoer
    in plaats van dat er een bedrag gegokt wordt (dezelfde afspraak als in
    fase 3: liever een lege post dan een verzonnen getal)."""
    common = (
        f"taxatie scenario B (fiets met originele wielen), midden €{bike_mid_eur:.0f}",
        f"eigen geld erbij: €{extra_budget_eur:.0f}",
    )
    rim = Budget(
        amount=bike_mid_eur + extra_budget_eur,
        route=ROUTE_RIM,
        reasons=common + ("carbon wielset verhuist mee, dus geen opbrengst maar extra score",),
    )
    if wheelset_value_eur is None:
        disc_reasons = common + (
            "carbon wielset moet verkocht worden, maar er zijn geen prijswaarnemingen "
            "van losse wielsets — zijn opbrengst telt daarom niet mee",
        )
        disc_amount = bike_mid_eur + extra_budget_eur
    else:
        disc_reasons = common + (
            f"carbon wielset apart verkocht: €{wheelset_value_eur:.0f}",
        )
        disc_amount = bike_mid_eur + wheelset_value_eur + extra_budget_eur
    return Budgets(rim=rim, disc=Budget(disc_amount, ROUTE_DISC, disc_reasons))


# --- De meeverhuizende wielset in de score ---------------------------------


def with_owner_wheels(
    build: sc.Build, owner_wheels: tuple[Optional[str], bool], config: dict
) -> tuple[sc.Build, Optional[str]]:
    """Bij een velremkandidaat verhuist de eigen wielset mee (§7). Dat is voor
    de score alleen winst als die wielset béter is dan wat er al op zit — een
    kandidaat met Zipp-wielen gaat er niet op vooruit van een CSC-set.

    Geeft de (eventueel aangepaste) build terug plus een reden-regel, of None
    als er niets verandert."""
    material, branded = owner_wheels
    if material is None:
        return build, None
    moved = replace(build, wheel_material=material, wheel_branded=branded)
    if sc.score_wheels(moved, config).score <= sc.score_wheels(build, config).score:
        return build, None
    return moved, f"eigen {material} wielset verhuist mee (velremkandidaat)"


# --- Prijzen ---------------------------------------------------------------


@dataclass(frozen=True)
class EffectivePrice:
    """Wat deze advertentie realistisch kost, plus waar dat getal op rust.

    `asking_eur` blijft er los naast staan: §7 eist dat vraagprijs én
    effectieve prijs allebei getoond worden, zodat een gecorrigeerd bedrag
    nooit voor een vraagprijs wordt aangezien."""

    amount: Optional[float]
    basis: str
    asking_eur: Optional[float] = None


def entry_price(listing: mp.Listing) -> EffectivePrice:
    """Wat het kost om een biedadvertentie binnen te komen.

    De valkuil uit CLAUDE.md zit hier: bij een MIN_BID-advertentie is de prijs
    uit de zoekresultaten de vraagprijs, niet het minimumbod. En daar komt de
    acceptatie-eis van deze fase bovenop: is het bod nooit opgehaald, dan valt
    dit niet terug op €0 en ook niet op het minimumbod — beide zouden de
    advertentie goedkoper laten lijken dan we weten. Onbekend blijft onbekend,
    met de vraagprijs als bovengrens waar die er is."""
    if listing.bid_count is None:
        if listing.price_eur is None:
            # FAST_BID zonder biedlookup: de zoekresultaten noemen geen prijs
            # en er is niets opgehaald. Er valt hier niets over te zeggen.
            return EffectivePrice(None, "bod niet opgehaald")
        return EffectivePrice(listing.price_eur, "vraagprijs, bod niet opgehaald", listing.price_eur)

    if listing.bid_count == 0:
        # Niemand heeft geboden: het minimumbod is de echte instapprijs, en
        # dat is precies waar deze advertenties interessant worden.
        if listing.bid_minimum is not None:
            return EffectivePrice(listing.bid_minimum, "minimumbod, nog geen bod", listing.price_eur)
        if listing.price_eur is None:
            # De lookup kwam terug zonder biedingen én zonder minimumbod. Dat
            # komt voor, en het levert geen bedrag op om op te rekenen.
            return EffectivePrice(None, "nog geen bod, geen bedrag bekend")
        return EffectivePrice(listing.price_eur, "vraagprijs, nog geen bod", listing.price_eur)

    # Er is geboden. Bij een FAST_BID staat het hoogste bod in price_eur; bij
    # een MIN_BID staat daar de hoogste van vraagprijs en bod (zie
    # enrich_bid_listings). In beide gevallen is dat de ondergrens van wat je
    # kwijt bent, en dus het eerlijke getal — alleen het etiket verschilt.
    basis = "huidig bod" if listing.price_type == "FAST_BID" else "vraagprijs of hoogste bod"
    return EffectivePrice(listing.price_eur, basis, listing.price_eur)


def effective_price(
    listing: mp.Listing, negotiation_factor: float = val.NEGOTIATION_DEFAULT[1]
) -> EffectivePrice:
    """De prijs waarop gerekend wordt (§7): vraagprijs maal onderhandelings-
    factor bij een vaste prijs, de instapprijs bij een biedadvertentie.

    Op een bod wordt geen onderhandelingsfactor losgelaten. Onder het
    minimumbod of onder het staande bod kun je niet kopen — daar valt niets te
    onderhandelen, dat is de prijs."""
    if listing.price_is_bid:
        return entry_price(listing)
    if listing.price_eur is None:
        return EffectivePrice(None, "geen prijs bekend")
    return EffectivePrice(
        listing.price_eur * negotiation_factor,
        f"vraagprijs €{listing.price_eur:.0f} × {val.dutch(negotiation_factor)} onderhandeling",
        listing.price_eur,
    )


# --- Geschatte waarde en speelruimte ---------------------------------------


@dataclass(frozen=True)
class ValueEstimate:
    amount: Optional[float]
    basis: str


def estimate_value(
    listing: mp.Listing,
    median_eur: Optional[float] = None,
    negotiation_factor: float = val.NEGOTIATION_DEFAULT[1],
) -> ValueEstimate:
    """Wat deze advertentie waard is, uit de beste benchmark die er ligt.

    Een ladder met afnemend vertrouwen, net als E1 in fase 3, maar dan per
    advertentie in plaats van per model: het waargenomen 2e-hands gemiddelde
    van dit exacte referentiemodel gaat vóór de mediaan van de zoekopdracht.

    Allebei zijn het vráágprijzen, dus de E2-correctie uit §6 gaat er
    overheen — anders vergelijkt de speelruimte hieronder een vraagprijs met
    een bod en valt elke biedadvertentie gunstig uit puur omdat er nog niet
    geboden is. Is er geen benchmark, dan is er geen schatting; dan blijft het
    veld leeg in plaats van dat er een getal verschijnt."""
    if listing.ref_market_avg and listing.ref_market_count >= MIN_MARKET_OBSERVATIONS:
        label = listing.ref_label or "referentiemodel"
        return ValueEstimate(
            listing.ref_market_avg * negotiation_factor,
            f"2e-hands gemiddelde {label} (n={listing.ref_market_count}) "
            f"× {val.dutch(negotiation_factor)}",
        )
    if median_eur:
        return ValueEstimate(
            median_eur * negotiation_factor,
            f"mediaan van deze zoekopdracht €{median_eur:.0f} × {val.dutch(negotiation_factor)}",
        )
    return ValueEstimate(None, "geen benchmark")


@dataclass(frozen=True)
class BidRow:
    """Eén regel van het biedpaneel. `headroom_eur` is de speelruimte uit §7:
    geschatte waarde − instapprijs. None betekent onbekend, niet nul."""

    listing: mp.Listing
    estimate: ValueEstimate
    entry: EffectivePrice
    headroom_eur: Optional[float]
    note: str = ""


def bid_headroom(
    listing: mp.Listing,
    median_eur: Optional[float] = None,
    negotiation_factor: float = val.NEGOTIATION_DEFAULT[1],
) -> BidRow:
    """Speelruimte voor één biedadvertentie.

    Het plan schrijft `geschatte waarde − huidig bod`. Het huidige bod is niet
    altijd los waarneembaar — bij een MIN_BID onder de vraagprijs kent
    Marktplaats het bedrag alleen op de advertentiepagina, en zonder
    `--bid-lookup all` is het helemaal niet opgehaald. Daarom wordt hier
    gerekend met de instapprijs: dát is wat je kwijt bent, en zodra het
    huidige bod bekend is, ís de instapprijs dat bod. Waar dat niet zo is,
    zegt `entry.basis` het."""
    estimate = estimate_value(listing, median_eur, negotiation_factor)
    entry = entry_price(listing)
    if estimate.amount is None or entry.amount is None:
        note = "geen schatting" if estimate.amount is None else "geen instapprijs bekend"
        return BidRow(listing, estimate, entry, None, note)
    return BidRow(listing, estimate, entry, estimate.amount - entry.amount)


def bid_panel(
    listings: Sequence[mp.Listing],
    median_eur: Optional[float] = None,
    negotiation_factor: float = val.NEGOTIATION_DEFAULT[1],
) -> list[BidRow]:
    """Alle biedadvertenties, gesorteerd op speelruimte (§7) in plaats van op
    dealscore. Regels zonder speelruimte zakken naar onderen: ze zijn niet
    slecht, ze zijn onbekend, en bovenaan zetten zou dat verwarren."""
    rows = [bid_headroom(l, median_eur, negotiation_factor) for l in listings if l.price_is_bid]
    rows.sort(key=lambda r: (r.headroom_eur is not None, r.headroom_eur or 0.0), reverse=True)
    return rows


# --- De upgrade-finder -----------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    listing: mp.Listing
    quality: sc.QualityScore
    gain: float
    effective: EffectivePrice
    budget: Budget
    upgrade_per_euro: float
    size: str
    reasons: tuple[str, ...] = ()

    @property
    def points_per_100_eur(self) -> float:
        """Dezelfde rangschikking, leesbaar: punten winst per €100."""
        return self.upgrade_per_euro * 100


@dataclass(frozen=True)
class Rejected:
    listing: mp.Listing
    reason: str


@dataclass(frozen=True)
class UpgradeResult:
    candidates: tuple[Candidate, ...]
    rejected: tuple[Rejected, ...]


def find_upgrades(
    listings: Sequence[mp.Listing],
    *,
    baseline: float,
    config: dict,
    budgets: Budgets,
    target_size_cm: float,
    margin: float = DEFAULT_SCORE_MARGIN,
    negotiation_factor: float = val.NEGOTIATION_DEFAULT[1],
    owner_wheels: tuple[Optional[str], bool] = (None, False),
    owner_already_has: frozenset = frozenset(),
    size_tolerance_cm: float = DEFAULT_SIZE_TOLERANCE_CM,
    allow_unknown_size: bool = True,
    as_of_year: Optional[int] = None,
) -> UpgradeResult:
    """Kandidaten uit §7: `past_qua_maat` ∧ `kwaliteitsscore > baseline +
    marge` ∧ `effectieve_prijs ≤ budget`, gerangschikt op upgrade per euro.

    Er wordt geen remtype vooraf uitgesloten. Het plan is daar uitgesproken
    over: juist een uitgesproken koopje bij de schijfremmen is de reden dat dit
    gereedschap bestaat, dus de rangschikking doet het werk en niet een filter.

    Elke afgewezen advertentie komt met een reden terug. Dat is geen extra:
    zonder die lijst is "hij staat er niet bij" niet te onderscheiden van een
    bug in de maatpoort."""
    candidates: list[Candidate] = []
    rejected: list[Rejected] = []

    for listing in listings:
        size = size_verdict(listing.frame_height, target_size_cm, size_tolerance_cm)
        if size == SIZE_WRONG:
            rejected.append(Rejected(listing, f"{SIZE_WRONG} ({listing.frame_height})"))
            continue
        if size == SIZE_UNKNOWN and not allow_unknown_size:
            rejected.append(Rejected(listing, SIZE_UNKNOWN))
            continue

        text = f"{listing.title} {listing.description}"
        build = sc.build_from_listing(
            specs=mp.extract_specs(text),
            groupset_label=listing.groupset,
            groupset_tier=listing.groupset_tier,
            text=text,
            label=listing.title,
        )
        route = brake_route(build.brake_type)
        reasons: list[str] = [f"route: {route}"]
        if route == ROUTE_RIM:
            build, moved = with_owner_wheels(build, owner_wheels, config)
            if moved:
                reasons.append(moved)
        if size == SIZE_UNKNOWN:
            reasons.append("framemaat staat niet in de advertentie — zelf navragen")

        quality = sc.score_build(
            build, config, owner_already_has=owner_already_has, as_of_year=as_of_year
        )
        gain = quality.total - baseline
        if gain <= margin:
            rejected.append(
                Rejected(listing, f"niet beter dan de eigen fiets ({quality.total:.0f} vs {baseline:.0f})")
            )
            continue

        effective = effective_price(listing, negotiation_factor)
        if effective.amount is None:
            rejected.append(Rejected(listing, f"geen bruikbare prijs ({effective.basis})"))
            continue
        if effective.amount <= 0:
            # Een advertentie van €0 is een weggeefactie (priceType FREE), geen
            # koopje met oneindige upgrade per euro. market_prices() gooit hem
            # om dezelfde reden uit de benchmarks.
            rejected.append(Rejected(listing, "prijs €0 — geen vraagprijs om op te rekenen"))
            continue

        budget = budgets.for_route(route)
        if effective.amount > budget.amount:
            rejected.append(
                Rejected(
                    listing,
                    f"boven budget (€{effective.amount:.0f} > €{budget.amount:.0f}, {budget.route})",
                )
            )
            continue

        candidates.append(
            Candidate(
                listing=listing,
                quality=quality,
                gain=gain,
                effective=effective,
                budget=budget,
                upgrade_per_euro=gain / effective.amount,
                size=size,
                reasons=tuple(reasons),
            )
        )

    # Bij gelijke upgrade per euro wint de grootste sprong; item_id sluit af,
    # zodat dezelfde invoer altijd dezelfde volgorde geeft.
    candidates.sort(key=lambda c: (-c.upgrade_per_euro, -c.gain, c.listing.item_id))
    return UpgradeResult(tuple(candidates), tuple(rejected))


# --- Database ---------------------------------------------------------------


def fetch_candidate_listings(
    conn: sqlite3.Connection,
    *,
    window_days: int = val.DEFAULT_COMP_WINDOW_DAYS,
    query: Optional[str] = None,
) -> list[mp.Listing]:
    """Advertenties uit `koopjes.db` als `Listing`, klaar voor find_upgrades().

    Anders dan fetch_comp_candidates() in fase 3 blijven biedadvertenties hier
    wél staan — §3 noemt ze eersterangs, en het zijn juist de kandidaten waar
    het krappe budget nog iets kan.

    `bid_count` en `bid_minimum` blijven leeg: die staan niet in het schema van
    §5, ze worden per run opgehaald. Een uit de database herbouwde
    biedadvertentie is dus een advertentie waarvan het bod niet is opgehaald —
    precies het geval dat entry_price() apart afhandelt. Verdwenen
    advertenties blijven buiten de lijst; die zijn niet meer te koop."""
    sql = [
        "SELECT item_id, title, description, price_eur, price_type, is_bid,",
        "       city, posted_date, condition, frame_height, url, first_seen",
        "FROM listing",
        "WHERE disappeared_at IS NULL",
    ]
    params: list = []
    if window_days > 0:
        # Zelfde meetvenster als fase 3 aanhoudt, hier los uitgerekend zodat
        # dit bestand geen interne helper van valuation.py nodig heeft.
        since = datetime.now(timezone.utc) - timedelta(days=window_days)
        sql.append("AND (last_seen IS NULL OR last_seen >= ?)")
        params.append(since.isoformat(timespec="seconds"))
    if query:
        sql.append("AND query = ?")
        params.append(query)

    listings = []
    for row in conn.execute("\n".join(sql), params).fetchall():
        title = row["title"] or ""
        description = row["description"] or ""
        groupset, tier = mp.detect_groupset(f"{title} {description}")
        listings.append(
            mp.Listing(
                item_id=row["item_id"],
                title=title,
                description=description,
                price_eur=row["price_eur"],
                price_type=row["price_type"] or "",
                city=row["city"] or "",
                date=row["posted_date"] or "",
                condition=row["condition"] or "",
                frame_height=row["frame_height"] or "",
                groupset=groupset,
                groupset_tier=tier,
                url=row["url"] or "",
                price_is_bid=bool(row["is_bid"]),
                first_seen=row["first_seen"] or "",
            )
        )
    return listings


# --- Uitvoer ---------------------------------------------------------------


def format_budgets(budgets: Budgets) -> str:
    lines = ["Budget per route:"]
    for budget in (budgets.rim, budgets.disc):
        lines.append(f"  {budget.route}: €{budget.amount:.0f}")
        for reason in budget.reasons:
            lines.append(f"    - {reason}")
    return "\n".join(lines)


def format_candidate(candidate: Candidate, position: int) -> str:
    l = candidate.listing
    asking = (
        f"€{candidate.effective.asking_eur:.0f}"
        if candidate.effective.asking_eur is not None
        else "—"
    )
    lines = [
        f"{position:>2}. {l.title[:68]}",
        f"    kwaliteit {candidate.quality.total:.0f}/100 (+{candidate.gain:.0f} t.o.v. baseline)"
        f"   {val.dutch(candidate.points_per_100_eur, 1)} punt per €100",
        f"    vraagprijs {asking}   effectief €{candidate.effective.amount:.0f}"
        f"   ({candidate.effective.basis})",
        f"    budget €{candidate.budget.amount:.0f} ({candidate.budget.route}) · maat: {candidate.size}",
    ]
    for name, dimension in candidate.quality.dimensions.items():
        lines.append(f"      {name:<10} {dimension.score:>3.0f}  {' · '.join(dimension.reasons)}")
    for reason in candidate.reasons:
        lines.append(f"      · {reason}")
    lines.append(f"    {l.url}")
    return "\n".join(lines)


def format_bid_row(row: BidRow) -> str:
    headroom = f"€{row.headroom_eur:.0f}" if row.headroom_eur is not None else "onbekend"
    entry = f"€{row.entry.amount:.0f}" if row.entry.amount is not None else "—"
    value = f"€{row.estimate.amount:.0f}" if row.estimate.amount is not None else "—"
    lines = [
        f"  speelruimte {headroom:>9}   instap {entry:>7} ({row.entry.basis})",
        f"      waarde {value} — {row.estimate.basis}",
        f"      {row.listing.title[:66]}",
        f"      {row.listing.url}",
    ]
    if row.note:
        lines.insert(1, f"      {row.note}")
    return "\n".join(lines)


# --- CLI --------------------------------------------------------------------


SIZE_CM_RE = re.compile(r"\s*(\d+(?:[.,]\d+)?)")
# De regel uit de intaketabel van mijn_fiets.md, niet uit het scoringsblok:
# `extras` daar beschrijft wat er bíj de fiets zit, en de Wahoo gaat juist
# niet mee. Voor de vergelijking met kandidaten telt hij wél mee.
COMPUTER_ROW_RE = re.compile(r"^\|\s*Fietscomputer\s*\|([^|]*)\|", re.M | re.I)


def target_size_from(specs: dict[str, str]) -> Optional[float]:
    """De doelframemaat uit het scoringsblok ("size_cm = 56"). None als er
    niets bruikbaars staat — de maatpoort is hard, dus daar dan zelf iets van
    maken zou precies de verkeerde fietsen doorlaten."""
    match = SIZE_CM_RE.match(specs.get("size_cm", ""))
    return float(match.group(1).replace(",", ".")) if match else None


def extra_budget_from(specs: dict[str, str]) -> float:
    """Het eigen geld bovenop de opbrengst, uit het scoringsblok van
    mijn_fiets.md ("max €250 boven op de opbrengst"). Staat er geen bedrag,
    dan de default — met de kanttekening dat dat een aanname is."""
    found = val.EURO_RE.search(specs.get("budget_extra", ""))
    return float(found.group(1).replace(",", ".")) if found else DEFAULT_EXTRA_BUDGET_EUR


def owner_extras_kept(markdown_text: str) -> frozenset:
    """Welke extra's de eigenaar hóudt, voor de korting die §7 vraagt: hij
    houdt zijn Wahoo Elemnt Roam, dus een fietscomputer bij een kandidaat is
    doorverkoopwaarde en geen aanwinst.

    Afgeleid uit de intaketabel in plaats van hier vastgelegd, en alleen als
    die regel ook echt zegt dat het ding niet meegaat — verkoopt hij hem mee,
    dan heeft hij er straks geen meer en telt een computer bij een kandidaat
    gewoon vol mee."""
    match = COMPUTER_ROW_RE.search(markdown_text)
    if match and "niet mee" in match.group(1).lower():
        return frozenset({"computer"})
    return frozenset()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upgrade-finder en biedlogica op de advertenties in koopjes.db (fase 5).",
    )
    parser.add_argument("--db", default="koopjes.db", help="pad naar de database (default: koopjes.db)")
    parser.add_argument(
        "--mijn-fiets", default="mijn_fiets.md",
        help="intakebestand met de eigen fiets (default: mijn_fiets.md)",
    )
    parser.add_argument(
        "--config", default=sc.DEFAULT_CONFIG_PATH,
        help=f"gewichten voor de kwaliteitsscore (default: {sc.DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--query", default=None, help="beperk tot advertenties uit één crawl-zoekopdracht"
    )
    parser.add_argument(
        "--window-days", type=int, default=val.DEFAULT_COMP_WINDOW_DAYS,
        help=f"hoe ver terug advertenties meetellen (default: {val.DEFAULT_COMP_WINDOW_DAYS}, 0 = alles)",
    )
    parser.add_argument(
        "--margin", type=float, default=DEFAULT_SCORE_MARGIN,
        help=f"punten boven de baseline voordat iets een upgrade heet (default: {DEFAULT_SCORE_MARGIN:.0f})",
    )
    parser.add_argument(
        "--budget-extra", type=float, default=None,
        help="eigen geld bovenop de verkoopopbrengst (default: uit mijn_fiets.md)",
    )
    parser.add_argument(
        "--size", type=float, default=None,
        help="doelframemaat in cm (default: uit mijn_fiets.md)",
    )
    parser.add_argument(
        "--size-tolerance", type=float, default=DEFAULT_SIZE_TOLERANCE_CM,
        help=f"speling op de framemaat in cm (default: {DEFAULT_SIZE_TOLERANCE_CM:.0f})",
    )
    parser.add_argument(
        "--strict-size", action="store_true",
        help="advertenties zonder framemaat ook uitsluiten (default: tonen met een vlag)",
    )
    parser.add_argument("--limit", type=int, default=15, help="hoeveel kandidaten tonen (default: 15)")
    parser.add_argument(
        "--show-rejected", action="store_true",
        help="ook tonen wat is afgevallen en waarom",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        with open(args.mijn_fiets, encoding="utf-8") as f:
            intake = f.read()
        bike = val.parse_owner_bike(intake)
    except FileNotFoundError:
        print(f"fout: {args.mijn_fiets} niet gevonden", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"fout: {exc}", file=sys.stderr)
        return 1

    config = sc.load_config(args.config)
    owner_build = sc.build_from_owner_specs(bike.specs, label=bike.label)
    baseline = sc.score_build(owner_build, config).total

    target_size = args.size if args.size is not None else target_size_from(bike.specs)
    if target_size is None:
        print(
            "fout: geen framemaat in mijn_fiets.md en geen --size meegegeven — de maatpoort "
            "is hard, dus zonder doelmaat valt er niets te filteren",
            file=sys.stderr,
        )
        return 1

    extra_budget = (
        args.budget_extra if args.budget_extra is not None else extra_budget_from(bike.specs)
    )
    owner_has = owner_extras_kept(intake)

    # Alleen lezen: de taxatie hieronder wordt niet opgeslagen. Het budget is
    # een tussenstand van deze draai, geen taxatie van de fiets — die hoort bij
    # valuation.py, en twee plekken die in `valuation` schrijven zouden alleen
    # maar rijen opleveren die elkaar tegenspreken.
    conn = db.connect(args.db)
    try:
        comps = val.fetch_comp_candidates(conn, window_days=args.window_days, query=args.query)
        subject = val.subject_from_owner_bike(bike)
        scenario_b = val.value_subject(
            subject,
            comps,
            subject_type="owned_item",
            scenario=val.SCENARIOS["b"],
            negotiation=val.empirical_negotiation_factor(comps),
        )
        if scenario_b is None:
            print(
                f"fout: geen vergelijkbare advertenties in {args.db}, dus geen taxatie en dus "
                "geen budget. Crawl eerst met --query op dit model.",
                file=sys.stderr,
            )
            return 2

        wheelset = val.Component(label=bike.wheelset_label or "carbon wielset")
        budgets = budgets_from_valuation(
            scenario_b.mid_eur,
            wheelset_value_eur=wheelset.market_value,
            extra_budget_eur=extra_budget,
        )

        listings = fetch_candidate_listings(
            conn, window_days=args.window_days, query=args.query
        )
    finally:
        conn.close()

    prices = mp.market_prices(listings)
    median_eur = statistics.median(prices) if prices else None

    print(f"Baseline eigen fiets ({bike.label}): {baseline:.0f}/100")
    print(f"Doelmaat: {target_size:g} cm (±{args.size_tolerance:g})")
    print(format_budgets(budgets))
    print(f"\n{len(listings)} advertenties in het meetvenster")

    result = find_upgrades(
        listings,
        baseline=baseline,
        config=config,
        budgets=budgets,
        target_size_cm=target_size,
        margin=args.margin,
        owner_wheels=(owner_build.wheel_material, owner_build.wheel_branded),
        owner_already_has=owner_has,
        size_tolerance_cm=args.size_tolerance,
        allow_unknown_size=not args.strict_size,
    )

    print(f"\nUPGRADE-KANDIDATEN — {len(result.candidates)} binnen budget en maat")
    if not result.candidates:
        print("  (geen. Dat is een uitkomst, geen fout — het budget is krap, zie mijn_fiets.md.)")
    for position, candidate in enumerate(result.candidates[: args.limit], start=1):
        print(format_candidate(candidate, position))
    if len(result.candidates) > args.limit:
        print(f"  ... en nog {len(result.candidates) - args.limit}")

    rows = bid_panel(listings, median_eur)
    print(f"\nBIEDPANEEL — {len(rows)} biedadvertenties, gesorteerd op speelruimte")
    for row in rows[: args.limit]:
        print(format_bid_row(row))
    if len(rows) > args.limit:
        print(f"  ... en nog {len(rows) - args.limit}")

    if args.show_rejected:
        print(f"\nAFGEVALLEN — {len(result.rejected)}")
        for reject in result.rejected:
            print(f"  {reject.reason}: {reject.listing.title[:60]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
