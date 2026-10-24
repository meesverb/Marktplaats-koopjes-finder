"""Per advertentie een overzichtsblad met alle foto's (genummerd), om de
antwoordsleutel te maken. Twee foto's naast elkaar op 720 px breed, zodat
stickers leesbaar blijven; lange galerijen over meerdere bladen."""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
OUT = HERE / "bladen"
OUT.mkdir(exist_ok=True)
CELL_W, CELL_H, COLS, ROWS = 720, 540, 2, 2  # 1440x1080 per blad: 4 foto's


def sheets(iid, photos):
    per = COLS * ROWS
    paths = []
    for s in range(0, len(photos), per):
        chunk = photos[s:s + per]
        rows = (len(chunk) + COLS - 1) // COLS
        sheet = Image.new("RGB", (CELL_W * COLS, CELL_H * rows), "white")
        draw = ImageDraw.Draw(sheet)
        for k, name in enumerate(chunk):
            im = Image.open(HERE / "fotos" / name).convert("RGB")
            im.thumbnail((CELL_W, CELL_H))
            x, y = (k % COLS) * CELL_W, (k // COLS) * CELL_H
            sheet.paste(im, (x + (CELL_W - im.width) // 2, y + (CELL_H - im.height) // 2))
            draw.rectangle([x, y, x + 34, y + 22], fill="yellow")
            draw.text((x + 4, y + 4), str(s + k), fill="black")
        p = OUT / f"{iid}_blad{s // per + 1}.jpg"
        sheet.save(p, quality=88)
        paths.append(p.name)
    return paths


if __name__ == "__main__":
    ads = json.loads((HERE / "advertenties.json").read_text())
    ids = sys.argv[1:] or list(ads)
    for iid in ids:
        print(iid, sheets(iid, ads[iid]["photos"]))
