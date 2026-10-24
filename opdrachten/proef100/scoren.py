"""Alle modellen tegen de antwoordsleutel (sleutel.json): per veld goed / fout /
weet niet, met de meerderheidsklasse als ondergrens. Schrijft uitslag.md en
uitslag.json; draai het opnieuw zodra er een model bij is.

    python scoren.py            (numpy nodig voor SigLIP/embeddinggemma: venv-python)

Wat telt:
- merk: alleen advertenties waar de sleutel een merk heeft; apart of het merk
  op een foto leesbaar is. Koga/Koga Miyata/Miyata en B'Twin/Triban/Van Rysel
  zijn elk één merk.
- groep: alleen waar de sleutel een groep heeft; apart of die leesbaar is.
  "Shimano" zonder groepnaam is weet niet. Waar de sleutel geen groep heeft,
  tellen we alleen hoe vaak een model er toch een noemt (niet te controleren).
- rem, materiaal, wielprofiel: alleen waar de sleutel het weet.
- staat (roest, banden, lint/zadel, onderdelen, lak): niet gescoord, de sleutel
  heeft daar alleen vrije tekst voor; alleen hoe vaak een model "unknown" zegt.
"""
import json
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "uitkomst"
KEY = json.loads((HERE / "sleutel.json").read_text())
ADV_TO_ID = json.loads((HERE / "blind100_map.json").read_text())
ID_TO_ADV = {v: k for k, v in ADV_TO_ID.items()}
UNKNOWN = {"", "unknown", "none", "n/a", "na", "unreadable", "not visible", "onbekend", "null"}
BRAND_GROUPS = [{"koga", "kogamiyata", "miyata", "myata"}, {"btwin", "triban", "vanrysel", "decathlon"}]
GROUPS = {  # sleutelnaam -> patroon in het antwoord
    "dura-ace": r"dura[\s-]?ace", "ultegra": r"ultegra", "105": r"\b105\b", "tiagra": r"tiagra",
    "sora": r"\bsora\b", "claris": r"claris", "2300": r"\b2300\b", "600": r"\b600\b",
    "exage": r"exage", "rx100": r"rx[\s-]?100", "rsx": r"\brsx\b", "golden arrow": r"golden\s*arrow",
    "sante": r"\bsante\b", "record": r"(?<!chorus )\brecord\b", "chorus": r"chorus", "centaur": r"centaur",
    "veloce": r"veloce", "mirage": r"mirage", "xenon": r"xenon", "athena": r"athena",
    "gran sport": r"gran\s*sport", "potenza": r"potenza", "red": r"\bsram red\b", "force": r"\bforce\b",
    "rival": r"\brival\b", "apex": r"\bapex\b", "400": r"\b400\b", "dynamic": r"\bdynamic\b",
}
CONDITION = ["chain_rusty", "tyres_worn", "bar_tape_or_saddle_torn", "parts_missing", "paint_damage"]


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def is_unknown(s):
    return s is None or str(s).strip().lower() in UNKNOWN


def same_brand(key, answer):
    k, a = norm(key), norm(answer)
    if not k or not a:
        return False
    if k == a or (len(k) >= 4 and k in a) or (len(a) >= 4 and a in k):
        return True
    return any(any(x in k for x in g) and any(x in a for x in g) for g in BRAND_GROUPS)


def groups_in(answer):
    low = str(answer or "").lower()
    return {name for name, pat in GROUPS.items() if re.search(pat, low)}


# ---------- antwoorden inlezen: per model {adv: {veld: waarde}} ----------

def claude(prefix):
    out = {}
    for f in sorted((HERE / "claude").glob(f"{prefix}_b*.json")):
        for rec in json.loads(f.read_text()):
            out[rec["advertentie"]] = rec
    return out


def ollama(path):
    out, errors = {}, 0
    for iid, rec in json.loads(path.read_text()).items():
        if "antwoord" in rec:
            out[ID_TO_ADV[iid]] = rec["antwoord"]
        else:
            errors += 1
    return out, errors


