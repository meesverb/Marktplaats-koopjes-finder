"""Weergaven en likes (bewaard): hoeveel mensen een advertentie bekijken en
bewaren, hoe dat groeit, en wat ermee samenhangt.

Waar het vandaan komt: de advertentiepagina zelf (`stats` in
window.__CONFIG__: viewCount, favoritedCount en `since`, het moment van
plaatsen). De zoekresultaten hebben het niet (gecontroleerd 29-09-2026),
dus elke meting is één verzoek. Daarom meet een ronde met mate:

- **meeliften**: waar de ronde of de knop controleer de pagina toch al
  ophaalt (biedopvraging, volledige omschrijving), gaat de meting mee
  (racefiets_jev.page_stats()); geen extra verzoek.
- **gericht**: je eigen advertenties die te koop staan (/flips, met
  advertentielink), elke 6 uur; favorieten en advertenties waarop je een
  lopend bod hebt, elke 12 uur.
- **steekproef**: van de nieuwe advertenties in de drie markten (racefietsen,
  fietscomputers, sporthorloges) een vaste 1 op SAMPLE_EVERY, gemeten op een
  leeftijd van 1, 3 en 7 dagen. Vast op het advertentienummer, zodat
  dezelfde advertentie alle drie de keren meedoet en je het verloop ziet.

Per ronde nooit meer dan `views_budget` verzoeken (schedule.json, per
tijdslot), met minstens de gewone wachttijd ertussen (recheck._get()).
Gericht gaat voor; de steekproef krijgt wat overblijft.

Wat het zegt, in de tab Patronen: hoe weergaven en likes groeien met de
leeftijd, of veel likes in de eerste dagen samengaan met snel verdwijnen
(verdwenen is niet verkocht, zie patterns.py), en wat samenhangt met meer
weergaven: een Dagtopper, de prijs ten opzichte van de rest, de dag en het
uur van plaatsen, een prijsverlaging. Samenhang, geen oorzaak: een
Dagtopper staat vaak bij een verkoper die ook betere foto's maakt.

Alleen lezen bij Marktplaats; bieden of reageren doet de eigenaar zelf.
"""
from __future__ import annotations

import re
import sqlite3
import statistics
import sys
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

import db
import racefiets_jev as mp

# 1 op zoveel nieuwe advertenties doet mee aan de steekproef. Met ~300
# nieuwe per dag in de drie markten samen (28/29-09-2026) zijn dat er ~30,
# drie metingen elk: ~90 verzoeken per dag, verdeeld over de rondes.
SAMPLE_EVERY = 10
SAMPLE_AGES_DAYS = (1, 3, 7)
OWN_EVERY_HOURS = 6
WATCHED_EVERY_HOURS = 12
# Waar de steekproef uit komt: de categorieën van de drie markten.
SAMPLE_CATEGORIES = ("fietsen-racefietsen", "fietsaccessoires-fietscomputers",
                     "sporthorloges", "smartwatches", "activity-trackers")
ITEM_ID_RE = re.compile(r"/(m\d{6,})")
# Onder zoveel advertenties per groep zegt een mediaan niets; dan "te weinig".
MIN_GROUP = 10
WEEKDAYS = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")


def item_id_from_url(url: str) -> Optional[str]:
    found = ITEM_ID_RE.search(url or "")
    return found.group(1) if found else None


def in_sample(item_id: str) -> bool:
    return zlib.crc32(item_id.encode("utf-8")) % SAMPLE_EVERY == 0


