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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional, Sequence

import db
import racefiets_jev as mp
import scoring as sc
import upgrade as up
import valuation as val

# De gewichten zijn code-configuratie, geen gebruikersdata: ze horen naast het
# script te staan, en een rapport dat vanuit een andere map gedraaid wordt
# moet ze net zo goed vinden.
SCORING_CONFIG_PATH = Path(__file__).resolve().parent / sc.DEFAULT_CONFIG_PATH

SCENARIO_KEYS = ("a", "b")


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def euro(amount: Optional[float]) -> str:
    return f"€{amount:.0f}" if amount is not None else "—"


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
) -> tuple[Optional[OwnerContext], Optional[str]]:
    """De eigen fiets uit `mijn_fiets.md`, gescoord en — als er een database
    is — getaxeerd. Geeft (context, None) of (None, reden).

    `db_path` None betekent: geen database (--no-db). Een pad dat niet bestaat
    wordt niet aangemaakt; db.connect() zou dat wel doen, en een lege database
    als bijwerking van een rapport is verwarrend."""
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

    build = sc.build_from_owner_specs(bike.specs, label=bike.label)
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
    if not Path(db_path).exists():
        return _without_valuation(context, f"{db_path} bestaat nog niet, dus geen comps om op te taxeren"), None

    conn = db.connect(db_path)
    try:
        comps = val.fetch_comp_candidates(conn)
    finally:
        conn.close()

    subject = val.subject_from_owner_bike(bike)
    comp_set = val.select_comps(subject, comps)
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
        )
        if valuation is not None:
            valuations[key] = valuation

    if "b" not in valuations:
        return _without_valuation(
            context,
            f"geen vergelijkbare advertenties in {db_path} ({len(comps)} advertenties met een "
            "vraagprijs in het meetvenster). Crawl eerst met --query op dit model.",
        ), None

    budgets = up.budgets_from_valuation(
        valuations["b"].mid_eur,
        wheelset_value_eur=context.wheelset.market_value,
        extra_budget_eur=context.extra_budget_eur,
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
            score_cell, score_sort = _value_score_cell(up.value_score(l, median_eur))
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


def render_bid_panel(rows: Sequence[up.BidRow], median_eur: Optional[float]) -> str:
    if not rows:
        return "<p class='notice'>Geen biedadvertenties in deze zoekopdracht.</p>"
    body = []
    for row in rows:
        l = row.listing
        score_cell, score_sort = _value_score_cell(up.value_score(l, median_eur))
        headroom = euro(row.headroom_eur) if row.headroom_eur is not None else "onbekend"
        deal = f"{l.deal_score:.0f}" if l.deal_score is not None else "—"
        body.append(
            f"<tr data-bidrow='1' data-valuescore='{score_sort}'>"
            f"<td class='num' title='{esc(row.note)}'><strong>{headroom}</strong></td>"
            f"<td class='num' title='{esc(row.entry.basis)}'>{euro(row.entry.amount)}"
            f"<div class='muted'>{esc(row.entry.basis)}</div></td>"
            f"<td class='num' title='{esc(row.estimate.basis)}'>{euro(row.estimate.amount)}</td>"
            f"<td class='num'>{score_cell}</td>"
            f"<td class='num' title='{esc(l.deal_reasons)}'>{deal}</td>"
            f"<td>{esc(mp.format_bid_info(l)) or '—'}</td>"
            f"<td><a href='{esc(l.url)}' target='_blank' rel='noopener'>{esc(l.title)}</a></td>"
            "</tr>"
        )
    return (
        "<p class='muted'>Gesorteerd op speelruimte: geschatte waarde − wat het kost om "
        "binnen te komen. Onbekende speelruimte staat onderaan; dat is niet slecht maar "
        "onbekend. Waardescore en dealscore zijn twee verschillende maten en staan daarom "
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


def build_panels(
    listings: Sequence[mp.Listing],
    median_eur: Optional[float] = None,
    *,
    owner: Optional[OwnerContext] = None,
    owner_problem: Optional[str] = None,
) -> Panels:
    """De drie panelen voor één rapport. Het biedpaneel kan altijd — het heeft
    alleen de advertenties en de mediaan nodig. Mijn fiets en Upgrade hebben
    de eigen fiets nodig en, voor een budget, een taxatie; ontbreekt die, dan
    zegt het paneel waarom in plaats van leeg te blijven."""
    bid_rows = up.bid_panel(listings, median_eur)

    result: Optional[up.UpgradeResult] = None
    if owner is not None and owner.budgets is not None and owner.target_size_cm is not None:
        result = up.find_upgrades(
            listings,
            baseline=owner.quality.total,
            config=owner.config,
            budgets=owner.budgets,
            target_size_cm=owner.target_size_cm,
            owner_wheels=(owner.build.wheel_material, owner.build.wheel_branded),
            owner_already_has=owner.owner_has,
        )

    return Panels(
        bike_html=render_bike_panel(owner, owner_problem),
        upgrade_html=render_upgrade_panel(owner, owner_problem, result, median_eur),
        upgrade_count=len(result.candidates) if result else 0,
        bids_html=render_bid_panel(bid_rows, median_eur),
        bid_row_count=len(bid_rows),
    )