def florence(path):
    """Merk en groep uit de OCR-tekst van alle foto's van een advertentie: het
    vaakst gelezen merk uit de lijst; een groep alleen als die ergens staat."""
    from prompts import brands
    brand_res = [(b, re.compile(r"(?<![a-z])" + re.escape(b).replace(r"\ ", r"[\s-]?") + r"(?![a-z])"))
                 for b in brands() if len(b) >= 3]
    texts = defaultdict(list)
    for rec in json.loads(path.read_text()).values():
        texts[rec["advertentie"]].append(rec["tekst"])
    out = {}
    for iid, parts in texts.items():
        low = " ".join(parts).lower()
        hits = Counter()
        for b, rx in brand_res:
            hits[b] += len(rx.findall(low))
        hits = +hits
        found = groups_in(low)
        out[ID_TO_ADV[iid]] = {"brand": hits.most_common(1)[0][0] if hits else "",
                               "groupset": " ".join(sorted(found)), "text_seen": parts}
    return out


def zero_shot(img_path, txt_path, brand_list=None):
    """Zonder training: per foto de gelijkenis met elke prompt. Merk: het
    hoogste over de foto's (één foto met het logo is genoeg); de rest: het
    gemiddelde over de foto's."""
    import numpy as np
    img = json.loads(img_path.read_text())
    txt = json.loads(txt_path.read_text())
    T = np.array(txt["vectoren"], dtype=np.float32)
    T /= np.linalg.norm(T, axis=1, keepdims=True)
    keys = txt["sleutels"]
    per_ad = defaultdict(list)
    for (iid, *_), v in zip(img["meta"], img["vectoren"]):
        per_ad[iid].append(v)
    out = {}
    for iid, vecs in per_ad.items():
        V = np.array(vecs, dtype=np.float32)
        V /= np.linalg.norm(V, axis=1, keepdims=True)
        S = V @ T.T  # foto's x prompts
        rec = {}
        for field, agg in (("merk", "max"), ("rem", "mean"), ("materiaal", "mean"), ("wielprofiel", "mean")):
            idx = [i for i, k in enumerate(keys) if k.startswith(field + ":")
                   and (field != "merk" or brand_list is None or k[5:] in brand_list)]
            col = S[:, idx].max(0) if agg == "max" else S[:, idx].mean(0)
            rec[field] = keys[idx[int(col.argmax())]].split(":", 1)[1]
        out[ID_TO_ADV[iid]] = {"brand": rec["merk"], "brake_type": rec["rem"],
                               "frame_material": rec["materiaal"], "wheel_profile": rec["wielprofiel"]}
    return out


# ---------- scoren ----------

def tally():
    return {"goed": 0, "fout": 0, "weet niet": 0, "ontbreekt": 0}


def score(answers):
    s = {k: tally() for k in ("merk leesbaar", "merk niet leesbaar", "groep leesbaar", "groep niet leesbaar",
                              "rem", "materiaal", "wielprofiel")}
    s["groep genoemd zonder sleutel"] = 0
    cond = Counter()
    for adv, k in KEY.items():
        a = answers.get(adv)
        if a is None:
            for name in s:
                if isinstance(s[name], dict) and _applies(name, k):
                    s[name]["ontbreekt"] += 1
            continue
        if k["merk"]:
            t = s["merk leesbaar" if k["merk_leesbaar"] else "merk niet leesbaar"]
            b = a.get("brand")
            t["weet niet" if is_unknown(b) else ("goed" if same_brand(k["merk"], b) else "fout")] += 1
        found = groups_in(a.get("groupset"))
        if k["groep"]:
            t = s["groep leesbaar" if k["groep_leesbaar"] else "groep niet leesbaar"]
            t["weet niet" if not found else ("goed" if k["groep"] in found else "fout")] += 1
        elif found:
            s["groep genoemd zonder sleutel"] += 1
        for name, key_field, ans_field in (("rem", "rem", "brake_type"), ("materiaal", "materiaal", "frame_material"),
                                           ("wielprofiel", "wielprofiel", "wheel_profile")):
            if k[key_field] == "unknown":
                continue
            v = a.get(ans_field)
            s[name]["weet niet" if is_unknown(v) else ("goed" if v == k[key_field] else "fout")] += 1
        for c in CONDITION:
            if c in a:
                cond[c, "unknown" if is_unknown(a[c]) else "oordeel"] += 1
    s["staat: aandeel unknown"] = {c: round(cond[c, "unknown"] / max(1, cond[c, "unknown"] + cond[c, "oordeel"]), 2)
                                   for c in CONDITION if cond[c, "unknown"] + cond[c, "oordeel"]}
    return s


