"""Tekstprompts voor de modellen zonder taalmodel (SigLIP 2, embeddinggemma-2,
Florence-OCR): een gesloten keuzelijst per veld. De merkenlijst is die van de
repo (catalogus + sleepers.EXTRA_BRANDS) plus de merken in de sleutel; dat
laatste maakt het voor deze modellen makkelijker dan voor de taalmodellen, die
een open vraag kregen."""
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path("/home/user/Marktplaats-koopjes-finder")
EXTRA = ("Koga", "Miyata", "Myata", "Gazelle", "Peugeot", "Diamant", "Cinelli", "Haibike",
         "Triban", "Van Rysel", "Principia", "Alan", "3T", "Enve", "S-Works", "Paul Milnes")


def brands(with_key=True):
    """with_key=False: alleen de lijst van de repo, zoals hij in het echt zou zijn."""
    b = {x.lower() for x in EXTRA}
    with open(REPO / "reference_bike_catalog.csv", newline="", encoding="utf-8-sig") as f:
        b.update(r["brand"].strip().lower() for r in csv.DictReader(f) if r.get("brand"))
    if with_key:
        key = json.loads((HERE / "sleutel.json").read_text())
        b.update(v["merk"] for v in key.values() if v["merk"])
    b -= {"time", "rose"}
    return sorted(b)


FIELDS = {
    "rem": {"rim": "a road bike with rim brakes, caliper brakes on the wheel rims",
            "disc": "a road bike with disc brakes and brake rotors at the hubs"},
    "materiaal": {"steel": "a steel road bike with thin round tubes",
                  "aluminium": "an aluminium road bike with thick welded tubes",
                  "carbon": "a carbon fibre road bike",
                  "titanium": "a titanium road bike with brushed metal tubes"},
    "wielprofiel": {"deep": "a road bike with deep section aero wheels",
                    "shallow": "a road bike with low profile box section rims"},
}


def all_prompts():
    out = {f"merk:{b}": f"a photo of a {b.title()} road bike" for b in brands()}
    for field, opts in FIELDS.items():
        out.update({f"{field}:{k}": v for k, v in opts.items()})
    return out


if __name__ == "__main__":
    p = all_prompts()
    print(len(brands()), "merken,", len(p), "prompts")
