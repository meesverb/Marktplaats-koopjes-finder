"""Tekstvectoren van de prompts (prompts.py) voor embeddinggemma-2 (Ollama) of
SigLIP 2 (venv): python tekstvectoren.py gemma | siglip"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from prompts import all_prompts  # noqa: E402

prompts = all_prompts()
keys, texts = list(prompts), list(prompts.values())
if sys.argv[1] == "gemma":
    import requests
    r = requests.post("http://localhost:11434/api/embed",
                      json={"model": "embeddinggemma-2", "input": texts}, timeout=600)
    r.raise_for_status()
    vecs = r.json()["embeddings"]
else:
    import torch
    from transformers import AutoModel, AutoProcessor
    model = AutoModel.from_pretrained("google/siglip2-base-patch16-224").eval()
    proc = AutoProcessor.from_pretrained("google/siglip2-base-patch16-224")
    with torch.inference_mode():
        inp = proc(text=texts, padding="max_length", max_length=64, return_tensors="pt")
        out = model.get_text_features(**inp)
    out = getattr(out, "pooler_output", out)
    vecs = (out / out.norm(dim=-1, keepdim=True)).tolist()
    scale = {"logit_scale": model.logit_scale.exp().item(), "logit_bias": model.logit_bias.item()}
    (HERE / "uitkomst" / "siglip2-b_schaal.json").write_text(json.dumps(scale))
(HERE / "uitkomst" / f"tekst_{sys.argv[1]}.json").write_text(json.dumps({"sleutels": keys, "vectoren": vecs}))
print(sys.argv[1], len(vecs), len(vecs[0]))
