"""Rondes starten vanaf de startpagina (/start in `python dashboard.py --serve`).

Een knop doet precies wat de taakplanner doet: `python koopjes.py run <slot>`,
als eigen proces op de achtergrond. Dat proces heeft het slot van koopjes.py
(.koopjes.lock), dus Marktplaats krijgt nooit twee rondes tegelijk, ook niet
als de taakplanner er net een start. Het loopt door als je de server stopt.

Blijf beleefd tegen Marktplaats: een knop mag de crawl-frequentie niet
opvoeren. Daarom een wachttijd per slot sinds de vorige ronde van dat slot
(ook een geplande): een half uur voor een slot met een vast aantal pagina's,
zes uur voor een slot dat alles ophaalt (pages 0: nacht, week, defy,
horloges). Een overgeslagen ronde (slot bezet) telt niet.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import koopjes

COOLDOWN = timedelta(minutes=30)
FULL_CRAWL_COOLDOWN = timedelta(hours=6)
LOG_LINES = 40


class LaunchError(RuntimeError):
    """Waarom een ronde niet start; de tekst gaat naar de pagina."""


@dataclass
class SlotInfo:
    name: str
    searches: tuple
    pages: int
    times: str  # "08:30, 13:30" of "handmatig"
    last: Optional[dict]  # de laatste ronde van dit slot uit rondes.jsonl
    ready_at: Optional[datetime]  # vanaf wanneer hij weer mag; None = nu

    @property
    def full(self) -> bool:
        return self.pages == 0


def _time(value) -> Optional[datetime]:
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def slots(config: koopjes.Config, now: Optional[datetime] = None) -> list[SlotInfo]:
    now = now or datetime.now(timezone.utc)
    rounds = koopjes.load_rounds(config.base_dir / config.rounds_file, limit=500)
    out = []
    for slot in config.slots.values():
        last = next((r for r in rounds if r.get("slot") == slot.name and r.get("status") != "overgeslagen"), None)
        ready = None
        started = _time(last.get("started_at")) if last else None
        if started is not None:
            wait = FULL_CRAWL_COOLDOWN if slot.pages == 0 else COOLDOWN
            if started + wait > now:
                ready = started + wait
        times = ", ".join(t.label() for t in slot.times) or "handmatig"
        out.append(SlotInfo(slot.name, tuple(slot.searches), slot.pages, times, last, ready))
    return out


def is_running(config: koopjes.Config) -> bool:
    """Of er nu een ronde draait: het slot van koopjes.py is bezet. Even
    pakken en loslaten, zoals `koopjes.py status` doet."""
    try:
        with koopjes.run_lock(koopjes.lock_path(config)):
            return False
    except koopjes.LockBusy:
        return True


def start(config: koopjes.Config, slot_name: str, popen=subprocess.Popen,
          now: Optional[datetime] = None) -> subprocess.Popen:
    info = next((s for s in slots(config, now) if s.name == slot_name), None)
    if info is None:
        raise LaunchError(f"Onbekend tijdslot '{slot_name}'.")
    if is_running(config):
        raise LaunchError("Er draait al een ronde; wacht tot die klaar is.")
    if info.ready_at is not None:
        local = info.ready_at.astimezone().strftime("%H:%M")
        why = "haalt alles op" if info.full else "draaide net"
        raise LaunchError(f"Ronde '{slot_name}' {why}; om Marktplaats niet te vaak te bevragen kan hij weer vanaf "
                          f"{local}.")
    command = [sys.executable, str(Path(koopjes.__file__).resolve()), "--config", str(config.path), "run", slot_name]
    kwargs = {"cwd": str(config.base_dir), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        # Geen zwart venster, en los van de server: Ctrl+C in het
        # servervenster stopt de ronde niet halverwege.
        kwargs["creationflags"] = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                   | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    else:
        kwargs["start_new_session"] = True
    try:
        return popen(command, **kwargs)
    except OSError as exc:
        raise LaunchError(f"Kon de ronde niet starten: {exc}") from None


def log_tail(config: koopjes.Config, lines: int = LOG_LINES) -> str:
    """Het eind van logs/koopjes.log: wat de ronde nu doet."""
    path = config.base_dir / config.log_file
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 20_000))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])
