"""Foto's van racefietsen: welke er zijn (uit koopjes.db, alleen lezen) en
ze beleefd ophalen naar beeld/data/fotos/.

Bewust zonder import uit de rest van de repo: beeld/ moet los te koppelen
zijn. Wat hier over koopjes.db staat (de tabel `listing`, de kolom
`image_urls`, racefietsen herkend aan de categorie in de URL) is dus een
kopie van wat racefiets_jev.py en racebikes.py doen, geen gedeelde code.
Verandert het schema daar, dan breekt het hier met een duidelijke melding in
plaats van stil.

Alleen stdlib en requests (dat staat al in de requirements van de repo):
de tests hiervan draaien zonder torch.
"""
from __future__ import annotations

import random
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

BEELD_DIR = Path(__file__).resolve().parent
REPO_DIR = BEELD_DIR.parent
DEFAULT_DB = REPO_DIR / "koopjes.db"
DATA_DIR = BEELD_DIR / "data"
PHOTO_DIR = DATA_DIR / "fotos"

# Zelfde categorie als racefiets_jev.ROAD_BIKE_CATEGORY; racebikes.py herkent
# een racefiets op dezelfde manier aan de URL.
ROAD_BIKE_CATEGORY = "fietsen-racefietsen"

# Zelfde browser als de scraper zich voordoet (racefiets_jev.USER_AGENT): een
# ander profiel voor dezelfde gebruiker zou alleen opvallen.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Minstens zoveel tussen twee verzoeken, zoals recheck.py: één tegelijk en
# rustig. Foto's komen van de beeldserver van Marktplaats, niet van de site
# zelf, maar ook daar geldt: de belasting niet opvoeren (CLAUDE.md).
MIN_DELAY_S = 1.5
# Een advertentiefoto is een paar honderd kB. Wat veel groter is, is geen
# foto van een advertentie, en hoort niet op de schijf.
MAX_PHOTO_BYTES = 15 * 1024 * 1024
TIMEOUT_S = 20


class SchemaError(RuntimeError):
    """koopjes.db ziet er anders uit dan beeld/ verwacht."""


@dataclass
class Bike:
    item_id: str
    title: str
    urls: list[str]
    disappeared: bool


@dataclass
class Fetch:
    url: str
    path: Optional[Path] = None
    status: str = "fout"  # "ok", "weg" (404/410) of "fout"
    detail: str = ""
    bytes: int = 0


@dataclass
class Polite:
    """Houdt MIN_DELAY_S tussen twee verzoeken, ook over aanroepen heen."""
    delay_s: float = MIN_DELAY_S
    _last: Optional[float] = field(default=None, repr=False)
    sleep: object = field(default=time.sleep, repr=False)
    clock: object = field(default=time.monotonic, repr=False)

    def wait(self) -> None:
        if self._last is not None:
            left = self.delay_s - (self.clock() - self._last)
            if left > 0:
                self.sleep(left)
        self._last = self.clock()


def split_urls(text: Optional[str]) -> list[str]:
    """De foto-URL's zoals racefiets_jev.search_image_urls() ze wegschrijft:
    gescheiden door spaties, alleen https."""
    return [u for u in (text or "").split() if u.startswith("https://")]


def open_readonly(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} bestaat niet. Draai dit vanaf de laptop met koopjes.db, of geef --db mee.")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(listing)")}
    missing = {"item_id", "title", "url", "image_urls", "disappeared_at"} - columns
    if missing:
        conn.close()
        raise SchemaError(f"tabel listing in {path} mist kolom(men) {', '.join(sorted(missing))}; "
                          "is de database ouder dan migratie 6, of is het schema veranderd?")
    return conn


def road_bikes(conn: sqlite3.Connection) -> list[Bike]:
    """Alle racefietsen met minstens één foto-URL, de nieuwste eerst."""
    rows = conn.execute(
        "SELECT item_id, title, image_urls, disappeared_at FROM listing "
        "WHERE url LIKE ? AND image_urls IS NOT NULL AND image_urls != '' "
        "ORDER BY last_seen DESC, item_id",
        (f"%/{ROAD_BIKE_CATEGORY}/%",)).fetchall()
    bikes = []
    for r in rows:
        urls = split_urls(r["image_urls"])
        if urls:
            bikes.append(Bike(r["item_id"], r["title"] or "", urls, r["disappeared_at"] is not None))
    return bikes


def sample(bikes: list[Bike], active: int, gone: int, seed: int = 1) -> list[Bike]:
    """`active` actieve en `gone` verdwenen fietsen, willekeurig maar
    herhaalbaar (vaste seed): een tweede meting pakt dezelfde fietsen, dus
    de tijden zijn te vergelijken."""
    rng = random.Random(seed)
    pick_active = [b for b in bikes if not b.disappeared]
    pick_gone = [b for b in bikes if b.disappeared]
    return (rng.sample(pick_active, min(active, len(pick_active)))
            + rng.sample(pick_gone, min(gone, len(pick_gone))))


def photo_path(item_id: str, index: int, folder: Path = PHOTO_DIR) -> Path:
    return folder / f"{item_id}_{index}.jpg"


def fetch_photo(session, url: str, dest: Path, polite: Polite) -> Fetch:
    """Eén foto ophalen naar `dest`. Staat hij er al, dan geen verzoek."""
    if dest.exists() and dest.stat().st_size > 0:
        return Fetch(url, dest, "ok", "al op schijf", dest.stat().st_size)
    polite.wait()
    try:
        response = session.get(url, timeout=TIMEOUT_S)
    except Exception as exc:  # netwerkfout van welke soort ook: melden, doorgaan
        return Fetch(url, None, "fout", f"{type(exc).__name__}: {exc}")
    if response.status_code in (404, 410):
        return Fetch(url, None, "weg", f"HTTP {response.status_code}")
    if response.status_code != 200:
        return Fetch(url, None, "fout", f"HTTP {response.status_code}")
    kind = (response.headers.get("Content-Type") or "").split(";")[0].strip()
    if not kind.startswith("image/"):
        return Fetch(url, None, "fout", f"geen foto maar {kind or 'onbekend type'}")
    body = response.content
    if not body or len(body) > MAX_PHOTO_BYTES:
        return Fetch(url, None, "fout", f"onverwachte grootte ({len(body)} bytes)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return Fetch(url, dest, "ok", kind, len(body))


def make_session():
    import requests

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "nl-NL,nl;q=0.9"})
    return session