def _time(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Target:
    item_id: str
    url: str
    why: str  # "eigen advertentie", "favoriet", "bod", "steekproef 3 d"


def plan(conn: sqlite3.Connection, budget: int, now: Optional[datetime] = None) -> list[Target]:
    """Wat deze ronde meet, in volgorde, hooguit `budget`."""
    if budget <= 0 or not db._has_table(conn, "listing_stats"):
        return []
    now = now or datetime.now(timezone.utc)
    last: dict[str, datetime] = {}
    measured: dict[str, list[datetime]] = {}
    for item_id, observed in conn.execute("SELECT item_id, observed_at FROM listing_stats"):
        t = _time(observed)
        if t is None:
            continue
        measured.setdefault(item_id, []).append(t)
        if item_id not in last or t > last[item_id]:
            last[item_id] = t

    def due(item_id: str, hours: float) -> bool:
        return item_id not in last or now - last[item_id] >= timedelta(hours=hours)

    targets: list[Target] = []
    seen: set[str] = set()

    def add(item_id: Optional[str], url: str, why: str) -> None:
        if item_id and url and item_id not in seen:
            seen.add(item_id)
            targets.append(Target(item_id, url, why))

    # Eigen advertenties: een flip die te koop staat, met een Marktplaats-link.
    if db._has_table(conn, "flip"):
        for url, in conn.execute(
                "SELECT f.sale_url FROM flip f JOIN trade t ON t.id = f.trade_id "
                "WHERE f.stage = 'te_koop' AND t.sold_at IS NULL AND f.sale_url LIKE '%marktplaats.nl%'"):
            item_id = item_id_from_url(url)
            if item_id and due(item_id, OWN_EVERY_HOURS):
                add(item_id, url.split("?")[0], "eigen advertentie")
    # Favorieten en lopende eigen biedingen, zolang ze online zijn.
    watched = []
    if db._has_table(conn, "listing_mark"):
        watched += [(r[0], r[1], "favoriet") for r in conn.execute(
            "SELECT l.item_id, l.url FROM listing_mark m JOIN listing l ON l.item_id = m.item_id "
            "WHERE m.mark = 'favoriet' AND l.disappeared_at IS NULL")]
    watched += [(r[0], r[1], "bod") for r in conn.execute(
        "SELECT l.item_id, l.url FROM own_bid b JOIN listing l ON l.item_id = b.item_id "
        "WHERE b.status IN ('open', 'overboden') AND l.disappeared_at IS NULL "
        "AND b.id = (SELECT MAX(id) FROM own_bid WHERE item_id = b.item_id)")]
    for item_id, url, why in watched:
        if due(item_id, WATCHED_EVERY_HOURS):
            add(item_id, url, why)
    # De steekproef: nieuwe advertenties op leeftijd 1, 3 en 7 dagen.
    oldest = (now - timedelta(days=max(SAMPLE_AGES_DAYS) + 2)).isoformat(timespec="seconds")
    where = " OR ".join("url LIKE ?" for _ in SAMPLE_CATEGORIES)
    rows = conn.execute(
        f"SELECT item_id, url, first_seen FROM listing WHERE disappeared_at IS NULL AND first_seen >= ? "
        f"AND ({where}) ORDER BY first_seen",
        (oldest, *(f"%/{c}/%" for c in SAMPLE_CATEGORIES))).fetchall()
    for item_id, url, first_seen in rows:
        if not in_sample(item_id):
            continue
        start = _time(first_seen)
        if start is None:
            continue
        age = now - start
        for days in sorted(SAMPLE_AGES_DAYS, reverse=True):
            if age < timedelta(days=days):
                continue
            # Al gemeten in dit leeftijdsvak (vanaf `days` dagen)? Dan niets.
            if not any(t - start >= timedelta(days=days) for t in measured.get(item_id, ())):
                add(item_id, url, f"steekproef {days} d")
            break
    return targets[:budget]


def measure(conn: sqlite3.Connection, target: Target, session=None, now: Optional[str] = None) -> str:
    """Eén meting: de pagina ophalen en de weergaven en likes vastleggen.
    Geeft kort terug wat er gebeurde ("158× bekeken, 4× bewaard", "weg")."""
    import recheck as rc

    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        resp = rc._get(session or rc.make_session(), target.url)
    except requests.RequestException as exc:
        return f"niet opgehaald ({exc})"
    if resp.status_code in rc.GONE_STATUSES:
        db.record_listing_gone(conn, target.item_id, now)
        return "weg"
    if resp.status_code >= 400:
        return f"niet opgehaald (HTTP {resp.status_code})"
    try:
        page = mp.listing_page_data(resp.text)
    except mp.ListingPageError as exc:
        return f"pagina niet te lezen ({exc}) — Marktplaats heeft waarschijnlijk zijn paginastructuur gewijzigd"
    stats = mp.page_stats(page)
    if not stats:
        return "geen weergaven op de pagina"
    price, _ = mp.price_from_info((page or {}).get("priceInfo") or {})
    db.record_stats(conn, target.item_id, now, stats, price_eur=price, source=target.why)
    return f"{stats.get('views')}× bekeken, {stats.get('favorites')}× bewaard"


def measure_round(db_path, budget: int, session=None, log=print) -> int:
    """Wat een ronde doet (koopjes.py): plannen, meten, loggen. Geeft het
    aantal verzoeken terug. Houdt op bij drie mislukte verzoeken achter
    elkaar: dan is er iets mis met de verbinding of met Marktplaats."""
    if budget <= 0 or not Path(db_path).exists():
        return 0
    conn = db.connect(str(db_path))
    try:
        targets = plan(conn, budget)
        if not targets:
            return 0
        log(f"Weergaven en likes meten: {len(targets)} advertentie(s) (max {budget} per ronde)")
        failures = done = 0
        for target in targets:
            result = measure(conn, target, session)
            done += 1
            log(f"  {target.item_id} ({target.why}): {result}")
            failures = failures + 1 if result.startswith(("niet opgehaald", "pagina niet")) else 0
            if failures >= 3:
                log("  gestopt: drie keer achter elkaar niet gelukt")
                break
        return done
    finally:
        conn.close()


# --- Tonen per advertentie -------------------------------------------------------


@dataclass(frozen=True)
class Latest:
    views: Optional[int]
    favorites: Optional[int]
    observed_at: str
    since: Optional[str]
    fav_delta: Optional[int] = None  # likes erbij sinds de meting daarvoor
    views_delta: Optional[int] = None
    previous_at: Optional[str] = None

    @property
    def label(self) -> str:
        parts = []
        if self.views is not None:
            parts.append(f"{self.views}× bekeken")
        if self.favorites is not None:
            parts.append(f"{self.favorites}× bewaard")
        return " · ".join(parts)


def latest(observations: list[dict]) -> Optional[Latest]:
    if not observations:
        return None
    last = observations[-1]
    prev = observations[-2] if len(observations) > 1 else None

    def delta(key):
        if prev is None or last.get(key) is None or prev.get(key) is None:
            return None
        return last[key] - prev[key]

    return Latest(last.get("views"), last.get("favorites"), last.get("observed_at") or "",
                  last.get("online_since"), delta("favorites"), delta("views"),
                  prev.get("observed_at") if prev else None)


def load_latest(db_path) -> dict[str, Latest]:
    """{item_id: laatste meting}, alleen lezen."""
    if not db_path or not Path(db_path).exists():
        return {}
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        found = db.list_stats(conn)
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    return {k: v for k, v in ((k, latest(obs)) for k, obs in found.items()) if v is not None}


def sparkline(values: list, width: int = 120, height: int = 28, color: str = "currentColor") -> str:
    """Een lijntje als inline SVG, voor /flips. Geen as of labels: het getal
    staat ernaast."""
    points = [v for v in values if v is not None]
    if len(points) < 2:
        return ""
    low, high = min(points), max(points)
    span = (high - low) or 1
    step = width / (len(points) - 1)
    coords = " ".join(f"{i * step:.1f},{height - 2 - (v - low) / span * (height - 4):.1f}"
                      for i, v in enumerate(points))
    return (f"<svg class='spark' width='{width}' height='{height}' viewBox='0 0 {width} {height}' "
            f"aria-hidden='true'><polyline fill='none' stroke='{color}' stroke-width='1.6' "
            f"points='{coords}'/></svg>")


# --- Patronen ----------------------------------------------------------------------


@dataclass
class Group:
    label: str
    n: int
    median: Optional[float]  # weergaven per dag (of wat de tabel zegt)
    extra: str = ""


@dataclass
class ViewPatterns:
    measurements: int = 0
    listings: int = 0
    growth: list = field(default_factory=list)  # (leeftijd, n, mediaan weergaven, mediaan likes)
    speed: list = field(default_factory=list)  # Group: likes per dag -> verdwenen binnen 7 dagen
    promotion: list = field(default_factory=list)  # Group
    price: list = field(default_factory=list)  # Group
    weekday: list = field(default_factory=list)  # Group
    hour: list = field(default_factory=list)  # Group
    drop: Optional[tuple] = None  # (n, mediaan weergaven/dag vóór, erna)


@dataclass
class _Obs:
    item_id: str
    at: datetime
    views: Optional[int]
    favorites: Optional[int]
    since: Optional[datetime]
    price: Optional[float]


def _median(values) -> Optional[float]:
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def compute(obs_by_item: dict, listings: dict, places: dict, now: Optional[datetime] = None) -> ViewPatterns:
    """`obs_by_item`: {item_id: [_Obs, oudste eerst]}; `listings`: {item_id:
    (first_seen, disappeared_at, first_price)}; `places`: {item_id:
    (lat, lon, promotion, traits)}. Zuiver, zonder database."""
    now = now or datetime.now(timezone.utc)
    p = ViewPatterns(measurements=sum(len(v) for v in obs_by_item.values()), listings=len(obs_by_item))

    def start_of(item_id: str, o: _Obs) -> Optional[datetime]:
        return o.since or _time((listings.get(item_id) or (None,))[0])

    def per_day(item_id: str, o: _Obs, key: str) -> Optional[float]:
        start, value = start_of(item_id, o), getattr(o, key)
        if start is None or value is None:
            return None
        days = (o.at - start).total_seconds() / 86400
        return value / days if days >= 0.5 else None

    # Groei: per leeftijdsvak de mediaan van wat er dan staat.
    buckets = ((0, 1, "< 1 dag"), (1, 3, "1-3 dagen"), (3, 7, "3-7 dagen"), (7, 14, "7-14 dagen"),
               (14, 10_000, "2 weken of ouder"))
    for low, high, label in buckets:
        views, favs = [], []
        for item_id, obs in obs_by_item.items():
            for o in obs:
                start = start_of(item_id, o)
                if start is None:
                    continue
                age = (o.at - start).total_seconds() / 86400
                if low <= age < high:
                    views.append(o.views)
                    favs.append(o.favorites)
                    break
        if views:
            p.growth.append((label, len(views), _median(views), _median(favs)))

    # Eén getal per advertentie: de eerste meting van minstens een halve dag oud.
    first: dict[str, _Obs] = {}
    for item_id, obs in obs_by_item.items():
        for o in obs:
            if per_day(item_id, o, "views") is not None:
                first[item_id] = o
                break

    # Snelheid: likes per dag, in drie even grote groepen, tegen "binnen 7
    # dagen verdwenen" — alleen advertenties waarvan de afloop bekend is.
    known = []
    for item_id, o in first.items():
        start = start_of(item_id, o)
        rate = per_day(item_id, o, "favorites")
        gone = _time((listings.get(item_id) or (None, None))[1])
        if start is None or rate is None:
            continue
        if gone is not None:
            known.append((rate, (gone - start).days <= 7, (gone - start).days))
        elif now - start > timedelta(days=7):
            known.append((rate, False, None))
    if len(known) >= 3 * MIN_GROUP:
        known.sort(key=lambda k: k[0])
        third = len(known) // 3
        for label, part in (("weinig likes", known[:third]), ("gemiddeld", known[third:2 * third]),
                            ("veel likes", known[2 * third:])):
            quick = sum(1 for k in part if k[1])
            days = _median(k[2] for k in part if k[2] is not None)
            p.speed.append(Group(f"{label} (≤{part[-1][0]:.1f}/dag)".replace(".", ","), len(part),
                                 quick / len(part), "" if days is None else f"mediaan {days:.0f} dagen online"))

    rates = {item_id: per_day(item_id, o, "views") for item_id, o in first.items()}

    def grouped(key_of) -> list:
        groups: dict[str, list] = {}
        for item_id, rate in rates.items():
            key = key_of(item_id)
            if key is not None:
                groups.setdefault(key, []).append(rate)
        return [Group(k, len(v), _median(v)) for k, v in groups.items()]

    p.promotion = sorted(grouped(lambda i: "Dagtopper" if (places.get(i) or (None,) * 4)[2] else "geen promotie"),
                         key=lambda g: g.label)
    prices = sorted(o.price for o in first.values() if o.price)
    if len(prices) >= 3 * MIN_GROUP:
        cut1, cut2 = prices[len(prices) // 3], prices[2 * len(prices) // 3]

        def band(item_id):
            price = first[item_id].price
            if not price:
                return None
            return (f"goedkoopste derde (< €{cut1:.0f})" if price < cut1 else
                    f"middelste derde" if price < cut2 else f"duurste derde (≥ €{cut2:.0f})")
        p.price = sorted(grouped(band), key=lambda g: (not g.label.startswith("goedkoop"), g.label.startswith("duur")))

    def placed(item_id):
        return first[item_id].since
    by_day = grouped(lambda i: WEEKDAYS[placed(i).astimezone().weekday()] if placed(i) else None)
    p.weekday = sorted(by_day, key=lambda g: WEEKDAYS.index(g.label))
    parts = (("nacht (0-6)", 0, 6), ("ochtend (6-12)", 6, 12), ("middag (12-18)", 12, 18), ("avond (18-24)", 18, 24))

    def part_of_day(item_id):
        t = placed(item_id)
        if t is None:
            return None
        hour = t.astimezone().hour
        return next(label for label, a, b in parts if a <= hour < b)
    by_hour = grouped(part_of_day)
    p.hour = sorted(by_hour, key=lambda g: [x[0] for x in parts].index(g.label))

    # Prijsverlaging: weergaven per dag tussen twee metingen, vóór en na.
    before, after = [], []
    for item_id, obs in obs_by_item.items():
        for a, b, c in zip(obs, obs[1:], obs[2:]):
            if a.price and b.price and c.price and a.price == b.price and c.price < b.price:
                span1 = (b.at - a.at).total_seconds() / 86400
                span2 = (c.at - b.at).total_seconds() / 86400
                if span1 >= 0.25 and span2 >= 0.25 and None not in (a.views, b.views, c.views):
                    before.append((b.views - a.views) / span1)
                    after.append((c.views - b.views) / span2)
                break
    if before:
        p.drop = (len(before), _median(before), _median(after))
    return p


def load_patterns(db_path, categories: tuple) -> ViewPatterns:
    """De patronen voor één markt (de categorieën uit de advertentie-URL),
    alleen lezen. Eigen advertenties tellen niet mee: die zijn de proef, niet
    de markt."""
    if not db_path or not Path(db_path).exists():
        return ViewPatterns()
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if not db._has_table(conn, "listing_stats"):
            return ViewPatterns()
        where = " OR ".join("l.url LIKE ?" for _ in categories)
        args = tuple(f"%/{c}/%" for c in categories)
        listings = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
            f"SELECT l.item_id, l.first_seen, l.disappeared_at, l.price_eur FROM listing l WHERE {where}", args)}
        obs: dict[str, list] = {}
        for r in conn.execute(
                "SELECT s.item_id, s.observed_at, s.views, s.favorites, s.online_since, s.price_eur, s.source "
                "FROM listing_stats s ORDER BY s.item_id, s.observed_at"):
            if r[0] not in listings or r[6] == "eigen advertentie":
                continue
            at = _time(r[1])
            if at is not None:
                obs.setdefault(r[0], []).append(_Obs(r[0], at, r[2], r[3], _time(r[4]), r[5]))
        places = db.list_places(conn)
    except sqlite3.Error:
        return ViewPatterns()
    finally:
        conn.close()
    return compute(obs, listings, places)


