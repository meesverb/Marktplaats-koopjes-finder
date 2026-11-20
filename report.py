"""Rapportpanelen — PLAN_FIETSWAARDE.md fase 6.

Drie tabbladen naast de advertentietabel, uit §8 van het plan:

- **Mijn fiets** — de taxatie per scenario (A en B) met band en n, de volledige
  bewijslijst met links naar de comps, en de kwaliteitsscore die als baseline
  dient.
- **Upgrade** — de kandidaten van `upgrade.find_upgrades()`, op upgrade per
  euro, met de uitsplitsing per dimensie én wat er is afgevallen en waarom.
- **Biedpaneel** — de biedadvertenties op speelruimte, niet op dealscore.

Hier wordt niets nieuws uitgerekend. De getallen komen uit valuation.py,
scoring.py en upgrade.py; dit bestand zet ze op een rij en escapet ze. Wat
er wél bij komt is de **waardescore** (`upgrade.value_score()`) als eigen
kolom — strikt naast, nooit in plaats van, `deal_score` (§2).

Alleen lezen: de taxatie die hier voor het rapport gemaakt wordt, wordt niet
opgeslagen. Dezelfde afspraak als in upgrade.main(): `valuation` wordt alleen
door valuation.py beschreven, anders ontstaan er rijen die elkaar
tegenspreken.
"""
from __future__ import annotations

import html
import string
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

import computers
import crawl
import db
import dealscore
import scoring as sc
import sleepers
import upgrade as up
from util import euro
import valuation as val

# De gewichten zijn code-configuratie, geen gebruikersdata: ze horen naast het
# script te staan, en een rapport dat vanuit een andere map gedraaid wordt
# moet ze net zo goed vinden.
SCORING_CONFIG_PATH = Path(__file__).resolve().parent / sc.DEFAULT_CONFIG_PATH

SCENARIO_KEYS = ("a", "b")


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


# --- De eigen fiets ---------------------------------------------------------


@dataclass(frozen=True)
class OwnerContext:
    """Alles over de eigen fiets wat de panelen nodig hebben, één keer
    uitgerekend. `valuations` en `budgets` zijn leeg als er geen comps zijn;
    `valuation_problem` zegt dan waarom, zodat het paneel het kan tonen in
    plaats van leeg te blijven."""

    bike: val.OwnerBike
    build: sc.Build
    quality: sc.QualityScore
    config: dict
    target_size_cm: Optional[float]
    extra_budget_eur: float
    owner_has: frozenset
    wheelset: val.Component
    valuations: dict[str, val.Valuation] = field(default_factory=dict)
    comp_count: Optional[int] = None
    budgets: Optional[up.Budgets] = None
    valuation_problem: Optional[str] = None