def _applies(name, k):
    return {"merk leesbaar": k["merk"] and k["merk_leesbaar"], "merk niet leesbaar": k["merk"] and not k["merk_leesbaar"],
            "groep leesbaar": k["groep"] and k["groep_leesbaar"],
            "groep niet leesbaar": k["groep"] and not k["groep_leesbaar"],
            "rem": k["rem"] != "unknown", "materiaal": k["materiaal"] != "unknown",
            "wielprofiel": k["wielprofiel"] != "unknown"}[name]


def baselines():
    out = {}
    for name, f in (("rem", "rem"), ("materiaal", "materiaal"), ("wielprofiel", "wielprofiel")):
        c = Counter(k[f] for k in KEY.values() if k[f] != "unknown")
        top, n = c.most_common(1)[0]
        out[name] = f"altijd '{top}': {n}/{sum(c.values())}"
    return out


# ---------- kosten: tokens en tijd ----------

def claude_cost(prefix):
    toks = json.loads((HERE / "claude_tokens.json").read_text())
    known = {k: v for k, v in toks.items() if k.startswith(prefix + "_b")}
    batches = sorted(f.stem for f in (HERE / "claude").glob(f"{prefix}_b*.json"))
    manifests = {f"{prefix}_b{n:02d}": len(re.findall(r"^adv\d{3}:", (HERE.parent / "blind100" / f"batch{n:02d}.txt")
                                                           .read_text(), re.M)) for n in range(1, 21)}
    photos = {f"{prefix}_b{n:02d}": len(re.findall(r"adv\d{3}_\d+\.jpg", (HERE.parent / "blind100" / f"batch{n:02d}.txt")
                                                    .read_text())) for n in range(1, 21)}
    tot = sum(v["tokens"] for v in known.values())
    ads = sum(manifests[b] for b in known)
    ph = sum(photos[b] for b in known)
    # subagent_tokens bevat per batch ook een vaste voet (systeemprompt,
    # tooldefinities, herhaald meesturen); een rechte lijn door
    # (foto's, tokens) scheidt die van wat er per foto bij komt.
    xs, ys = [photos[b] for b in known], [known[b]["tokens"] for b in known]
    fit = {}
    if len(xs) >= 3:
        mx, my = statistics.mean(xs), statistics.mean(ys)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
        fit = {"per foto (lijn)": round(slope), "vaste voet per batch (lijn)": round(my - slope * mx)}
    return {"batches met uitkomst": len(batches), "batches met tokentelling": len(known),
            "tokens (bekende batches)": tot, "advertenties daarin": ads, "foto's daarin": ph,
            "tokens per advertentie": round(tot / ads) if ads else None,
            "tokens per foto": round(tot / ph) if ph else None, **fit,
            "seconden per advertentie": round(sum(v["ms"] for v in known.values()) / 1000 / ads, 1) if ads else None,
            "onbekend": sorted(set(b for b in manifests) - set(known))}


def ollama_cost(path):
    d = json.loads(path.read_text())
    ok = [v for v in d.values() if "antwoord" in v or "onleesbaar" in v]
    if not ok:
        return {"advertenties": 0}
    tin = [v["tokens_in"] for v in ok if v.get("tokens_in") is not None]
    tout = [v["tokens_uit"] for v in ok if v.get("tokens_uit") is not None]
    sec = [v["seconden"] for v in ok]
    return {"advertenties": len(ok), "fouten": len(d) - len(ok),
            "tokens in (som)": sum(tin), "tokens uit (som)": sum(tout),
            "tokens per advertentie": round((sum(tin) + sum(tout)) / len(ok)),
            "seconden per advertentie (mediaan)": round(statistics.median(sec), 1),
            "seconden totaal": round(sum(sec))}


def vector_cost(path):
    d = json.loads(path.read_text())
    out = {"foto's": len(d["meta"]), "seconden totaal": d.get("seconden_totaal")}
    if d["meta"] and len(d["meta"][0]) > 2:
        out["tokens in (som)"] = sum(m[2] or 0 for m in d["meta"])
    return out


