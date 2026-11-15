#!/usr/bin/env python3
"""Scrape one product photo per GPU model and cut it out to a transparent PNG.

Candidates come from the retailer listings in data/data.json (populated by
update_data.py); a model can pin a specific photo with "img_url" in models.json.
Background removal is a flood fill from the image border over near-white
pixels, followed by a soft alpha edge. Retail product shots sit on pure white,
so this keeps the card (including white shrouds that touch no border) intact.

Requires Pillow + numpy:  pip install pillow numpy
Usage: python scripts/fetch_images.py [model-id ...] [--force]
"""
from __future__ import annotations

import io
import json
import re
import sys
import urllib.request
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "img" / "gpus"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"


def big(url: str) -> str:
    # Amazon: ..._SL160_.jpg -> _SL1500_ ; Newegg: ProductImageCompressAll640 -> ProductImage
    url = re.sub(r"\._[A-Z]{2}\d+_\.", "._SL1500_.", url)
    return url.replace("ProductImageCompressAll640", "ProductImage")


def download(url: str) -> Image.Image:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return Image.open(io.BytesIO(r.read())).convert("RGB")


def cutout(img: Image.Image, tol: int = 18) -> Image.Image:
    a = np.asarray(img).astype(np.int16)
    h, w, _ = a.shape
    # "background-like" = close to the border's dominant (near-white) colour
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = np.median(border, axis=0)
    dist = np.abs(a - bg).max(axis=2)
    cand = dist <= tol
    seen = np.zeros((h, w), bool)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if cand[y, x] and not seen[y, x]:
                seen[y, x] = True; q.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if cand[y, x] and not seen[y, x]:
                seen[y, x] = True; q.append((y, x))
    while q:
        y, x = q.popleft()
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= ny < h and 0 <= nx < w and cand[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True; q.append((ny, nx))
    alpha = np.where(seen, 0, 255).astype(np.uint8)
    # soften: fade pixels near the background colour on the boundary
    soft = np.clip((dist.astype(np.float32) / (tol * 2.5)) * 255, 0, 255).astype(np.uint8)
    edge = np.asarray(Image.fromarray(alpha).filter(ImageFilter.MaxFilter(3))) > 0
    edge &= np.asarray(Image.fromarray(alpha).filter(ImageFilter.MinFilter(3))) == 0
    alpha = np.where(edge, np.minimum(soft, 255), alpha)
    m = Image.fromarray(alpha).filter(ImageFilter.GaussianBlur(0.6))
    rgba = img.convert("RGBA"); rgba.putalpha(m)
    bbox = rgba.getbbox()
    if bbox:
        rgba = rgba.crop(bbox)
    rgba.thumbnail((900, 900), Image.LANCZOS)
    return rgba


def score(img: Image.Image) -> float:
    """Prefer clean white backdrops and wide (card-shaped) subjects."""
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    whiteness = float((border.min(axis=1) > 240).mean())
    return whiteness


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    cfg = json.loads((ROOT / "data" / "models.json").read_text())
    data = json.loads((ROOT / "data" / "data.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    for m in cfg["models"]:
        mid = m["id"]
        if args and mid not in args:
            continue
        dest = OUT / f"{mid}.png"
        if dest.exists() and not force:
            continue
        if m.get("img_url"):  # a pinned photo always wins
            urls = [m["img_url"]]
        else:
            urls = [big(l["img"]) for l in data["gpus"].get(mid, {}).get("listings", [])]
        best = None
        for u in urls[:8]:
            try:
                im = download(u)
            except Exception as e:  # noqa: BLE001
                print(f"  {mid}: skip {u[:70]}… ({e})"); continue
            s = score(im)
            if best is None or s > best[0]:
                best = (s, u, im)
            if s > 0.98 and min(im.size) >= 600:
                break
        if not best:
            print(f"{mid}: no image"); continue
        cut = cutout(best[2], tol=m.get("img_tol", 18))
        cut.save(dest, optimize=True)
        cut.save(dest.with_suffix(".webp"), quality=86, method=6)  # lightweight copy for the web page
        print(f"{mid}: {cut.size} white={best[0]:.2f} <- {best[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