def load_owner_context(
    mijn_fiets_path: str,
    db_path: Optional[str],
    config_path: str | Path = SCORING_CONFIG_PATH,
    comps: Optional[list] = None,
) -> tuple[Optional[OwnerContext], Optional[str]]:
    """De eigen fiets uit `mijn_fiets.md`, gescoord en — als er een database
    is — getaxeerd. Geeft (context, None) of (None, reden).

    `db_path` None betekent: geen database (--no-db). Een pad dat niet bestaat
    wordt niet aangemaakt; db.connect() zou dat wel doen, en een lege database
    als bijwerking van een rapport is verwarrend.

    `comps`: valuation.fetch_comp_candidates() van deze database, als de
    aanroeper die al heeft (de live pagina /fiets onthoudt ze tussen twee
    klikken); anders worden ze hier opgehaald."""
    try:
        with open(mijn_fiets_path, encoding="utf-8") as f:
            intake = f.read()
        bike = val.parse_owner_bike(intake)
    except FileNotFoundError:
        return None, f"{mijn_fiets_path} niet gevonden — geen eigen fiets om te taxeren"
    except ValueError as exc:
        return None, f"{mijn_fiets_path} is niet te lezen: {exc}"
    try:
        config = sc.load_config(str(config_path))
    except FileNotFoundError:
        return None, f"{config_path} niet gevonden — zonder gewichten geen kwaliteitsscore"
    if db_path is not None and Path(config_path) == SCORING_CONFIG_PATH:
        # De regel die de eigenaar op /upgrade opsloeg (upgrade_test.py):
        # daarmee rekenen /racefietsen, het rapport en het overzicht.
        config, _ = up.apply_saved_rule(config, db_path)

    build = sc.owner_build(bike.specs, label=bike.label, config=config)
    context = OwnerContext(
        bike=bike,
        build=build,
        quality=sc.score_build(build, config),
        config=config,
        target_size_cm=up.target_size_from(bike.specs),
        extra_budget_eur=up.extra_budget_from(bike.specs),
        owner_has=up.owner_extras_kept(intake),
        # Zonder prijswaarnemingen van losse wielsets heeft deze post geen
        # bedrag; de bewijsregels zeggen dat, er wordt niets ingevuld.
        wheelset=val.Component(label=bike.wheelset_label or "carbon wielset"),
    )

    if db_path is None:
        return _without_valuation(context, "geen database (--no-db), dus geen comps om op te taxeren"), None
    # A database that doesn't exist yet (the very first run) has no comps, but
    # verkoopprijs_handmatig still gives a budget — so carry on with none
    # instead of stopping here. Not connected: db.connect() would create it.
    missing = not Path(db_path).exists()
    chosen: frozenset = frozenset()
    if missing:
        comps = []
    else:
        conn = db.connect(db_path)
        try:
            if comps is None:
                comps = val.fetch_comp_candidates(conn)
            chosen = val.chosen_comp_ids(conn)
        finally:
            conn.close()

    subject = val.subject_from_owner_bike(bike)
    comp_set = val.select_comps(subject, comps, chosen)
    negotiation = val.empirical_negotiation_factor(comps)
    valuations: dict[str, val.Valuation] = {}
    for key in SCENARIO_KEYS:
        valuation = val.value_subject(
            subject,
            comps,
            subject_type="owned_item",
            scenario=val.SCENARIOS[key],
            extras=(context.wheelset,) if key == "a" else (),
            negotiation=negotiation,
            chosen=chosen,
        )
        if valuation is not None:
            valuations[key] = valuation

    if "b" not in valuations:
        manual = up.manual_sale_price_from(bike.specs)
        problem = (
            f"{db_path} bestaat nog niet, dus geen comps om op te taxeren."
            if missing
            else f"geen taxatie: {val.no_comps_reason(chosen, db_path)}"
        )
        if manual is None:
            return _without_valuation(
                context,
                problem + f" Of zet {up.MANUAL_SALE_PRICE_KEY} in het scoringsblok van "
                "mijn_fiets.md; dan werkt de upgrade-finder met dat bedrag.",
            ), None
        # Geen taxatie, wel een budget: de upgrade-finder draait op het
        # bedrag van de eigenaar, en het budgetblok zegt waar het vandaan komt.
        return replace(
            _without_valuation(context, problem),
            budgets=up.budgets_from_valuation(
                manual,
                wheelset_value_eur=context.wheelset.market_value,
                extra_budget_eur=context.extra_budget_eur,
                source=up.manual_budget_source(manual),
            ),
        ), None

    amount, source = up.budget_basis(valuations["b"], up.manual_sale_price_from(bike.specs))
    budgets = up.budgets_from_valuation(
        amount,
        wheelset_value_eur=context.wheelset.market_value,
        extra_budget_eur=context.extra_budget_eur,
        source=source,
    )
    context = replace(
        context,
        valuations=valuations,
        comp_count=comp_set.n if comp_set else None,
        budgets=budgets,
    )
    return context, None