def florence_cost(path):
    d = json.loads(path.read_text())
    return {"foto's": len(d), "seconden totaal": round(sum(v["seconden"] for v in d.values())),
            "tokens uit (som)": sum(v["tokens_uit"] for v in d.values())}


def main():
    models, costs, notes = {}, {}, {}
    for p in ("haiku", "sonnet", "opus"):
        if any((HERE / "claude").glob(f"{p}_b*.json")):
            models[f"claude-{p}"] = claude(p)
            costs[f"claude-{p}"] = claude_cost(p)
    for f in sorted(OUT.glob("*.json")):
        name = f.stem
        if name.startswith(("tekst_", "siglip2-b_schaal")):
            continue
        if name in ("siglip2-b", "embeddinggemma-2"):
            txt = OUT / ("tekst_siglip.json" if name == "siglip2-b" else "tekst_gemma.json")
            try:
                models[name] = zero_shot(f, txt)
                # Eerlijker: alleen de merkenlijst van de repo; merken die
                # daar niet in staan kan het model dan niet goed hebben.
                from prompts import brands
                models[name + " (repo-merken)"] = zero_shot(f, txt, set(brands(with_key=False)))
            except ImportError:
                notes[name] = "numpy ontbreekt: draai met de venv-python"
                continue
            costs[name] = vector_cost(f)
        elif name.startswith("florence"):
            models[name] = florence(f)
            costs[name] = florence_cost(f)
        else:
            models[name], errors = ollama(f)
            costs[name] = ollama_cost(f)
    results = {m: score(a) for m, a in models.items()}
    (HERE / "uitslag.json").write_text(json.dumps({"scores": results, "kosten": costs, "basis": baselines(),
                                                   "notities": notes}, indent=1, ensure_ascii=False))
    write_md(results, costs, notes)
    print((HERE / "uitslag.md").read_text())


def cell(t):
    answered = t["goed"] + t["fout"]
    prec = f" ({100 * t['goed'] // answered}%)" if answered else ""
    miss = f" +{t['ontbreekt']}∅" if t["ontbreekt"] else ""
    return f"{t['goed']}/{t['fout']}/{t['weet niet']}{prec}{miss}"


def write_md(results, costs, notes):
    n = lambda f: sum(1 for k in KEY.values() if f(k))  # noqa: E731
    head = ["model", f"merk leesbaar (n={n(lambda k: k['merk'] and k['merk_leesbaar'])})",
            f"merk niet leesbaar (n={n(lambda k: k['merk'] and not k['merk_leesbaar'])})",
            f"groep leesbaar (n={n(lambda k: k['groep'] and k['groep_leesbaar'])})",
            f"groep niet leesbaar (n={n(lambda k: k['groep'] and not k['groep_leesbaar'])})",
            "groep genoemd, sleutel leeg", "rem", "materiaal", "wielprofiel"]
    lines = ["# Uitslag beeldtest 100 advertenties", "",
             "Per cel: goed/fout/weet niet (precisie = goed van wat het model durfde te zeggen). "
             "+N∅ = advertenties zonder antwoord van dat model.", "",
             "Meerderheidsklasse: " + "; ".join(f"{k} {v}" for k, v in baselines().items()), "",
             "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for m, s in results.items():
        lines.append("| " + " | ".join([m, cell(s["merk leesbaar"]), cell(s["merk niet leesbaar"]),
                                        cell(s["groep leesbaar"]), cell(s["groep niet leesbaar"]),
                                        str(s["groep genoemd zonder sleutel"]), cell(s["rem"]),
                                        cell(s["materiaal"]), cell(s["wielprofiel"])]) + " |")
    lines += ["", "## Staat (niet gescoord): aandeel 'unknown'", "", "| model | " + " | ".join(CONDITION) + " |",
              "|" + "---|" * (len(CONDITION) + 1)]
    for m, s in results.items():
        u = s["staat: aandeel unknown"]
        if u:
            lines.append(f"| {m} | " + " | ".join(str(u.get(c, "-")) for c in CONDITION) + " |")
    lines += ["", "## Kosten", ""]
    for m, c in costs.items():
        lines.append(f"- **{m}**: " + ", ".join(f"{k}: {v}" for k, v in c.items()))
    for m, t in notes.items():
        lines.append(f"- {m}: {t}")
    (HERE / "uitslag.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
