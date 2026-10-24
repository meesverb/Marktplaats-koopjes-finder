"""Florence-2 (base en large) leest tekst op elke foto (<OCR>), SigLIP 2 maakt
een vector per foto. Scoren gebeurt later (scoren.py): het merk uit de OCR-
tekst tegen een merkenlijst, en SigLIP zonder training tegen tekstprompts.

    venv/bin/python visie.py florence2-b | florence2-l | siglip2-b
"""
import json
import sys
import time
from pathlib import Path

import torch
from PIL import Image
from transformers.utils import logging

logging.set_verbosity_error()
logging.disable_progress_bar()

HERE = Path(__file__).resolve().parent
OUT = HERE / "uitkomst"
OUT.mkdir(exist_ok=True)
IDS = {"florence2-b": "florence-community/Florence-2-base", "florence2-l": "florence-community/Florence-2-large",
       "siglip2-b": "google/siglip2-base-patch16-224"}


def photos():
    ads = json.loads((HERE / "advertenties.json").read_text())
    for iid in json.loads((HERE / "test_ids.json").read_text()):
        for name in ads[iid]["photos"]:
            yield iid, name


def florence(key):
    from transformers import AutoProcessor, Florence2ForConditionalGeneration

    model = Florence2ForConditionalGeneration.from_pretrained(IDS[key]).eval()
    proc = AutoProcessor.from_pretrained(IDS[key])
    path = OUT / f"{key}.json"
    done = json.loads(path.read_text()) if path.exists() else {}
    for n, (iid, name) in enumerate(photos(), 1):
        if name in done:
            continue
        image = Image.open(HERE / "fotos" / name).convert("RGB")
        start = time.perf_counter()
        inputs = proc(text="<OCR>", images=image, return_tensors="pt")
        with torch.inference_mode():
            ids = model.generate(**inputs, max_new_tokens=128, num_beams=3)
        raw = proc.batch_decode(ids, skip_special_tokens=False)[0]
        text = proc.post_process_generation(raw, task="<OCR>", image_size=image.size).get("<OCR>", "")
        done[name] = {"advertentie": iid, "tekst": text, "seconden": round(time.perf_counter() - start, 2),
                      "tokens_uit": int(ids.shape[-1])}
        if n % 25 == 0:
            path.write_text(json.dumps(done, ensure_ascii=False))
            print(key, n, flush=True)
    path.write_text(json.dumps(done, ensure_ascii=False))


def siglip():
    from transformers import AutoModel, AutoProcessor

    model = AutoModel.from_pretrained(IDS["siglip2-b"]).eval()
    proc = AutoProcessor.from_pretrained(IDS["siglip2-b"])
    vectors, meta = [], []
    start = time.perf_counter()
    for iid, name in photos():
        image = Image.open(HERE / "fotos" / name).convert("RGB")
        with torch.inference_mode():
            out = model.get_image_features(**proc(images=[image], return_tensors="pt"))
        vec = getattr(out, "pooler_output", out)[0]
        vectors.append((vec / vec.norm()).tolist())
        meta.append([iid, name])
    seconds = time.perf_counter() - start
    (OUT / "siglip2-b.json").write_text(json.dumps({"meta": meta, "vectoren": vectors,
                                                    "seconden_totaal": round(seconds, 1)}))


if __name__ == "__main__":
    key = sys.argv[1]
    siglip() if key == "siglip2-b" else florence(key)
    print("KLAAR", key, flush=True)