def _without_valuation(context: OwnerContext, problem: str) -> OwnerContext:
    return replace(context, valuation_problem=problem)


# --- Paneel: Mijn fiets -----------------------------------------------------


def _dimension_rows(quality: sc.QualityScore) -> str:
    return "\n".join(
        f"<tr><td>{esc(name)}</td><td class='num'>{dimension.score:.0f}</td>"
        f"<td>{esc(' · '.join(dimension.reasons))}</td></tr>"
        for name, dimension in quality.dimensions.items()
    )


def _evidence_rows(valuation: val.Valuation) -> str:
    rows = []
    for item in valuation.evidence:
        link = (
            f"<a href='{esc(item.ref_url)}' target='_blank' rel='noopener'>advertentie</a>"
            if item.ref_url
            else ""
        )
        rows.append(
            f"<tr data-evidence='{esc(item.kind)}'><td>{esc(item.kind)}</td>"
            f"<td class='num'>{euro(item.price_eur)}</td>"
            f"<td>{esc(item.note)}</td><td>{link}</td></tr>"
        )
    return "\n".join(rows)


def _budget_block(budgets: up.Budgets) -> str:
    parts = []
    for budget in (budgets.rim, budgets.disc):
        reasons = "".join(f"<li>{esc(reason)}</li>" for reason in budget.reasons)
        parts.append(
            f"<div class='card'><h4>Budget {esc(budget.route)}kandidaat: {euro(budget.amount)}</h4>"
            f"<ul>{reasons}</ul></div>"
        )
    return f"<div class='cards'>{''.join(parts)}</div>"


def render_bike_panel(context: Optional[OwnerContext], problem: Optional[str]) -> str:
    if context is None:
        return f"<p class='notice'>{esc(problem or 'Geen eigen fiets bekend.')}</p>"

    bike = context.bike
    parts = [f"<h2>{esc(bike.label)}</h2>"]
    specs = " · ".join(f"{esc(k)}: {esc(v)}" for k, v in bike.specs.items())
    parts.append(f"<p class='muted'>Uit de intake: {specs}</p>")

    parts.append("<h3>Taxatie</h3>")
    if context.valuation_problem:
        parts.append(f"<p class='notice'>{esc(context.valuation_problem)}</p>")
        if context.budgets is not None:
            parts.append("<h3>Budget voor de upgrade-finder</h3>")
            parts.append(_budget_block(context.budgets))
    else:
        # §6: nooit één getal zonder band en zonder n.
        n = f"n={context.comp_count}" if context.comp_count is not None else "n onbekend"
        cards = []
        for key in SCENARIO_KEYS:
            valuation = context.valuations.get(key)
            if valuation is None:
                cards.append(
                    f"<div class='card' data-scenario='{key}'><h4>Scenario {key.upper()}</h4>"
                    "<p class='notice'>geen taxatie</p></div>"
                )
                continue
            cards.append(
                f"<div class='card' data-scenario='{key}'>"
                f"<h4>Scenario {key.upper()} — {esc(valuation.scenario)}</h4>"
                f"<div class='band'>{euro(valuation.low_eur)} – <strong>{euro(valuation.mid_eur)}</strong>"
                f" – {euro(valuation.high_eur)}</div>"
                f"<div class='muted'>laag – midden – hoog · {n} comps · vertrouwen: "
                f"{esc(valuation.confidence)}</div></div>"
            )
        parts.append(f"<div class='cards'>{''.join(cards)}</div>")
        if context.budgets is not None:
            parts.append("<h3>Budget voor de upgrade-finder</h3>")
            parts.append(_budget_block(context.budgets))
        for key in SCENARIO_KEYS:
            valuation = context.valuations.get(key)
            if valuation is None:
                continue
            parts.append(
                f"<h3>Bewijslijst scenario {key.upper()}</h3>"
                "<div class='table-wrap'><table class='evidence'><thead><tr>"
                "<th>Soort</th><th>Bedrag</th><th>Onderbouwing</th><th>Link</th>"
                f"</tr></thead><tbody>{_evidence_rows(valuation)}</tbody></table></div>"
            )

    parts.append(
        f"<h3>Kwaliteitsscore (baseline): {context.quality.total:.0f}/100</h3>"
        "<div class='table-wrap'><table class='dimensions'><thead><tr>"
        "<th>Dimensie</th><th>Score</th><th>Waarom</th></tr></thead>"
        f"<tbody>{_dimension_rows(context.quality)}</tbody></table></div>"
    )
    return "\n".join(parts)


