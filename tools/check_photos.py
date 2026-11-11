"""Checks that every product's main photo (the one the Shop by Size page uses) has a cutout.

Reads each product page politely (about one a second) and compares its main photo
with the cutouts. Writes review/photo_check.csv listing every product that would
show the plain block, and why.
"""
import csv
import json
import pathlib
import re
import time
import urllib.request

HEADERS = {"User-Agent": "actfurniture-cutouts/1.0 (photo check)"}


def get(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def main():
    cut = {p.stem for p in pathlib.Path("cut").glob("*.webp")}
    fixes = json.loads(pathlib.Path("fixes.json").read_text())
    dropped = {k for k, v in fixes.items() if v.get("drop")}
    xml = get("https://www.actfurniture.co.uk/store-products-sitemap.xml")
    rows, ok, failed = [], 0, 0
    for entry in xml.split("<url>")[1:]:
        page = re.search(r"<loc>([^<]+)</loc>", entry).group(1)
        listed = re.search(r"/media/([^/~<]+)", entry)
        listed = listed.group(1) if listed else ""
        main_photo, title = "", ""
        for attempt in range(3):
            try:
                html = get(page)
                found = re.search(r'property="og:image" content="[^"]*/media/([^/~"]+)', html)
                if found:
                    main_photo = found.group(1)
                    named = re.search(r'property="og:title" content="([^"]+)"', html)
                    title = named.group(1) if named else ""
                    break
            except Exception:
                pass
            time.sleep(10 * (attempt + 1))
        time.sleep(1.2)
        if not main_photo:
            failed += 1
            rows.append([page, title, "", listed, "could not read page"])
        elif main_photo in cut:
            ok += 1
        elif main_photo in dropped:
            rows.append([page, title, main_photo, listed, "block on purpose (set or close-up)"])
        elif main_photo != listed:
            rows.append([page, title, main_photo, listed, "main photo differs from listed photo, no cutout"])
        else:
            rows.append([page, title, main_photo, listed, "no cutout"])
    out = pathlib.Path("review")
    out.mkdir(exist_ok=True)
    with open(out / "photo_check.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["page", "title", "main_photo", "listed_photo", "result"])
        writer.writerows(rows)
    print(f"{ok} products show their cutout; {len(rows)} listed in photo_check.csv ({failed} unreadable)")


if __name__ == "__main__":
    main()
