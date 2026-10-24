"""Lokale leraren via Ollama op de 100 testadvertenties: per advertentie één
verzoek met alle foto's, dezelfde vraag en vaste keuzes als beeld/candidates.py
(aangepast van "één foto" naar "de foto's van één advertentie"). Bewaart per
advertentie het antwoord, de tijd en de exacte tokentellingen van Ollama
(prompt_eval_count = invoer incl. foto's, eval_count = uitvoer).

    python lokaal.py qwen3.5:2b [--max-fotos N]
"""
import base64
import json
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, "/home/user/Marktplaats-koopjes-finder/beeld")
import candidates as cand  # noqa: E402

PROMPT = cand.TEACHER_PROMPT.replace(
    "This is one photo from a used road bike listing. Answer only from what is visible in this photo;",
    "These are all the photos of one used road bike listing. Answer only from what is visible in these photos;")
assert PROMPT != cand.TEACHER_PROMPT
SCHEMA = cand.TEACHER_SCHEMA
BASE = "http://localhost:11434"


def main():
    model = sys.argv[1]
    max_photos = int(sys.argv[sys.argv.index("--max-fotos") + 1]) if "--max-fotos" in sys.argv else 99
    limit = int(sys.argv[sys.argv.index("--aantal") + 1]) if "--aantal" in sys.argv else None
    ads = json.loads((HERE / "advertenties.json").read_text())
    test = json.loads((HERE / "test_ids.json").read_text())
    out_path = HERE / "uitkomst" / f"{model.replace(':', '_')}.json"
    out_path.parent.mkdir(exist_ok=True)
    done = json.loads(out_path.read_text()) if out_path.exists() else {}
    for n, iid in enumerate(test[:limit], 1):
        if iid in done:
            continue
        photos = ads[iid]["photos"][:max_photos]
        images = [base64.b64encode((HERE / "fotos" / p).read_bytes()).decode() for p in photos]
        body = {"model": model, "stream": False, "think": False, "format": SCHEMA, "keep_alive": "30m",
                "options": {"temperature": 0, "num_predict": cand.TEACHER_MAX_TOKENS, "num_ctx": 16384},
                "messages": [{"role": "user", "content": PROMPT, "images": images}]}
        start = time.perf_counter()
        try:
            r = requests.post(f"{BASE}/api/chat", json=body, timeout=3600)
            if r.status_code == 400 and "think" in r.text.lower():
                body.pop("think")
                r = requests.post(f"{BASE}/api/chat", json=body, timeout=3600)
        except Exception as exc:
            done[iid] = {"fout": f"{type(exc).__name__}: {exc}"[:300]}
            out_path.write_text(json.dumps(done, indent=1, ensure_ascii=False))
            print(n, iid, "fout", exc, flush=True)
            continue
        seconds = time.perf_counter() - start
        rec = {"seconden": round(seconds, 1), "fotos": len(photos)}
        if r.status_code != 200:
            rec["fout"] = f"HTTP {r.status_code}: {r.text[:300]}"
        else:
            data = r.json()
            content = (data.get("message") or {}).get("content", "")
            try:
                rec["antwoord"] = json.loads(content)
            except ValueError:
                rec["onleesbaar"] = content[:500]
            rec["tokens_in"] = data.get("prompt_eval_count")
            rec["tokens_uit"] = data.get("eval_count")
        done[iid] = rec
        out_path.write_text(json.dumps(done, indent=1, ensure_ascii=False))
        print(n, iid, rec.get("seconden"), rec.get("tokens_in"), rec.get("tokens_uit"),
              "fout" if "fout" in rec else "", flush=True)
        if "fout" in rec and n <= 2:
            print("stop: model werkt niet", flush=True)
            break
    print("KLAAR", flush=True)


if __name__ == "__main__":
    main()