# --- Paneel: Upgrade --------------------------------------------------------


def _breakdown(quality: sc.QualityScore) -> str:
    """De uitsplitsing per dimensie, zichtbaar en met de redenen als tooltip —
    §7: een niet-uitlegbaar totaalcijfer wordt niet gebruikt."""
    return " ".join(
        f"<span class='dim' title='{esc(' · '.join(d.reasons))}'>{esc(name)} {d.score:.0f}</span>"
        for name, d in quality.dimensions.items()
    )


def _value_score_cell(score: up.ValueScore) -> tuple[str, str]:
    """(celinhoud, sorteerwaarde). Onbekend is een streepje, geen 0."""
    if score.ratio is None:
        return f"<span title='{esc(score.basis)}'>—</span>", "-1"
    return (
        f"<span title='{esc(score.basis)}'>{val.dutch(score.ratio)}×</span>",
        f"{score.ratio:.4f}",
    )


def render_upgrade_panel(
    context: Optional[OwnerContext],
    problem: Optional[str],
    result: Optional[up.UpgradeResult],
    median_eur: Optional[float],
    segments: Optional[up.SegmentBenchmarks] = None,
) -> str:
    if context is None:
        return f"<p class='notice'>{esc(problem or 'Geen eigen fiets bekend.')}</p>"
    if result is None:
        reason = context.valuation_problem or (
            "geen framemaat (size_cm) in mijn_fiets.md — de maatpoort is hard, dus zonder "
            "doelmaat valt er niets te filteren"
        )
        return f"<p class='notice'>Geen upgrade-finder: {esc(reason)}</p>"

    parts = [
        f"<p class='muted'>Baseline eigen fiets {context.quality.total:.0f}/100 · doelmaat "
        f"{context.target_size_cm:g} cm (±{up.DEFAULT_SIZE_TOLERANCE_CM:g}) · marge "
        f"{up.DEFAULT_SCORE_MARGIN:.0f} punten · gesorteerd op upgrade per euro. "
        "Beweeg over een dimensie of een waardescore voor de onderbouwing.</p>"
    ]
    if context.budgets is not None:
        parts.append(
            f"<p class='muted'>Budget: {euro(context.budgets.rim.amount)} bij velremmen, "
            f"{euro(context.budgets.disc.amount)} bij schijfremmen (zie tab Mijn fiets).</p>"
        )
    if not result.candidates:
        parts.append(
            "<p class='notice'>Geen kandidaten binnen budget en maat. Dat is een uitkomst, "
            "geen fout — het budget is krap, zie mijn_fiets.md.</p>"
        )
    else:
        rows = []
        for position, c in enumerate(result.candidates, start=1):
            l = c.listing
            score_cell, score_sort = _value_score_cell(up.value_score(l, median_eur, segments=segments))
            reasons = " · ".join(c.reasons)
            rows.append(
                f"<tr data-upgraderow='1' data-valuescore='{score_sort}'>"
                f"<td class='num'>{position}</td>"
                f"<td><a href='{esc(l.url)}' target='_blank' rel='noopener'>{esc(l.title)}</a>"
                f"<div class='muted'>{esc(reasons)}</div></td>"
                f"<td class='num'>{c.quality.total:.0f} <span class='muted'>(+{c.gain:.0f})</span></td>"
                f"<td class='num'>{val.dutch(c.points_per_100_eur, 1)}</td>"
                f"<td class='num'>{euro(c.effective.asking_eur)}</td>"
                f"<td class='num' title='{esc(c.effective.basis)}'>{euro(c.effective.amount)}</td>"
                f"<td class='num'>{score_cell}</td>"
                f"<td>{euro(c.budget.amount)} <span class='muted'>{esc(c.budget.route)}</span></td>"
                f"<td>{esc(c.size)}</td>"
                f"<td>{_breakdown(c.quality)}</td>"
                "</tr>"
            )
        parts.append(
            "<div class='table-wrap'><table class='upgrades'><thead><tr>"
            "<th>#</th><th>Titel</th><th>Kwaliteit</th><th>Punt per €100</th>"
            "<th>Vraagprijs</th><th>Effectief</th><th>Waardescore</th><th>Budget</th>"
            "<th>Maat</th><th>Uitsplitsing</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        )

    if result.rejected:
        # Zonder deze lijst is "hij staat er niet bij" niet te onderscheiden van
        # een bug in de maatpoort (zie find_upgrades()).
        items = "".join(
            f"<li>{esc(r.reason)}: <a href='{esc(r.listing.url)}' target='_blank' "
            f"rel='noopener'>{esc(r.listing.title)}</a></li>"
            for r in result.rejected
        )
        parts.append(
            f"<details><summary>Afgevallen ({len(result.rejected)})</summary><ul>{items}</ul></details>"
        )
    return "\n".join(parts)


# --- Paneel: Biedpaneel -----------------------------------------------------


def render_bid_panel(
    rows: Sequence[up.BidRow],
    median_eur: Optional[float],
    segments: Optional[up.SegmentBenchmarks] = None,
) -> str:
    if not rows:
        return "<p class='notice'>Geen biedadvertenties in deze zoekopdracht.</p>"
    body = []
    for row in rows:
        l = row.listing
        score_cell, score_sort = _value_score_cell(up.value_score(l, median_eur, segments=segments))
        headroom = euro(row.headroom_eur) if row.headroom_eur is not None else "onbekend"
        if row.headroom_eur is not None and row.estimate.rough:
            headroom += " <span class='muted'>(grof)</span>"
        deal = f"{l.deal_score:.0f}" if l.deal_score is not None else "—"
        body.append(
            f"<tr data-bidrow='1' data-valuescore='{score_sort}'>"
            f"<td class='num' title='{esc(row.note)}'><strong>{headroom}</strong></td>"
            f"<td class='num' title='{esc(row.entry.basis)}'>{euro(row.entry.amount)}"
            f"<div class='muted'>{esc(row.entry.basis)}</div></td>"
            f"<td class='num' title='{esc(row.estimate.basis)}'>{euro(row.estimate.amount)}</td>"
            f"<td class='num'>{score_cell}</td>"
            f"<td class='num' title='{esc(l.deal_reasons)}'>{deal}</td>"
            f"<td>{esc(crawl.format_bid_info(l)) or '—'}</td>"
            f"<td><a href='{esc(l.url)}' target='_blank' rel='noopener'>{esc(l.title)}</a></td>"
            "</tr>"
        )
    return (
        "<p class='muted'>Gesorteerd op speelruimte: geschatte waarde − wat het kost om "
        "binnen te komen. De waarde komt van het referentiemodel of van vergelijkbare fietsen "
        "(zelfde framemateriaal en groepset); waar niets over de fiets bekend is, alleen de "
        "mediaan van de hele zoekopdracht — die regels staan als <em>grof</em> onder de rest. "
        "Onbekende speelruimte staat onderaan; dat is niet slecht maar onbekend. Waardescore en dealscore zijn twee verschillende maten en staan daarom "
        "in aparte kolommen.</p>"
        "<div class='table-wrap'><table class='bids'><thead><tr>"
        "<th>Speelruimte</th><th>Instap</th><th>Geschatte waarde</th><th>Waardescore</th>"
        "<th>Dealscore</th><th>Bod</th><th>Titel</th>"
        f"</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


# --- Samen -------------------------------------------------------------------


@dataclass(frozen=True)
class Panels:
    bike_html: str
    upgrade_html: str
    upgrade_count: int
    bids_html: str
    bid_row_count: int
    # De kandidaten zelf, voor de samenvatting die koopjes.py op zijn
    # overzichtspagina zet.
    upgrades: tuple = ()


def build_panels(
    listings: Sequence[crawl.Listing],
    median_eur: Optional[float] = None,
    *,
    owner: Optional[OwnerContext] = None,
    owner_problem: Optional[str] = None,
) -> Panels:
    """De drie panelen voor één rapport. Het biedpaneel kan altijd — het heeft
    alleen de advertenties en de mediaan nodig. Mijn fiets en Upgrade hebben
    de eigen fiets nodig en, voor een budget, een taxatie; ontbreekt die, dan
    zegt het paneel waarom in plaats van leeg te blijven."""
    segments = up.segment_benchmarks(listings)
    bid_rows = up.bid_panel(listings, median_eur, segments=segments)

    result: Optional[up.UpgradeResult] = None
    if owner is not None and owner.budgets is not None and owner.target_size_cm is not None:
        result = up.find_upgrades(
            listings,
            baseline=owner.quality.total,
            config=owner.config,
            budgets=owner.budgets,
            target_size_cm=owner.target_size_cm,
            owner_wheels=up.owner_wheels(owner.build),
            owner_already_has=owner.owner_has,
            owner_build=owner.build,
        )

    return Panels(
        bike_html=render_bike_panel(owner, owner_problem),
        upgrade_html=render_upgrade_panel(owner, owner_problem, result, median_eur, segments),
        upgrade_count=len(result.candidates) if result else 0,
        bids_html=render_bid_panel(bid_rows, median_eur, segments),
        bid_row_count=len(bid_rows),
        upgrades=result.candidates if result else (),
    )


# The report's HTML lives in its own file (PLAN_FIETSWAARDE.md §8). It used to
# be a str.format() string in here, where every brace in the CSS and the
# JavaScript had to be doubled — writing an object literal in that was an
# accident waiting to happen. string.Template's $-placeholders leave braces
# alone; the one character to watch in the template is now `$` itself (write
# `$$` for a literal one).
REPORT_TEMPLATE_PATH = Path(__file__).resolve().parent / "report_template.html"


def load_report_template(path: Path = REPORT_TEMPLATE_PATH) -> string.Template:
    """Read the template at render time rather than at import, so a missing
    file only matters to a run that actually writes a report (--no-html runs
    and the tools that import this module don't need it)."""
    try:
        return string.Template(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(
            f"error: HTML-sjabloon {path} ontbreekt — dat bestand hoort naast "
            f"{Path(__file__).name}; zet het terug of draai met --no-html"
        ) from None


def score_css_class(score: Optional[float]) -> str:
    """The pill colour for a score — same tiers as its label."""
    if score is not None:
        for threshold, _, css_class in dealscore.SCORE_LABELS:
            if score >= threshold:
                return css_class
    return "low"


def render_html(
    listings: list[crawl.Listing], query: str, stats: Optional[dict] = None, panels=None
) -> str:
    """`panels` is a Panels (the Biedpaneel / Upgrade / Mijn fiets tabs).
    Left out, only the bid panel is filled — it needs nothing but the
    listings — and the other two say there is no bike to compare against."""
    rows_sorted = dealscore.sort_by_score(listings)

    row_html = []
    for l in rows_sorted:
        price_str = (
            html.escape(l.price_type) if l.price_eur is None
            else f"€{l.price_eur:.2f}" if l.price_eur < 1
            else f"€{l.price_eur:.0f}"
        )
        if l.price_is_bid and l.price_eur is not None:
            price_str += ' <span class="bid-tag">bod</span>'
        badges = ""
        if l.is_new:
            badges += '<span class="badge new">NIEUW</span>'
        if l.is_bargain:
            badges += '<span class="badge bargain">KOOPJE</span>'
        if l.ref_better:
            badges += '<span class="badge better">BETER</span>'
        if l.price_dropped:
            badges += f'<span class="badge dropped">-€{l.price_drop_from - l.price_eur:.0f}</span>'
        if l.bid_open:
            badges += '<span class="badge bid">VRIJ TE BIEDEN</span>'
        price_sort_value = l.price_eur if l.price_eur is not None else -1

        if l.deal_score is not None:
            score_cell = (
                f"<span class='score-pill {score_css_class(l.deal_score)}'>{l.deal_score:.0f}</span>"
                f"<div class='score-label'>{html.escape(l.deal_label)}</div>"
            )
        else:
            score_cell = "<span class='score-pill low'>—</span>"
        score_sort = l.deal_score if l.deal_score is not None else -1
        score_title = html.escape(l.deal_reasons, quote=True)

        bid_str = html.escape(crawl.format_bid_info(l)) or "—"
        # Sort the Bod column by what it would cost to bid right now.
        if l.bid_minimum is not None:
            bid_sort = l.bid_minimum
        elif l.price_is_bid and l.price_eur is not None:
            bid_sort = l.price_eur
        else:
            bid_sort = -1

        ref_str = html.escape(l.ref_label) if l.ref_label else "—"
        ref_sort = l.ref_pct_of_original if l.ref_pct_of_original is not None else 1e9

        if l.ref_pct_of_original is not None:
            ref_price_str = f"€{l.ref_original_price:.0f} ({l.ref_pct_of_original:.0f}% nu)"
        elif l.ref_original_price is not None:
            ref_price_str = f"€{l.ref_original_price:.0f}"
        else:
            ref_price_str = "—" if not l.ref_label else "onbekend"
        if l.ref_market_count > 0:
            ref_price_str += f" · 2e-hands gem. €{l.ref_market_avg:.0f} (n={l.ref_market_count})"
        ref_specs_str = html.escape(l.ref_score) if l.ref_score else (
            html.escape(l.ref_specs) if l.ref_specs else "—"
        )
        if l.ref_specs and l.ref_score:
            ref_specs_str = html.escape(f"{l.ref_specs} — {l.ref_score}")

        pct_median_str = f"{l.pct_of_median:.0f}%" if l.pct_of_median is not None else "—"
        pct_median_sort = l.pct_of_median if l.pct_of_median is not None else 1e9

        row_html.append(
            "<tr data-new='{is_new}' data-bargain='{is_bargain}' data-better='{is_better}' "
            "data-dropped='{is_dropped}' data-topdeal='{is_topdeal}' "
            "data-bidding='{is_bidding}' data-openbid='{is_openbid}' "
            "data-price='{price_sort}' data-title='{title_attr}' "
            "data-frame='{frame_attr}' data-groupset='{groupset_sort}' "
            "data-condition='{condition_attr}' data-city='{city_attr}' data-ref='{ref_sort}' "
            "data-pctmedian='{pct_median_sort}' data-score='{score_sort}' data-bid='{bid_sort}'>"
            "<td>{badges}</td>"
            "<td class='score' title='{score_title}'>{score_cell}</td>"
            "<td class='price'>{price}</td>"
            "<td>{bid}</td>"
            "<td>{pct_median}</td>"
            "<td><a href='{url}' target='_blank' rel='noopener'>{title}</a></td>"
            "<td>{frame}</td>"
            "<td>{groupset}</td>"
            "<td>{condition}</td>"
            "<td>{city}</td>"
            "<td>{ref}</td>"
            "<td>{ref_price}</td>"
            "<td>{ref_specs}</td>"
            "</tr>".format(
                is_new="1" if l.is_new else "0",
                is_bargain="1" if l.is_bargain else "0",
                is_better="1" if l.ref_better else "0",
                is_dropped="1" if l.price_dropped else "0",
                is_topdeal="1" if (l.deal_score is not None and l.deal_score >= dealscore.TOP_DEAL_SCORE) else "0",
                is_bidding="1" if l.price_is_bid else "0",
                is_openbid="1" if l.bid_open else "0",
                price_sort=price_sort_value,
                score_sort=score_sort,
                score_title=score_title,
                score_cell=score_cell,
                bid=bid_str,
                bid_sort=bid_sort,
                title_attr=html.escape(l.title, quote=True),
                frame_attr=html.escape(l.frame_height, quote=True),
                groupset_sort=l.groupset_tier if l.groupset_tier is not None else -1,
                condition_attr=html.escape(l.condition, quote=True),
                city_attr=html.escape(l.city, quote=True),
                ref_sort=ref_sort,
                pct_median_sort=pct_median_sort,
                badges=badges,
                frame=html.escape(l.frame_height) or "—",
                groupset=html.escape(l.groupset) or "—",
                price=price_str,
                pct_median=pct_median_str,
                url=html.escape(l.url, quote=True),
                title=html.escape(l.title),
                condition=html.escape(l.condition),
                city=html.escape(l.city),
                ref=ref_str,
                ref_price=ref_price_str,
                ref_specs=ref_specs_str,
            )
        )

    if stats is None:
        stats = dealscore.price_stats(listings)
    price_stats_str = (
        f" · gemiddeld €{stats['mean']:.0f} · mediaan €{stats['median']:.0f}"
        if stats["count"] >= 2
        else ""
    )
    if panels is None:
        panels = build_panels(
            listings, stats.get("median"),
            owner_problem="Geen eigen fiets meegegeven aan dit rapport.",
        )

    sleeper_count, sleeper_panel = sleepers.render_panel(listings)
    computer_count, computer_panel = computers.render_panel(listings)

    # substitute(), not safe_substitute(): a placeholder in the template that
    # nobody fills in should fail here, not end up as literal text in the page.
    return load_report_template().substitute(
        query=html.escape(query),
        generated=datetime.now().strftime("%d-%m-%Y %H:%M"),
        total=len(listings),
        new_count=sum(1 for l in listings if l.is_new),
        bargain_count=sum(1 for l in listings if l.is_bargain),
        better_count=sum(1 for l in listings if l.ref_better),
        dropped_count=sum(1 for l in listings if l.price_dropped),
        topdeal_count=sum(
            1 for l in listings if l.deal_score is not None and l.deal_score >= dealscore.TOP_DEAL_SCORE
        ),
        bid_count=len(crawl.bid_listings(listings)),
        open_bid_count=len(crawl.open_bid_listings(listings)),
        price_stats_str=price_stats_str,
        rows="\n".join(row_html),
        bidpanel_count=panels.bid_row_count,
        upgrade_count=panels.upgrade_count,
        bid_panel=panels.bids_html,
        upgrade_panel=panels.upgrade_html,
        bike_panel=panels.bike_html,
        sleeper_count=sleeper_count,
        sleeper_panel=sleeper_panel,
        # Only when this run has bike computers: on a racefiets run the tab
        # would always read "(0)". The full picture is dashboard.html.
        computer_tab=(
            f'  <button data-panel="computers">Fietscomputers ({computer_count})</button>\n'
            if computer_count else ""
        ),
        computer_panel=computer_panel,
    )


def write_html(
    listings: list[crawl.Listing], path: str, query: str, stats: Optional[dict] = None, panels=None
) -> None:
    Path(path).write_text(
        render_html(listings, query, stats=stats, panels=panels), encoding="utf-8"
    )
