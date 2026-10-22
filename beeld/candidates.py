"""De modellen die stap 0 meet, en hoe je er één foto doorheen haalt.

Drie rollen (zie opdrachten/beeldmodel.md):
- vectoren: een voorgetraind netwerk maakt van een foto een rij getallen;
  daar komt later de eigen classifier op (de leerling).
- uitsnede: Florence-2 omkadert onderdelen (crank, derailleur, rem, wiel) en
  leest tekst, zodat de groepset op een uitsnede bekeken kan worden in plaats
  van op een overzichtsfoto waar de crank 100 pixels breed is.
- leraar: een klein beeld-taalmodel via Ollama dat stickers leest en zegt wat
  het ziet. Traag, maar zonder labels.

torch en transformers worden pas geïmporteerd als een model echt gemeten
wordt: dit bestand moet ook zonder die twee te laden zijn (tests, --lijst).
"""
from __future__ import annotations

import base64
import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

VECTORS, CROPS, TEACHER = "vectoren", "uitsnede", "leraar"


@dataclass(frozen=True)
class Candidate:
    key: str
    role: str
    model_id: str
    note: str
    default: bool = True


# Licenties en groottes uit de modelkaarten (22-10-2026); bronnen in
# opdrachten/beeldmodel.md. Niet standaard: de grotere varianten, die pas
# zin hebben als de kleine te zwak blijken en de tijd het toelaat.
CANDIDATES = (
    Candidate("dinov2-s", VECTORS, "facebook/dinov2-small", "Apache 2.0, 22M"),
    Candidate("dinov2-b", VECTORS, "facebook/dinov2-base", "Apache 2.0, 86M"),
    Candidate("dinov3-s+", VECTORS, "facebook/dinov3-vits16plus-pretrain-lvd1689m",
              "DINOv3-licentie, toegang aanvragen, 29M"),
    Candidate("dinov3-b", VECTORS, "facebook/dinov3-vitb16-pretrain-lvd1689m",
              "DINOv3-licentie, toegang aanvragen, 86M"),
    Candidate("siglip2-b", VECTORS, "google/siglip2-base-patch16-224", "Apache 2.0, ook zonder training"),
    Candidate("florence2-b", CROPS, "florence-community/Florence-2-base", "MIT, 230M"),
    Candidate("florence2-l", CROPS, "florence-community/Florence-2-large", "MIT, 770M", default=False),
    Candidate("qwen3.5:2b", TEACHER, "qwen3.5:2b", "Apache 2.0, Ollama, ~3 GB"),
    Candidate("qwen3.5:4b", TEACHER, "qwen3.5:4b", "Apache 2.0, Ollama, ~4 GB", default=False),
    Candidate("gemma4:e2b", TEACHER, "gemma4:e2b", "Apache 2.0, Ollama, ~5-7 GB"),
)
BY_KEY = {c.key: c for c in CANDIDATES}

# Wat Florence-2 per foto moet doen: onderdelen omkaderen (de uitsnedes voor
# later) en tekst lezen (merk- en groepsetstickers).
CROP_PHRASES = ("crankset", "rear derailleur", "brake lever", "bicycle wheel")
FLORENCE_TASKS = ("<OCR>", "<OPEN_VOCABULARY_DETECTION>")

# De leraar ziet alleen de foto, nooit de titel of tekst: anders praat hij de
# verkoper na en zegt "leraar en verkoper zijn het eens" niets meer.
# Eerste versie (22-10-2026) gaf voorbeelden ("rusty chain, worn tyres") en
# vrije tekst per veld: qwen3.5:2b schreef de voorbeelden terug bij bijna
# elke fiets, ook in nieuwstaat, zette de uitlegzin als antwoord bij
# cosmetic, en verzon modellen en groepsets ("Allez 10" op een Scott, "750mm").
# Daarom: vaste keuzes met "unknown", en merk/model/groepset alleen als het
# leesbaar op de fiets staat. Groepsetgeneratie is eruit: daar was elk
# antwoord onzin.
TEACHER_PROMPT = (
    "This is one photo from a used road bike listing. Answer only from what is visible in this photo; "
    "never guess from what a bike usually has. text_seen: every word or number printed on the bike that "
    "you can actually read (frame, fork, wheels, crankset, shifters, derailleurs), copied exactly; an "
    "empty list if you cannot read any. brand, model, groupset and wheel_brand: only when that name is "
    "readable on the bike itself, otherwise an empty string. For every other field answer unknown when "
    "you cannot see it clearly.")
