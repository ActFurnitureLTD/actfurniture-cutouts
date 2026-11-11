"""Re-makes the cutouts listed in fixes.json with hand-picked settings.

fixes.json maps a photo id to its settings, for example
  {"86c0c7_abc": {"model": "birefnet-general", "wall": 0, "fill": true,
                  "erase": [[0.1, 0.0, 0.4, 0.2]]}}
"model" picks the background-removal model (default isnet-general-use).
"drop": true deletes the cutout, so the page shows a plain block instead.
Every other key is passed to clean_mask (see scripts/make_cutouts.py).

Only pieces listed in todo.txt are redone (all of fixes.json if it's empty).
Writes review/fix_NNN.jpg sheets (original | new cutout) to the review branch.
"""
import io
import json
import pathlib
import sys
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, "scripts")
sys.path.insert(0, "tools")
from make_cutouts import cutout  # noqa: E402
from review import full_names  # noqa: E402

CUT = pathlib.Path("cut")
SHEETS = pathlib.Path("review")
TILE = 300
CHECK = (226, 54, 196)


def main():
    from rembg import new_session

    fixes = json.loads(pathlib.Path("fixes.json").read_text())
    wanted = [line.strip() for line in pathlib.Path("todo.txt").read_text().splitlines() if line.strip()]
    ids = wanted or list(fixes)
    names = full_names()
    sessions = {}
    tiles = []
    for photo_id in ids:
        opts = dict(fixes.get(photo_id, {}))
        target = CUT / f"{photo_id}.webp"
        if opts.pop("drop", False):
            target.unlink(missing_ok=True)
            print(f"Dropped {photo_id}")
            continue
        model = opts.pop("model", "isnet-general-use")
        if model not in sessions:
            sessions[model] = new_session(model)
        name = names.get(photo_id, f"{photo_id}~mv2.jpeg")
        url = f"https://static.wixstatic.com/media/{name}/v1/fit/w_800,h_800,q_90/photo.jpg"
        request = urllib.request.Request(url, headers={"User-Agent": "actfurniture-cutouts/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            photo = Image.open(io.BytesIO(response.read())).convert("RGB")
        result = cutout(np.asarray(photo)[:, :, ::-1].copy(), sessions[model], opts)
        if result is None:
            print(f"No furniture found for {photo_id}")
            continue
        picture = Image.fromarray(result, "RGBA")
        picture.save(target, quality=90, method=6)
        tiles.append((photo_id, photo, picture))
        print(f"Fixed {photo_id}")

    SHEETS.mkdir(exist_ok=True)
    font = ImageFont.load_default(size=20)
    across, down = 3, 4
    per = across * down
    for start in range(0, len(tiles), per):
        sheet = Image.new("RGB", (across * TILE * 2, down * TILE), (255, 255, 255))
        draw = ImageDraw.Draw(sheet)
        for k, (photo_id, photo, picture) in enumerate(tiles[start:start + per]):
            x, y = (k % across) * TILE * 2, (k // across) * TILE
            o = photo.copy()
            o.thumbnail((TILE - 10, TILE - 10))
            sheet.paste(o, (x + (TILE - o.width) // 2, y + (TILE - o.height) // 2))
            bg = Image.new("RGB", (TILE, TILE), CHECK)
            c = picture.copy()
            c.thumbnail((TILE - 10, TILE - 10))
            bg.paste(c, ((TILE - c.width) // 2, (TILE - c.height) // 2), c)
            sheet.paste(bg, (x + TILE, y))
            draw.rectangle([x, y, x + 2 * TILE - 1, y + TILE - 1], outline=(0, 0, 0), width=2)
            draw.rectangle([x + 2, y + 2, x + 150, y + 26], fill=(0, 0, 0))
            draw.text((x + 6, y + 3), photo_id[7:15], fill=(255, 255, 0), font=font)
        sheet.save(SHEETS / f"fix_{start // per + 1:03d}.jpg", quality=82)


if __name__ == "__main__":
    sys.exit(main())
