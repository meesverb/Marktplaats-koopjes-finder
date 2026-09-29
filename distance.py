"""Afstand van elke advertentie tot de eigen postcode, hemelsbreed in km: voor
het schuifje "max. afstand" en sorteren op afstand in de dashboards en op
/racefietsen. Een racefiets haal je op; een fietscomputer of horloge scheelt
verzendkosten als hij om de hoek staat.

Hoe het werkt, zonder externe dienst:

- De zoekresultaten van Marktplaats geven bij elke advertentie de breedte-
  en lengtegraad van de verkoper (`location.latitude/longitude`, ook zonder
  postcode in het verzoek; gecontroleerd 29-09-2026). Die staan in
  `listing_place` (db.py, migratie 18). Een verkoper die alleen het land
  opgaf, komt met 0, 0 en `onCountryLevel` en heeft dus geen plek.
- De eigen plek komt uit de postcode die je op de pagina invult. Marktplaats
  zegt niet waar een postcode ligt, maar wel hoe ver elke advertentie ervan
  af ligt: met `postcode` in het zoekverzoek krijgt elke advertentie
  `distanceMeters`, afgerond op hele km. Eén zoekverzoek van 100
  advertenties door heel Nederland, en dan het punt zoeken waarvan die
  afstanden kloppen (kleinste kwadraten). Op 29-09-2026 met 3511AB: 75
  bruikbare afstanden, gemiddeld 0,3 km afwijking. `distanceMeters` 0
  betekent daar onbekend (sommige winkels), niet "om de hoek"; die tellen
  niet mee.
- Daarna rekent alles hier, zonder verzoeken: een andere postcode geldt
  meteen voor elke advertentie in de database.

Een advertentie van vóór migratie 18 heeft nog geen plek. Tot een ronde hem
weer ziet, krijgt hij die van andere advertenties in dezelfde plaats
(`ca.` ervoor): de plaatsnaam staat er wel bij.

Het is hemelsbreed. Over de weg is het meestal een stuk verder; de afstand
telt nergens in een score mee, hij filtert en sorteert alleen.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests

import db
import racefiets_jev as mp

EARTH_RADIUS_KM = 6371.0088
POSTCODE_RE = re.compile(r"^\s*(\d{4})\s*([A-Za-z]{2})?\s*$")
# Waar de eigen plek staat (tabel `setting`).
SETTING_POSTCODE = "postcode"
SETTING_LATITUDE = "postcode_latitude"
SETTING_LONGITUDE = "postcode_longitude"
# Het zoekverzoek om de postcode te plaatsen: een woord met aanbod in heel
# het land, zodat de afstanden alle kanten op wijzen.
LOCATE_QUERY = "fiets"
LOCATE_LIMIT = 100
# Minder bruikbare afstanden, of een slechtere fit dan dit, en de plek is
# niet te vertrouwen: dan liever een foutmelding dan een verkeerde afstand
# bij elke advertentie.
MIN_POINTS = 8
MAX_RMS_KM = 2.0


class LocateError(Exception):
    """De postcode is niet te plaatsen; de tekst gaat naar de pagina."""


@dataclass(frozen=True)
class Home:
    postcode: str
    latitude: float
    longitude: float


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (lat1, lon1, lat2, lon2))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def normalize_postcode(text: str) -> Optional[str]:
    """"3511 ab" -> "3511AB", "3511" -> "3511"; None als het geen postcode is."""
    m = POSTCODE_RE.match(text or "")
    if not m or m.group(1).startswith("0"):
        return None
    return m.group(1) + (m.group(2) or "").upper()


def fit_home(points: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    """(lat, lon, rms in km) van het punt waarvan de afstanden tot `points`
    ((lat, lon, afstand in km)) het best kloppen. Gauss-Newton, begonnen bij
    de dichtstbijzijnde advertentie."""
    if len(points) < 3:
        raise LocateError("te weinig advertenties met een afstand")
    lat, lon, _ = min(points, key=lambda p: p[2])
    step = 1e-5
    for _ in range(40):
        a = b = c = g1 = g2 = 0.0
        for plat, plon, d in points:
            f = haversine_km(lat, lon, plat, plon)
            j1 = (haversine_km(lat + step, lon, plat, plon) - f) / step
            j2 = (haversine_km(lat, lon + step, plat, plon) - f) / step
            r = f - d
            a, b, c = a + j1 * j1, b + j1 * j2, c + j2 * j2
            g1, g2 = g1 + j1 * r, g2 + j2 * r
        det = a * c - b * b
        if abs(det) < 1e-12:
            break
        dlat, dlon = (c * g1 - b * g2) / det, (a * g2 - b * g1) / det
        lat, lon = lat - dlat, lon - dlon
        if abs(dlat) < 1e-7 and abs(dlon) < 1e-7:
            break
    rms = math.sqrt(sum((haversine_km(lat, lon, p[0], p[1]) - p[2]) ** 2 for p in points) / len(points))
    return lat, lon, rms


def locate_postcode(postcode: str, session=None) -> Home:
    """Eén zoekverzoek aan Marktplaats met de postcode, en daaruit de plek.
    Via recheck._get(): nooit tegelijk met of vlak na een klik op
    controleer."""
    import recheck as rc

    code = normalize_postcode(postcode)
    if code is None:
        raise LocateError(f"'{postcode}' is geen Nederlandse postcode (bv. 3511 of 3511AB).")
    params = [("query", LOCATE_QUERY), ("limit", LOCATE_LIMIT), ("offset", 0), ("postcode", code)]
    try:
        resp = rc._get(session or rc.make_session(), mp.BASE_URL + mp.SEARCH_API_PATH + "?" + urlencode(params))
        resp.raise_for_status()
        data = json.loads(resp.text)
    except (requests.RequestException, ValueError) as exc:
        raise LocateError(f"Kon Marktplaats niet bereiken ({exc}). Er is niets opgeslagen.") from None
    listings = data.get("listings") if isinstance(data, dict) else None
    if not isinstance(listings, list):
        raise LocateError("Marktplaats gaf geen advertentielijst terug — mogelijk is de zoek-API gewijzigd. "
                          "Er is niets opgeslagen.")
    points = []
    for raw in listings:
        lat, lon = mp.search_location(raw) if isinstance(raw, dict) else (None, None)
        meters = mp.as_number(((raw.get("location") or {}) if isinstance(raw, dict) else {}).get("distanceMeters"))
        if lat is not None and meters is not None and meters > 0:
            points.append((lat, lon, meters / 1000))
    if len(points) < MIN_POINTS:
        raise LocateError(f"Marktplaats gaf bij {code} maar {len(points)} advertenties met een afstand; "
                          "zo is de plek niet te bepalen. Kijk of de postcode klopt.")
    lat, lon, rms = fit_home(points)
    if rms > MAX_RMS_KM:
        raise LocateError(f"De afstanden bij {code} klopten niet met één plek ({rms:.1f} km afwijking). "
                          "Er is niets opgeslagen; probeer het later nog eens.")
    return Home(code, lat, lon)


def load_home(conn: sqlite3.Connection) -> Optional[Home]:
    code = db.get_setting(conn, SETTING_POSTCODE)
    lat, lon = db.get_setting(conn, SETTING_LATITUDE), db.get_setting(conn, SETTING_LONGITUDE)
    if not code or lat is None or lon is None:
        return None
    try:
        return Home(code, float(lat), float(lon))
    except ValueError:
        return None


def save_home(conn: sqlite3.Connection, home: Optional[Home]) -> None:
    """None wist hem: dan tonen de pagina's geen afstand."""
    db.set_setting(conn, SETTING_POSTCODE, home.postcode if home else None, commit=False)
    db.set_setting(conn, SETTING_LATITUDE, repr(home.latitude) if home else None, commit=False)
    db.set_setting(conn, SETTING_LONGITUDE, repr(home.longitude) if home else None, commit=False)
    conn.commit()


