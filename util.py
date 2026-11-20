"""Kleine hulpfuncties die meer dan één module nodig heeft.

Wat op meerdere plekken hetzelfde moet: een tijd uit de database lezen of
tonen, een bedrag in euro's schrijven.

Hangt van geen andere module in deze repo af.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
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


def parse_day(value) -> Optional[date]:
    """De dag van een datum of tijdstip, of None. Een tijdstip met tijdzone
    (de database bewaart UTC) telt op de lokale dag, zoals date.today():
    anders stond een flip die je om half een 's nachts op te koop zette
    meteen op "1 dag"."""
    moment = parse_time(value)
    if moment is not None and len(value) > 10:
        return (moment.astimezone() if moment.tzinfo else moment).date()
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def local_time(value, fmt: str = "%d-%m-%Y %H:%M") -> str:
    """Een tijd uit de database op de eigen klok. De database en de rondes
    bewaren UTC ("...+00:00", de advertentiepagina "...Z"); een tijd zonder
    tijdzone (een eigen bod) blijft zoals hij is. Onleesbaar: de tekst zelf."""
    moment = parse_time(str(value).replace("Z", "+00:00")) if value else None
    if moment is None:
        return value or "?"
    return (moment.astimezone() if moment.tzinfo else moment).strftime(fmt)


def euro(amount: Optional[float], cents: bool = False, sign: bool = False, none: str = "—") -> str:
    """"€1.250", "−€5", met `cents` "€11,95" (op /flips: een onderdeel van
    €11,95 is geen €12), met `sign` "+€25". Zonder bedrag `none`."""
    if amount is None:
        return none
    text = f"{abs(amount):,.{2 if cents else 0}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("−" if amount < 0 else "+" if sign else "") + "€" + text
