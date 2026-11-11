"""Cuts out every ActFurniture product photo that doesn't have a cutout yet.

Reads the shop's public product sitemap, downloads each product's main photo,
removes the background and saves cut/<photo id>.webp. Set limit.txt to a number
to process only that many new photos; 0 means no limit.
"""
import io
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.request

import cv2
import numpy as np
from PIL import Image

SITEMAP = "https://www.actfurniture.co.uk/store-products-sitemap.xml"
OUT = pathlib.Path("cut")
HEADERS = {"User-Agent": "actfurniture-cutouts/1.0"}
TIME_BUDGET_S = 5.25 * 60 * 60
COMMIT_EVERY = 50
SHEET = pathlib.Path("preview.jpg")


def fetch(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def stock_photos():
    xml = fetch(SITEMAP).decode("utf-8")
    photos = re.findall(r"static\.wixstatic\.com/media/([^/<?\s]+)", xml)
    return list(dict.fromkeys(photos))


def background_colours(image, mask):
    """Median wall (top strip) and floor (bottom strip) colours in Lab."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    height = image.shape[0]
    outside = mask == 0
    colours = []
    for strip in (lab[: int(height * 0.3)][outside[: int(height * 0.3)]],
                  lab[int(height * 0.9):][outside[int(height * 0.9):]]):
        if len(strip):
            colours.append(np.median(strip, axis=0))
    return lab, colours


def distance(lab, colour):
    return np.sqrt(((lab - colour) ** 2).sum(axis=2))


def clean_mask(image, alpha, opts=None):
    """Turns the model's soft mask into one solid, tidy piece of furniture.

    opts (used by tools/fix.py for hand fixes): wall (colour distance for wall
    patches, 0 turns the rule off), min_part (smallest separate part kept, as a
    share of the biggest), fill (fill every enclosed hole), erase / keep (lists of
    [x0, y0, x1, y1] boxes as fractions of the photo).
    """
    opts = opts or {}
    mask = (alpha > 0.5).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count < 2:
        return None
    biggest = stats[1:, cv2.CC_STAT_AREA].max()
    keep = np.zeros_like(mask)
    for index in range(1, count):
        if stats[index, cv2.CC_STAT_AREA] >= biggest * opts.get("min_part", 0.05):
            keep[labels == index] = 1

    lab, colours = background_colours(image, keep)
    if not colours:
        return keep
    near_background = np.min([distance(lab, c) for c in colours], axis=0)
    total = keep.size

    # A hole that doesn't look like wall or floor is furniture the model lost,
    # usually the inside of a glass cabinet, so put it back.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(1 - keep, 4)
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        touches_edge = x == 0 or y == 0 or x + w == keep.shape[1] or y + h == keep.shape[0]
        if touches_edge:
            continue
        if opts.get("fill") or area < total * 0.0005 or np.median(near_background[labels == index]) > 11:
            keep[labels == index] = 1

    # A large wall-coloured patch inside the shape is an open gap the model
    # filled in, such as the space between a sideboard's two tiers.
    wall = ((near_background < opts.get("wall", 9.5)) & (keep == 1)).astype(np.uint8)
    wall = cv2.morphologyEx(wall, cv2.MORPH_OPEN, np.ones((opts.get("wall_open", 7),) * 2, np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(wall, 4)
    for index in range(1, count):
        if stats[index, cv2.CC_STAT_AREA] >= total * opts.get("wall_min", 0.012):
            patch = cv2.dilate((labels == index).astype(np.uint8), np.ones((5, 5), np.uint8))
            keep[patch == 1] = 0

    h, w = keep.shape
    for x0, y0, x1, y1 in opts.get("keep", []):
        box = (slice(int(y0 * h), int(y1 * h)), slice(int(x0 * w), int(x1 * w)))
        keep[box] = np.maximum(keep[box], (near_background[box] > 12).astype(np.uint8))
    for x0, y0, x1, y1 in opts.get("erase", []):
        keep[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)] = 0
    return keep


def cutout(image, session, opts=None):
    """Returns a trimmed RGBA array of the furniture, or None if nothing was found."""
    from rembg import remove

    rgb = Image.fromarray(image[:, :, ::-1])
    alpha = np.asarray(remove(rgb, session=session))[:, :, 3].astype(np.float32) / 255
    keep = clean_mask(image, alpha, opts)
    if keep is None or keep.sum() < keep.size * 0.02:
        return None

    # Tighten the edge by a pixel so no wall colour shows, then soften it.
    edge = cv2.erode(keep, np.ones((3, 3), np.uint8))
    soft = np.clip(cv2.GaussianBlur(edge.astype(np.float32), (0, 0), 0.7) * 1.15, 0, 1)

    # Recolour edge pixels from the nearest solid wood pixel.
    solid = cv2.erode(keep, np.ones((5, 5), np.uint8))
    if solid.sum() == 0:
        return None
    _, nearest = cv2.distanceTransformWithLabels(1 - solid, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.where(solid > 0)
    lookup = np.zeros(nearest.max() + 1, int)
    lookup[nearest[ys, xs]] = np.arange(len(ys))
    colour = image.copy()
    fringe = solid == 0
    index = lookup[nearest[fringe]]
    colour[fringe] = image[ys[index], xs[index]]

    rgba = np.dstack([colour[:, :, ::-1], (soft * 255).astype(np.uint8)])
    rows, cols = np.where(soft > 0.05)
    return rgba[rows.min():rows.max() + 1, cols.min():cols.max() + 1]


def commit(message):
    subprocess.run(["git", "add", "cut", str(SHEET)], check=False)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return
    subprocess.run(["git", "commit", "-q", "-m", message], check=True)
    subprocess.run(["git", "pull", "-q", "--rebase", "origin", "main"], check=True)
    subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], check=True)


def contact_sheet(tiles):
    size, across = 320, 6
    rows = (len(tiles) + across - 1) // across
    sheet = Image.new("RGB", (size * across, size * rows), (231, 230, 226))
    for position, tile in enumerate(tiles):
        tile.thumbnail((size - 16, size - 16))
        x = position % across * size + (size - tile.width) // 2
        y = position // across * size + size - 8 - tile.height
        sheet.paste(tile, (x, y), tile)
    sheet.save(SHEET, quality=82)


def main():
    from rembg import new_session

    limit = int(pathlib.Path("limit.txt").read_text().strip() or 0)
    OUT.mkdir(exist_ok=True)
    photos = stock_photos()
    fixes = pathlib.Path("fixes.json")
    dropped = {k for k, v in json.loads(fixes.read_text()).items() if v.get("drop")} if fixes.exists() else set()
    todo = [p for p in photos
            if p.split("~")[0] not in dropped and not (OUT / f"{p.split('~')[0]}.webp").exists()]
    print(f"{len(photos)} photos in stock, {len(todo)} still need a cutout")
    if limit:
        todo = todo[:limit]
    if not todo:
        return

    session = new_session("isnet-general-use")
    started, done, failed, tiles = time.time(), 0, 0, []
    for photo in todo:
        if time.time() - started > TIME_BUDGET_S:
            print("Out of time for this run; the next run carries on")
            break
        try:
            url = f"https://static.wixstatic.com/media/{photo}/v1/fit/w_800,h_800,q_90/photo.jpg"
            image = np.asarray(Image.open(io.BytesIO(fetch(url))).convert("RGB"))[:, :, ::-1].copy()
            result = cutout(image, session)
            if result is None:
                raise ValueError("no furniture found")
            picture = Image.fromarray(result, "RGBA")
            picture.save(OUT / f"{photo.split('~')[0]}.webp", quality=90, method=6)
            if limit and len(tiles) < 60:
                tiles.append(picture.copy())
            done += 1
        except Exception as error:  # one bad photo shouldn't stop the run
            failed += 1
            print(f"Skipped {photo}: {error}")
        if done and done % COMMIT_EVERY == 0:
            commit(f"Add cutouts ({done} so far)")
    if tiles:
        contact_sheet(tiles)
    commit(f"Add cutouts ({done} new)")
    print(f"Finished: {done} made, {failed} skipped")


if __name__ == "__main__":
    sys.exit(main())
