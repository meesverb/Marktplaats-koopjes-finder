"""Kleine hulpfuncties die meer dan één module nodig heeft.

Alleen wat op meerdere plekken letterlijk hetzelfde was (een tijd uit de
database lezen, een bedrag in euro's schrijven). Wat per pagina net anders
moet (`dashboard.euro()` met een minteken, `flips.euro()` met centen,
`recheck._euro()` met "geen prijs") staat bewust bij die pagina.

Hangt van geen andere module in deze repo af.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def parse_time(value) -> Optional[datetime]:
    """Een ISO-tijd zoals de database hem bewaart, of None bij iets anders
    (leeg, None, onleesbaar). Zonder tijdzone in de tekst blijft het een tijd
    zonder tijdzone; gebruik parse_time_utc() als je ermee gaat rekenen tegen
    een tijd mét."""
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def parse_time_utc(value) -> Optional[datetime]:
    """Als parse_time(), maar altijd met tijdzone: "...Z" (zo schrijft de
    advertentiepagina het) wordt gelezen als UTC, en een tijd zonder
    tijdzone telt als UTC, zoals db.py ze wegschrijft."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def euro(amount: Optional[float]) -> str:
    """"€1.250" (hele euro's, punt als duizendtal), of "—" zonder bedrag."""
    return "—" if amount is None else f"€{amount:,.0f}".replace(",", ".")