_UNKNOWN_YES_NO = {"type": "string", "enum": ["yes", "no", "unknown"]}
TEACHER_SCHEMA = {
    "type": "object",
    "properties": {
        "text_seen": {"type": "array", "items": {"type": "string"}},
        "brand": {"type": "string"},
        "model": {"type": "string"},
        "groupset": {"type": "string"},
        "wheel_brand": {"type": "string"},
        "brake_type": {"type": "string", "enum": ["rim", "disc", "unknown"]},
        "frame_material": {"type": "string", "enum": ["carbon", "aluminium", "steel", "titanium", "unknown"]},
        "wheel_profile": {"type": "string", "enum": ["deep", "shallow", "unknown"]},
        "chain_rusty": _UNKNOWN_YES_NO,
        "tyres_worn": _UNKNOWN_YES_NO,
        "bar_tape_or_saddle_torn": _UNKNOWN_YES_NO,
        "parts_missing": _UNKNOWN_YES_NO,
        "paint_damage": {"type": "string", "enum": ["none", "light", "heavy", "unknown"]},
    },
    "required": ["text_seen", "brand", "model", "groupset", "wheel_brand", "brake_type", "frame_material",
                 "wheel_profile", "chain_rusty", "tyres_worn", "bar_tape_or_saddle_torn", "parts_missing",
                 "paint_damage"],
}
TEACHER_TIMEOUT_S = 600


@dataclass
class Measurement:
    key: str
    role: str
    model_id: str
    status: str = "ok"  # "ok", "overgeslagen" of "fout"
    reason: str = ""
    load_s: Optional[float] = None
    first_s: Optional[float] = None  # eerste foto: opwarmen, telt niet mee
    seconds: list = field(default_factory=list)  # de foto's daarna
    batch_photos_per_s: Optional[float] = None
    memory_mb: Optional[float] = None
    extra: dict = field(default_factory=dict)
    outputs: list = field(default_factory=list)  # (foto, antwoord): alleen naar beeld/data/

    def summary(self) -> dict:
        """Wat in beeld/metingen/ komt: tijden en tellingen, geen foto's,
        geen advertentienummers en geen antwoorden."""
        times = self.seconds or ([self.first_s] if self.first_s is not None else [])
        median = statistics.median(times) if times else None
        return {
            "model": self.key, "rol": self.role, "model_id": self.model_id, "status": self.status,
            "reden": self.reason, "laden_s": _round(self.load_s), "eerste_foto_s": _round(self.first_s),
            "fotos": len(times), "mediaan_s": _round(median),
            "max_s": _round(max(times)) if times else None,
            "batch_fotos_per_s": _round(self.batch_photos_per_s),
            "fotos_per_uur": int(3600 / median) if median else None,
            "geheugen_mb": _round(self.memory_mb, 0), **self.extra,
        }


def _round(value, digits: int = 2):
    return None if value is None else round(value, digits)


def select(keys: Optional[str]) -> list[Candidate]:
    """`--modellen dinov2-s,siglip2-b`; leeg = de standaardkeuze."""
    if not keys:
        return [c for c in CANDIDATES if c.default]
    picked = []
    for key in (k.strip() for k in keys.split(",")):
        if not key:
            continue
        if key == "alle":
            return list(CANDIDATES)
        if key not in BY_KEY:
            raise ValueError(f"onbekend model '{key}'; kies uit: {', '.join(BY_KEY)} of 'alle'")
        picked.append(BY_KEY[key])
    return picked


