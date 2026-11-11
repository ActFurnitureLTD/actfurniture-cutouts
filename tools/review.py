"""Builds review sheets: each original photo next to its cutout on a bright background.

Writes review/sheet_NNN.jpg and review/index.csv (number, photo id, score), worst first.
The score estimates how much wall or floor colour is left inside the cutout.
"""
import csv
import io
import pathlib
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

CUT = pathlib.Path("cut")
OUT = pathlib.Path("review")
TILE = 280
ACROSS, DOWN = 3, 5
CHECK = (226, 54, 196)


def full_names():
    """Maps each photo id to its full Wix file name, read from the shop's sitemap."""
    request = urllib.request.Request("https://www.actfurniture.co.uk/store-products-sitemap.xml",
                                     headers={"User-Agent": "actfurniture-cutouts/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        xml = response.read().decode("utf-8")
    names = re.findall(r"static\.wixstatic\.com/media/([^/<?\s]+)", xml)
    return {n.split("~")[0]: n for n in names}


NAMES = {}


def original(photo_id):
    name = NAMES.get(photo_id, f"{photo_id}~mv2.jpeg")
    url = f"https://static.wixstatic.com/media/{name}/v1/fit/w_800,h_800,q_90/photo.jpg"
    request = urllib.request.Request(url, headers={"User-Agent": "actfurniture-cutouts/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return Image.open(io.BytesIO(response.read())).convert("RGB")
    except Exception:
        return None


def score(orig, cut):
    """Share of the cutout's visible pixels that look like the photo's wall or floor."""
    o = cv2.cvtColor(np.asarray(orig), cv2.COLOR_RGB2LAB).astype(np.float32)
    h = o.shape[0]
    bands = [o[: int(h * 0.12)].reshape(-1, 3), o[int(h * 0.94):].reshape(-1, 3)]
    colours = [np.median(b, axis=0) for b in bands]
    c = np.asarray(cut)
    alpha = c[:, :, 3] > 200
    if alpha.sum() == 0:
        return 1.0
    lab = cv2.cvtColor(c[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)[alpha]
    near = np.min([np.sqrt(((lab - col) ** 2).sum(axis=1)) for col in colours], axis=0)
    return float((near < 8).mean())


def fit(img, size):
    img = img.copy()
    img.thumbnail((size - 10, size - 10))
    return img


def main():
    OUT.mkdir(exist_ok=True)
    NAMES.update(full_names())
    ids = sorted(p.stem for p in CUT.glob("*.webp"))
    with ThreadPoolExecutor(8) as pool:
        originals = list(pool.map(original, ids))
    rows = []
    for photo_id, orig in zip(ids, originals):
        cut = Image.open(CUT / f"{photo_id}.webp").convert("RGBA")
        rows.append((score(orig, cut) if orig else 1.0, photo_id, orig, cut))
    rows.sort(key=lambda r: -r[0])

    font = ImageFont.load_default(size=22)
    per = ACROSS * DOWN
    with open(OUT / "index.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["number", "photo_id", "score"])
        for start in range(0, len(rows), per):
            sheet = Image.new("RGB", (ACROSS * TILE * 2, DOWN * TILE), (255, 255, 255))
            draw = ImageDraw.Draw(sheet)
            for k, (s, photo_id, orig, cut) in enumerate(rows[start:start + per]):
                number = start + k + 1
                writer.writerow([number, photo_id, f"{s:.3f}"])
                x, y = (k % ACROSS) * TILE * 2, (k // ACROSS) * TILE
                if orig:
                    o = fit(orig, TILE)
                    sheet.paste(o, (x + (TILE - o.width) // 2, y + (TILE - o.height) // 2))
                bg = Image.new("RGB", (TILE, TILE), CHECK)
                c = fit(cut, TILE)
                bg.paste(c, ((TILE - c.width) // 2, (TILE - c.height) // 2), c)
                sheet.paste(bg, (x + TILE, y))
                draw.rectangle([x, y, x + 2 * TILE - 1, y + TILE - 1], outline=(0, 0, 0), width=2)
                draw.rectangle([x + 2, y + 2, x + 70, y + 30], fill=(0, 0, 0))
                draw.text((x + 8, y + 4), str(number), fill=(255, 255, 0), font=font)
            sheet.save(OUT / f"sheet_{start // per + 1:03d}.jpg", quality=80)
    print(f"{len(rows)} pieces on {(len(rows) + per - 1) // per} sheets")


if __name__ == "__main__":
    sys.exit(main())