@dataclass(frozen=True)
class Distance:
    km: float
    approx: bool = False  # uit de plaatsnaam, niet uit de eigen plek van de advertentie

    @property
    def label(self) -> str:
        shown = f"{self.km:.0f} km" if self.km >= 10 else f"{self.km:.1f} km".replace(".", ",")
        return f"ca. {shown}" if self.approx else shown


def distances(conn: sqlite3.Connection, home: Optional[Home]) -> dict[str, Distance]:
    """{item_id: Distance} voor elke advertentie met een plek, of met een
    plaatsnaam die bij andere advertenties een plek heeft. Leeg zonder eigen
    plek of van vóór migratie 18."""
    if home is None:
        return {}
    places = db.list_places(conn)
    if not places:
        return {}
    cities = dict(conn.execute("SELECT item_id, city FROM listing WHERE city IS NOT NULL AND city <> ''"))
    by_city: dict[str, list] = {}
    for item_id, (lat, lon, *_rest) in places.items():
        city = cities.get(item_id)
        if city and lat is not None:
            by_city.setdefault(city, []).append((lat, lon))
    centre = {c: (statistics.median(p[0] for p in pts), statistics.median(p[1] for p in pts))
              for c, pts in by_city.items()}
    out: dict[str, Distance] = {}
    for item_id, city in cities.items():
        lat, lon = (places.get(item_id) or (None, None))[:2]
        approx = False
        if lat is None and city in centre:
            (lat, lon), approx = centre[city], True
        if lat is not None:
            out[item_id] = Distance(haversine_km(home.latitude, home.longitude, lat, lon), approx)
    return out


def load(db_path) -> tuple[Optional[Home], dict[str, Distance]]:
    """(eigen plek, afstanden) uit koopjes.db, alleen lezen."""
    if not db_path or not Path(db_path).exists():
        return None, {}
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        home = load_home(conn)
        return home, distances(conn, home)
    except sqlite3.Error:
        return None, {}
    finally:
        conn.close()
