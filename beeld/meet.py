"""Stap 0 van het beeldmodel: meten wat deze laptop aankan.

    python beeld/meet.py              standaardkeuze: alle vectornetwerken,
                                      Florence-2 base, leraren qwen3.5:35b
                                      (de grootste die past), gemma4:26b
                                      (terugval) en qwen3.5:2b (snel), als
                                      ze in Ollama staan
    python beeld/meet.py --lijst      welke modellen er te kiezen zijn
    python beeld/meet.py --modellen dinov2-s,siglip2-b
    python beeld/meet.py --map C:\\pad\\naar\\fotos   eigen foto's, zonder koopjes.db

Haalt eerst een handvol foto's op (één per fiets, beleefd: één tegelijk,
minstens 1,5 s ertussen), ook van verdwenen fietsen, om te zien of die nog
bestaan. Dan per model: laadtijd, seconden per foto, geheugen.

Wat het wegschrijft:
- beeld/metingen/stap0-<datum>.json: alleen tijden en tellingen, geen foto's,
  geen advertentienummers. Mag in git, zodat een volgende sessie kan lezen
  wat jouw laptop haalde.
- beeld/data/meting/: de foto's en wat Florence-2 en de leraar per foto
  zeiden. Niet in git (beeld/data/ staat in .gitignore).

Schrijft nooit in koopjes.db.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import statistics
import sys
from datetime import datetime
from pathlib import Path

BEELD_DIR = Path(__file__).resolve().parent
if str(BEELD_DIR) not in sys.path:
    sys.path.insert(0, str(BEELD_DIR))

import candidates as cand  # noqa: E402
import photos  # noqa: E402

RESULTS_DIR = BEELD_DIR / "metingen"
RUN_DIR = photos.DATA_DIR / "meting"
DEFAULT_OLLAMA = "http://localhost:11434"
# De leraar doet tientallen seconden per foto: niet alle foto's.
TEACHER_PHOTOS = 5
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def cpu_name() -> str:
    """De naam zoals Taakbeheer hem toont ("Intel(R) Core(TM) 7 150U");
    platform.processor() geeft op Windows alleen de familie."""
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def system_info() -> dict:
    info = {"systeem": platform.platform(), "processor": cpu_name(),
            "logische_kernen": os.cpu_count(), "python": platform.python_version()}
    try:
        import psutil

        info["ram_gb"] = round(psutil.virtual_memory().total / 1024 ** 3, 1)
        info["ram_vrij_gb"] = round(psutil.virtual_memory().available / 1024 ** 3, 1)
    except ImportError:
        pass
    for name in ("torch", "transformers"):
        try:
            info[name] = __import__(name).__version__
        except ImportError:
            info[name] = "niet geïnstalleerd"
    return info


def photo_sizes(paths: list[Path]) -> dict:
    """Mediaan breedte en hoogte: of een sticker leesbaar kan zijn hangt
    daarvan af."""
    try:
        from PIL import Image
    except ImportError:
        return {}
    widths, heights = [], []
    for path in paths:
        with Image.open(path) as image:
            widths.append(image.width)
            heights.append(image.height)
    if not widths:
        return {}
    return {"foto_breedte_mediaan": int(statistics.median(widths)),
            "foto_hoogte_mediaan": int(statistics.median(heights))}


def gather_from_db(db_path: Path, active: int, gone: int, delay: float) -> tuple[list[Path], dict]:
    conn = photos.open_readonly(db_path)
    try:
        bikes = photos.road_bikes(conn)
    finally:
        conn.close()
    picked = photos.sample(bikes, active, gone)
    counts = {"racefietsen_met_foto": len(bikes),
              "actief": sum(not b.disappeared for b in bikes),
              "verdwenen": sum(b.disappeared for b in bikes)}
    print(f"koopjes.db: {counts['racefietsen_met_foto']} racefietsen met foto "
          f"({counts['actief']} actief, {counts['verdwenen']} verdwenen). "
          f"Ophalen: {sum(not b.disappeared for b in picked)} actief + {sum(b.disappeared for b in picked)} "
          f"verdwenen, één foto per fiets.")
    session, polite = photos.make_session(), photos.Polite(delay)
    paths, outcome = [], {"actief": {"ok": 0, "weg": 0, "fout": 0}, "verdwenen": {"ok": 0, "weg": 0, "fout": 0}}
    for bike in picked:
        result = photos.fetch_photo(session, bike.urls[0], photos.photo_path(bike.item_id, 0, RUN_DIR / "fotos"),
                                    polite)
        group = "verdwenen" if bike.disappeared else "actief"
        outcome[group][result.status] += 1
        if result.status == "ok":
            paths.append(result.path)
        else:
            print(f"  {group} {bike.item_id}: {result.status} ({result.detail})")
    print(f"  actief: {outcome['actief']['ok']} gelukt; verdwenen: {outcome['verdwenen']['ok']} van "
          f"{sum(outcome['verdwenen'].values())} nog te laden")
    return paths, {**counts, "ophalen": outcome}


def gather_from_folder(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise FileNotFoundError(f"map {folder} bestaat niet")
    paths = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    print(f"{len(paths)} foto's uit {folder}")
    return paths


def run_one(c: cand.Candidate, paths: list[Path], args) -> cand.Measurement:
    try:
        if c.role == cand.VECTORS:
            return cand.measure_vectors(c, paths)
        if c.role == cand.CROPS:
            return cand.measure_florence(c, paths[:args.leraar_fotos * 2])
        return cand.measure_teacher(c, paths[:args.leraar_fotos], photos.make_session(), args.ollama)
    except ImportError as exc:
        hint = cand.access_hint(exc, c.model_id)
        if "torch" in str(exc) or "transformers" in str(exc):
            hint = f"{exc}; installeer eerst beeld/requirements.txt (zie beeld/README.md)"
        return cand.Measurement(c.key, c.role, c.model_id, status="overgeslagen", reason=hint)
    except Exception as exc:  # één model dat faalt mag de rest van de meting niet stoppen
        reason = cand.access_hint(exc, c.model_id)
        status = "overgeslagen" if cand.is_access_problem(reason) else "fout"
        return cand.Measurement(c.key, c.role, c.model_id, status=status, reason=reason)
    finally:
        # Het vorige model uit het geheugen voordat het volgende laadt.
        gc.collect()


def print_line(m: cand.Measurement) -> None:
    s = m.summary()
    if m.status != "ok":
        print(f"  {m.key:<12} {m.status}: {m.reason}")
        return
    extra = "".join(f", {k} {v}" for k, v in s.items()
                    if k in ("dimensies", "tokens_per_s", "batch_fotos_per_s") and v is not None)
    print(f"  {m.key:<12} {s['mediaan_s']} s per foto (eerste {s['eerste_foto_s']} s, laden {s['laden_s']} s, "
          f"~{s['fotos_per_uur']} per uur, geheugen {s['geheugen_mb']} MB{extra})")


def save(info: dict, gathered: dict, measurements: list, stamp: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"stap0-{stamp}.json"
    payload = {"gemeten_op": stamp, "laptop": info, "fotos": gathered,
               "modellen": [m.summary() for m in measurements]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    answers = {m.key: m.outputs for m in measurements if m.outputs}
    if answers:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        (RUN_DIR / f"antwoorden-{stamp}.json").write_text(
            json.dumps(answers, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Stap 0 van het beeldmodel: meten wat deze laptop aankan.")
    parser.add_argument("--lijst", action="store_true", help="toon de modellen en stop")
    parser.add_argument("--modellen", help="kommagescheiden, of 'alle'; standaard de aanbevolen set")
    parser.add_argument("--db", type=Path, default=photos.DEFAULT_DB, help="pad naar koopjes.db")
    parser.add_argument("--map", type=Path, help="eigen foto's gebruiken in plaats van koopjes.db")
    parser.add_argument("--actief", type=int, default=10, help="actieve fietsen (één foto elk)")
    parser.add_argument("--verdwenen", type=int, default=5, help="verdwenen fietsen: zijn hun foto's er nog?")
    parser.add_argument("--vertraging", type=float, default=photos.MIN_DELAY_S,
                        help=f"seconden tussen verzoeken, minstens {photos.MIN_DELAY_S}")
    parser.add_argument("--leraar-fotos", type=int, default=TEACHER_PHOTOS,
                        help="zoveel foto's per leraar (Florence-2 krijgt er het dubbele)")
    parser.add_argument("--ollama", default=DEFAULT_OLLAMA, help="adres van Ollama")
    args = parser.parse_args(argv)

    if args.lijst:
        for c in cand.CANDIDATES:
            print(f"{c.key:<12} {c.role:<9} {'standaard' if c.default else '         '} {c.model_id}  ({c.note})")
        return 0
    try:
        chosen = cand.select(args.modellen)
    except ValueError as exc:
        parser.error(str(exc))
    if args.vertraging < photos.MIN_DELAY_S:
        parser.error(f"--vertraging minstens {photos.MIN_DELAY_S} s: blijf beleefd tegen Marktplaats")

    info = system_info()
    print("Laptop: " + ", ".join(f"{k} {v}" for k, v in info.items()))
    try:
        if args.map:
            paths, gathered = gather_from_folder(args.map), {"bron": "eigen map"}
        else:
            paths, gathered = gather_from_db(args.db, args.actief, args.verdwenen, args.vertraging)
    except (FileNotFoundError, photos.SchemaError) as exc:
        print(f"Fout: {exc}", file=sys.stderr)
        return 1
    if len(paths) < 2:
        print("Fout: minder dan twee foto's; meten heeft zo geen zin.", file=sys.stderr)
        return 1
    gathered.update(photo_sizes(paths))

    print(f"\nMeten op {len(paths)} foto's (de eerste foto per model is opwarmen en telt niet mee):")
    measurements = []
    for c in chosen:
        print(f"- {c.key} ({c.role}) ...", flush=True)
        m = run_one(c, paths, args)
        print_line(m)
        measurements.append(m)

    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    path = save(info, gathered, measurements, stamp)
    print(f"\nTijden opgeslagen in {path.relative_to(BEELD_DIR.parent)}"
          f" (mag in git); foto's en antwoorden in {RUN_DIR.relative_to(BEELD_DIR.parent)} (niet in git).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