def access_hint(error: Exception, model_id: str) -> str:
    """Een begrijpelijke reden bij de fouten die je bij stap 0 kunt verwachten."""
    text = f"{type(error).__name__}: {error}"
    lowered = text.lower()
    if "gated" in lowered or "401" in text or "403" in text or "access" in lowered and "restricted" in lowered:
        return (f"geen toegang tot {model_id}: vraag toegang aan op https://huggingface.co/{model_id} "
                "en log in met 'hf auth login'")
    if "florence2" in lowered and ("cannot import" in lowered or "has no attribute" in lowered):
        return "deze transformers kent Florence-2 nog niet: pip install -U transformers"
    return text[:300]


def is_access_problem(reason: str) -> bool:
    return reason.startswith("geen toegang") or reason.startswith("deze transformers")


def _memory_mb() -> Optional[float]:
    try:
        import psutil
    except ImportError:
        return None
    return psutil.Process().memory_info().rss / 1024 / 1024


def _memory_growth(before: Optional[float]) -> Optional[float]:
    """Hoeveel het proces groeide door dit model. Bij benadering: de
    geheugenbeheerder geeft niet alles terug na het vorige model."""
    after = _memory_mb()
    return None if before is None or after is None else max(after - before, 0.0)


def _quiet_transformers() -> None:
    # De voortgangsbalken en configwaarschuwingen van transformers maken de
    # meting onleesbaar; fouten komen nog wel door.
    from transformers.utils import logging

    logging.set_verbosity_error()
    logging.disable_progress_bar()


def _open_images(paths: list[Path]):
    from PIL import Image

    return [Image.open(p).convert("RGB") for p in paths]


def _timed(fn):
    start = time.perf_counter()
    result = fn()
    return time.perf_counter() - start, result


def measure_vectors(c: Candidate, paths: list[Path], batch: int = 8) -> Measurement:
    import torch
    from transformers import AutoImageProcessor, AutoModel, AutoProcessor

    _quiet_transformers()
    m = Measurement(c.key, c.role, c.model_id)
    siglip = "siglip" in c.model_id
    before = _memory_mb()

    def load():
        model = AutoModel.from_pretrained(c.model_id).eval()
        proc = (AutoProcessor if siglip else AutoImageProcessor).from_pretrained(c.model_id)
        return model, proc

    m.load_s, (model, proc) = _timed(load)
    images = _open_images(paths)

    def embed(batch_images):
        with torch.inference_mode():
            inputs = proc(images=batch_images, return_tensors="pt")
            if siglip:
                out = model.get_image_features(**inputs)
                # transformers 5 geeft een model-uitvoer terug, oudere versies een tensor.
                out = getattr(out, "pooler_output", out)
            else:
                out = model(**inputs).pooler_output
        return out

    for i, image in enumerate(images):
        seconds, vec = _timed(lambda: embed([image]))
        if i == 0:
            m.first_s = seconds
            m.extra["dimensies"] = int(vec.shape[-1])
        else:
            m.seconds.append(seconds)
    if len(images) > 1:
        chunk = images[:batch]
        seconds, _ = _timed(lambda: embed(chunk))
        m.batch_photos_per_s = len(chunk) / seconds
    m.memory_mb = _memory_growth(before)
    m.extra["threads"] = torch.get_num_threads()
    return m


