"""Draws every gallery photo of the products in gallery.json, one row per product.

gallery.json maps a main photo id to {"loc": product slug, "photos": [full file names]}.
Writes review/gallery_NNN.jpg; each tile is labelled "<row>.<photo number>".
"""
import io
import json
import pathlib
import urllib.request

from PIL import Image, ImageDraw, ImageFont

SHEETS = pathlib.Path("review")
TILE = 180
ACROSS = 15
ROWS = 6


def load(name):
    url = f"https://static.wixstatic.com/media/{name}/v1/fit/w_400,h_400,q_80/photo.jpg"
    request = urllib.request.Request(url, headers={"User-Agent": "actfurniture-cutouts/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return Image.open(io.BytesIO(response.read())).convert("RGB")


def main():
    gallery = json.loads(pathlib.Path("gallery.json").read_text())
    SHEETS.mkdir(exist_ok=True)
    font = ImageFont.load_default(size=18)
    rows = list(gallery.items())
    index_lines = []
    for start in range(0, len(rows), ROWS):
        chunk = rows[start:start + ROWS]
        sheet = Image.new("RGB", (ACROSS * TILE, len(chunk) * (TILE + 24)), (255, 255, 255))
        draw = ImageDraw.Draw(sheet)
        for r, (main, info) in enumerate(chunk):
            row_no = start + r + 1
            y = r * (TILE + 24)
            draw.text((4, y + 2), f"{row_no}  {info['loc'][:110]}", fill=(0, 0, 0), font=font)
            for k, name in enumerate(info["photos"][:ACROSS]):
                index_lines.append(f"{row_no}.{k + 1},{main},{name}")
                try:
                    photo = load(name)
                except Exception as error:  # a missing photo shouldn't stop the sheet
                    print(f"Skipped {name}: {error}")
                    continue
                photo.thumbnail((TILE - 8, TILE - 8))
                x = k * TILE
                sheet.paste(photo, (x + (TILE - photo.width) // 2, y + 24 + (TILE - photo.height) // 2))
                draw.rectangle((x + 2, y + 26, x + 46, y + 48), fill=(0, 0, 0))
                draw.text((x + 6, y + 27), f"{row_no}.{k + 1}", fill=(255, 255, 0), font=font)
        sheet.save(SHEETS / f"gallery_{start // ROWS + 1:03d}.jpg", quality=82)
    (SHEETS / "gallery_index.csv").write_text("\n".join(index_lines) + "\n")


if __name__ == "__main__":
    main()