def patterns_html(p: ViewPatterns, items: str = "advertenties") -> str:
    """Het blok "Weergaven en likes" voor de tab Patronen (dashboards en
    /racefietsen). Zonder database-toegang; alleen `p`."""
    import html

    esc = html.escape
    num = lambda x, d=0: "—" if x is None else f"{x:.{d}f}".replace(".", ",")
    out = ["<h3>Weergaven en likes</h3>",
           "<p class='explain'>Van de advertentiepagina zelf (de zoekresultaten hebben ze niet), dus gemeten met "
           "mate: je eigen advertenties, favorieten en biedingen, en een vaste steekproef van 1 op "
           f"{SAMPLE_EVERY} nieuwe {esc(items)} op 1, 3 en 7 dagen (<code>views_budget</code> per ronde in "
           "schedule.json). Plus wat de ronde toch al ophaalt (biedopvragingen, controleer). "
           "<strong>Samenhang is geen oorzaak</strong>, en verdwenen is niet verkocht.</p>"]
    if not p.measurements:
        out.append("<p class='empty'>Nog geen metingen. Die komen vanzelf met de rondes (views_budget in "
                   "schedule.json), of met de hand: <code>python views.py meet 10</code>.</p>")
        return "\n".join(out)
    out.append(f"<p class='sub'>{p.measurements} metingen van {p.listings} {esc(items)}. Een groep met minder "
               f"dan {MIN_GROUP} advertenties zegt nog weinig.</p>")

    def table(head: list, rows: list) -> str:
        ths = "".join(f"<th{' class=num' if i else ''}>{esc(h)}</th>" for i, h in enumerate(head))
        return (f"<div class='table-wrap'><table><thead><tr>{ths}</tr></thead><tbody>{''.join(rows)}"
                "</tbody></table></div>")

    if p.growth:
        out.append("<h3>Hoe het groeit</h3><p class='explain'>Mediaan van wat een advertentie op die leeftijd "
                   "heeft (leeftijd vanaf het plaatsen, volgens Marktplaats).</p>")
        out.append(table(["Leeftijd", "n", "Bekeken", "Bewaard"], [
            f"<tr><td>{esc(label)}</td><td class='num'>{n}</td><td class='num'>{num(v)}</td>"
            f"<td class='num'>{num(f, 1)}</td></tr>" for label, n, v, f in p.growth]))
    out.append("<h3>Likes en hoe snel iets weg is</h3>")
    if p.speed:
        out.append("<p class='explain'>Likes per dag bij de eerste meting, in drie even grote groepen, tegen het "
                   "deel dat binnen 7 dagen na plaatsen verdween. Alleen advertenties waarvan dat al vaststaat.</p>")
        out.append(table(["Groep", "n", "Weg binnen 7 dagen", ""], [
            f"<tr><td>{esc(g.label)}</td><td class='num'>{g.n}</td><td class='num'>"
            f"{'—' if g.median is None else f'{g.median:.0%}'}</td><td class='sub'>{esc(g.extra)}</td></tr>"
            for g in p.speed]))
    else:
        out.append(f"<p class='empty'>Nog te weinig advertenties waarvan de afloop bekend is (minstens "
                   f"{3 * MIN_GROUP} nodig).</p>")

    def groups(title: str, explain: str, rows: list) -> None:
        if not rows:
            return
        out.append(f"<h3>{esc(title)}</h3><p class='explain'>{explain}</p>")
        out.append(table(["", "n", "Bekeken per dag (mediaan)"], [
            f"<tr><td>{esc(g.label)}{'' if g.n >= MIN_GROUP else ' <span class=sub>(te weinig)</span>'}</td>"
            f"<td class='num'>{g.n}</td><td class='num'>{num(g.median, 1)}</td></tr>" for g in rows]))

    groups("Promotie", "Dagtopper of andere betaalde plek (uit de zoekresultaten), tegen weergaven per dag.",
           p.promotion)
    groups("Prijs", "Duurder of goedkoper dan de rest van de gemeten advertenties.", p.price)
    groups("Dag van plaatsen", "Het moment van plaatsen komt van de advertentiepagina (<code>since</code>).",
           p.weekday)
    groups("Tijd van plaatsen", "Zelfde bron, per dagdeel.", p.hour)
    if p.drop:
        n, before, after = p.drop
        out.append("<h3>Na een prijsverlaging</h3><p class='explain'>Weergaven per dag tussen de twee metingen "
                   "vóór de verlaging, en tussen de laatste daarvan en de eerste meting erna, bij "
                   f"{n} advertentie(s) die de prijs verlaagden terwijl ze gemeten werden.</p>"
                   f"<p>Vóór: <strong>{num(before, 1)}</strong> per dag · erna: <strong>{num(after, 1)}</strong> "
                   "per dag</p>")
    return "\n".join(out)


def main(argv=None) -> int:
    """`python views.py meet 20`: een ronde metingen met de hand (hooguit 20)."""
    import argparse

    parser = argparse.ArgumentParser(description="Weergaven en likes meten (zie de uitleg bovenin views.py).")
    parser.add_argument("actie", choices=["meet", "plan"])
    parser.add_argument("aantal", type=int, nargs="?", default=10)
    parser.add_argument("--db", default="koopjes.db")
    args = parser.parse_args(argv)
    if not Path(args.db).exists():
        print(f"Database {args.db} bestaat niet.", file=sys.stderr)
        return 1
    if args.actie == "plan":
        conn = db.connect(args.db)
        try:
            for t in plan(conn, args.aantal):
                print(f"{t.item_id}  {t.why:20}  {t.url}")
        finally:
            conn.close()
        return 0
    measure_round(args.db, args.aantal)
    return 0


if __name__ == "__main__":
    sys.exit(main())