def measure_florence(c: Candidate, paths: list[Path]) -> Measurement:
    import torch
    from transformers import AutoProcessor, Florence2ForConditionalGeneration

    _quiet_transformers()
    m = Measurement(c.key, c.role, c.model_id)
    before = _memory_mb()

    def load():
        model = Florence2ForConditionalGeneration.from_pretrained(c.model_id).eval()
        return model, AutoProcessor.from_pretrained(c.model_id)

    m.load_s, (model, proc) = _timed(load)
    per_task = {task: [] for task in FLORENCE_TASKS}

    def run(image, task: str, text: str = ""):
        inputs = proc(text=task + text, images=image, return_tensors="pt")
        with torch.inference_mode():
            ids = model.generate(**inputs, max_new_tokens=256, num_beams=3)
        raw = proc.batch_decode(ids, skip_special_tokens=False)[0]
        return proc.post_process_generation(raw, task=task, image_size=image.size)

    for i, (path, image) in enumerate(zip(paths, _open_images(paths))):
        total, answer = 0.0, {}
        for task in FLORENCE_TASKS:
            if task == "<OPEN_VOCABULARY_DETECTION>":
                boxes = {}
                for phrase in CROP_PHRASES:
                    seconds, result = _timed(lambda: run(image, task, phrase))
                    total += seconds
                    per_task[task].append(seconds)
                    boxes[phrase] = result.get(task, result)
                answer[task] = boxes
            else:
                seconds, result = _timed(lambda: run(image, task))
                total += seconds
                per_task[task].append(seconds)
                answer[task] = result.get(task, result)
        m.outputs.append((path.name, answer))
        if i == 0:
            m.first_s = total
        else:
            m.seconds.append(total)
    m.memory_mb = _memory_growth(before)
    for task, times in per_task.items():
        rest = times[len(CROP_PHRASES):] if task == "<OPEN_VOCABULARY_DETECTION>" else times[1:]
        if rest:
            m.extra[f"mediaan_s {task}"] = round(statistics.median(rest), 2)
    m.extra["threads"] = torch.get_num_threads()
    return m


def ollama_models(session, base_url: str) -> set:
    response = session.get(f"{base_url}/api/tags", timeout=10)
    response.raise_for_status()
    return {model.get("name", "") for model in response.json().get("models", [])}


def measure_teacher(c: Candidate, paths: list[Path], session, base_url: str) -> Measurement:
    m = Measurement(c.key, c.role, c.model_id)
    try:
        present = ollama_models(session, base_url)
    except Exception as exc:
        m.status, m.reason = "overgeslagen", (f"Ollama niet bereikbaar op {base_url} ({type(exc).__name__}); "
                                              "is Ollama geïnstalleerd en gestart?")
        return m
    if c.model_id not in present and f"{c.model_id}:latest" not in present:
        m.status, m.reason = "overgeslagen", f"niet gedownload: ollama pull {c.model_id}"
        return m
    rates = []
    for i, path in enumerate(paths):
        body = {
            "model": c.model_id, "stream": False, "think": False, "format": TEACHER_SCHEMA,
            "options": {"temperature": 0}, "keep_alive": "10m",
            "messages": [{"role": "user", "content": TEACHER_PROMPT,
                          "images": [base64.b64encode(path.read_bytes()).decode("ascii")]}],
        }
        start = time.perf_counter()
        response = session.post(f"{base_url}/api/chat", json=body, timeout=TEACHER_TIMEOUT_S)
        if response.status_code == 400 and "think" in response.text.lower():
            # Een model zonder denkstand weigert het veld; dan zonder.
            body.pop("think")
            response = session.post(f"{base_url}/api/chat", json=body, timeout=TEACHER_TIMEOUT_S)
        seconds = time.perf_counter() - start
        if response.status_code != 200:
            m.status, m.reason = "fout", f"HTTP {response.status_code}: {response.text[:200]}"
            return m
        data = response.json()
        content = (data.get("message") or {}).get("content", "")
        try:
            answer = json.loads(content)
        except ValueError:
            answer = {"onleesbaar": content[:500]}
        m.outputs.append((path.name, answer))
        if data.get("eval_count") and data.get("eval_duration"):
            rates.append(data["eval_count"] / (data["eval_duration"] / 1e9))
        if i == 0:
            m.first_s = seconds
            m.load_s = (data.get("load_duration") or 0) / 1e9
        else:
            m.seconds.append(seconds)
    if rates:
        m.extra["tokens_per_s"] = round(statistics.median(rates), 1)
    try:
        running = session.get(f"{base_url}/api/ps", timeout=10).json().get("models", [])
        size = next((r.get("size") for r in running if r.get("name", "").startswith(c.model_id)), None)
        m.memory_mb = size / 1024 / 1024 if size else None
    except Exception:
        pass
    return m
