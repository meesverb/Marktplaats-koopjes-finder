"""embeddinggemma-2 via Ollama: een vector per foto ({"image": base64} in
`input` van /api/embed; het "images"-veld werkt niet, getest 22-10-2026).
Scoren zonder training gebeurt in scoren.py, zoals bij SigLIP 2."""
import base64
import json
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ads = json.loads((HERE / "advertenties.json").read_text())
meta, vectors = [], []
start = time.perf_counter()
for iid in json.loads((HERE / "test_ids.json").read_text()):
    for name in ads[iid]["photos"]:
        img = base64.b64encode((HERE / "fotos" / name).read_bytes()).decode()
        r = requests.post("http://localhost:11434/api/embed",
                          json={"model": "embeddinggemma-2", "input": [{"image": img}], "keep_alive": "30m"},
                          timeout=300)
        r.raise_for_status()
        data = r.json()
        vectors.append(data["embeddings"][0])
        meta.append([iid, name, data.get("prompt_eval_count")])
(HERE / "uitkomst").mkdir(exist_ok=True)
(HERE / "uitkomst" / "embeddinggemma-2.json").write_text(json.dumps(
    {"meta": meta, "vectoren": vectors, "seconden_totaal": round(time.perf_counter() - start, 1)}))
print("KLAAR embeddinggemma-2", len(vectors), flush=True)
