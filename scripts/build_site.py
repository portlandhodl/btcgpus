#!/usr/bin/env python3
"""Generate the social unfurl cards and per-model share pages.

  assets/img/og/og.png ........ 1200x630 site card (top 4 models)
  assets/img/og/<id>.png ...... 1200x630 card per GPU
  m/<id>/index.html ........... share URL with model-specific OpenGraph/Twitter
                                tags that forwards to the dashboard (#open=<id>)
  index.html .................. OG tags refreshed with the current headline

Requires Pillow:  pip install pillow
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "assets" / "fonts" / "Inter.ttf"
MONO = ROOT / "assets" / "fonts" / "JetBrainsMono.ttf"
OG = ROOT / "assets" / "img" / "og"
GPU_IMG = ROOT / "assets" / "img" / "gpus"
W, H = 1200, 630

BG = (9, 11, 16)
INK = (240, 239, 236)
INK2 = (170, 172, 180)
MUTED = (110, 114, 124)
ORANGE = (247, 147, 26)
BRAND = {"NVIDIA": (118, 185, 0), "AMD": (237, 28, 36), "Intel": (0, 113, 197)}


def font(size: int, weight: int = 400, mono: bool = False) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(MONO if mono else FONT), size)
    try:
        f.set_variation_by_axes([weight] if mono else [min(32, max(14, size)), weight])
    except Exception:  # noqa: BLE001
        pass
    return f


def latest(series: dict, on: str | None = None):
    keys = [k for k in series if on is None or k <= on]
    return (keys[-1], series[keys[-1]]) if keys else (None, None)


def stats(cfg, data):
    btc = data["btc"]
    bdate, bprice = latest(btc)
    out = []
    for m in cfg["models"]:
        g = data["gpus"].get(m["id"], {})
        rdate, r = latest(g.get("retail", {}))
        price = r[1] if r else None
        launch_btc = latest(btc, m["launch"])[1] or next(iter(btc.values()))
        out.append({
            **m,
            "price": price,
            "ratio": bprice / price if price else None,
            "launch_ratio": launch_btc / m["msrp"],
            "launch_btc": launch_btc,
            "premium": (price / m["msrp"] - 1) if price else None,
        })
    return bdate, bprice, out


def backdrop() -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse((W - 620, -380, W + 380, 520), fill=(120, 62, 8))
    d.ellipse((-420, 330, 380, 1030), fill=(18, 40, 78))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    im = Image.blend(im, glow, 0.55)
    d = ImageDraw.Draw(im)
    for x in range(0, W, 40):
        d.line([(x, 0), (x, H)], fill=(20, 23, 30))
    for y in range(0, H, 40):
        d.line([(0, y), (W, y)], fill=(20, 23, 30))
    return im


def mark(d: ImageDraw.ImageDraw, x: int, y: int, title: str):
    d.rounded_rectangle((x, y, x + 44, y + 44), 10, fill=ORANGE)
    d.text((x + 22, y + 23), "₿", font=font(30, 800), fill=(20, 12, 0), anchor="mm")
    d.text((x + 58, y + 22), title.upper(), font=font(22, 800), fill=INK, anchor="lm")


def paste_gpu(im: Image.Image, mid: str, box: tuple[int, int, int, int]):
    p = GPU_IMG / f"{mid}.png"
    if not p.exists():
        return
    g = Image.open(p).convert("RGBA")
    bw, bh = box[2] - box[0], box[3] - box[1]
    g.thumbnail((bw, bh), Image.LANCZOS)
    x = box[0] + (bw - g.width) // 2
    y = box[1] + (bh - g.height) // 2
    shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sh = Image.new("RGBA", g.size, (0, 0, 0, 0))
    sh.putalpha(g.getchannel("A").point(lambda a: int(a * 0.55)))
    shadow.paste(sh, (x + 8, y + 18))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    im.alpha_composite(shadow)
    im.alpha_composite(g, (x, y))


def fmt_ratio(r: float) -> str:
    return f"{r:,.1f}" if r >= 10 else f"{r:,.2f}"


def site_card(cfg, bdate, bprice, rows, dest: Path):
    im = backdrop().convert("RGBA")
    d = ImageDraw.Draw(im)
    mark(d, 56, 48, cfg["site"]["title"])
    d.text((56, 128), "How many GPUs", font=font(60, 800), fill=INK)
    d.text((56, 196), "does 1 bitcoin buy?", font=font(60, 800), fill=ORANGE)
    d.text((W - 56, 70), f"BTC ${bprice:,.0f}", font=font(30, 700, mono=True), fill=INK, anchor="rm")
    d.text((W - 56, 104), f"updated {bdate}", font=font(18, 400), fill=MUTED, anchor="rm")

    pick = [r for r in rows if r["id"] in ("rtx-5090", "rtx-5080", "rx-9070-xt", "arc-b580")]
    cw, gap, top = 262, 18, 286
    for i, r in enumerate(pick):
        x = 56 + i * (cw + gap)
        card = Image.new("RGBA", (cw, 286), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle((0, 0, cw - 1, 285), 18, fill=(18, 21, 29, 235), outline=(40, 44, 56), width=2)
        im.alpha_composite(card, (x, top))
        paste_gpu(im, r["id"], (x + 16, top + 14, x + cw - 16, top + 132))
        d.rounded_rectangle((x + 18, top + 146, x + 26, top + 166), 3, fill=BRAND[r["brand"]])
        d.text((x + 34, top + 156), r["short"], font=font(24, 700), fill=INK, anchor="lm")
        d.text((x + 18, top + 214), fmt_ratio(r["ratio"]), font=font(52, 700, mono=True), fill=ORANGE, anchor="lm")
        d.text((x + 20, top + 258), f"per BTC · ${r['price']:,.0f}", font=font(19, 500), fill=INK2, anchor="lm")
    d.text((56, H - 26), cfg["site"]["base_url"].replace("https://", ""), font=font(18, 500), fill=MUTED, anchor="ls")
    d.text((W - 56, H - 26), "13 GPUs · NVIDIA · AMD · Intel", font=font(18, 500), fill=MUTED, anchor="rs")
    im.convert("RGB").save(dest, optimize=True)


def model_card(cfg, bdate, bprice, r, dest: Path):
    im = backdrop().convert("RGBA")
    d = ImageDraw.Draw(im)
    mark(d, 56, 48, cfg["site"]["title"])
    paste_gpu(im, r["id"], (560, 110, 1160, 470))
    d.rounded_rectangle((56, 138, 66, 178), 4, fill=BRAND[r["brand"]])
    d.text((80, 158), r["name"], font=font(42, 800), fill=INK, anchor="lm")
    d.text((58, 222), "1 BTC buys", font=font(30, 500), fill=INK2, anchor="lm")
    d.text((52, 312), fmt_ratio(r["ratio"]), font=font(140, 800, mono=True), fill=ORANGE, anchor="lm")
    sats = r["price"] / bprice * 1e8
    d.text((58, 410), f"{sats/1e6:,.2f}M sats each · ${r['price']:,.0f} avg retail", font=font(26, 500), fill=INK, anchor="lm")
    chg = r["ratio"] / r["launch_ratio"] - 1
    col = (12, 163, 12) if chg >= 0 else (230, 103, 103)
    d.text((58, 456), f"At launch ({r['launch']}, ${r['msrp']:,} MSRP): {fmt_ratio(r['launch_ratio'])} per BTC",
           font=font(22, 400), fill=INK2, anchor="lm")
    d.text((58, 494), f"{'▲' if chg >= 0 else '▼'} {abs(chg)*100:,.0f}% purchasing power since launch",
           font=font(24, 700), fill=col, anchor="lm")
    d.text((W - 56, 70), f"BTC ${bprice:,.0f}", font=font(30, 700, mono=True), fill=INK, anchor="rm")
    d.text((W - 56, 104), f"updated {bdate}", font=font(18, 400), fill=MUTED, anchor="rm")
    d.text((56, H - 26), cfg["site"]["base_url"].replace("https://", "") + f"/m/{r['id']}/",
           font=font(18, 500), fill=MUTED, anchor="ls")
    d.text((W - 56, H - 26), f"{r['vram']}GB {r['mem']} · {r['arch']}", font=font(18, 500), fill=MUTED, anchor="rs")
    im.convert("RGB").save(dest, optimize=True)


def meta_block(title, desc, url, image) -> str:
    t, dsc = html.escape(title, True), html.escape(desc, True)
    return f"""<!-- og:start -->
<title>{t}</title>
<meta name="description" content="{dsc}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Sats per Silicon">
<meta property="og:title" content="{t}">
<meta property="og:description" content="{dsc}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{image}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{t}">
<meta name="twitter:description" content="{dsc}">
<meta name="twitter:image" content="{image}">
<!-- og:end -->"""


def model_page(cfg, r, bprice, stamp) -> str:
    base = cfg["site"]["base_url"].rstrip("/")
    url = f"{base}/m/{r['id']}/"
    title = f"1 BTC = {fmt_ratio(r['ratio'])} {r['short']}s · Sats per Silicon"
    desc = (f"{r['name']}: ${r['price']:,.0f} avg US retail, {r['price']/bprice*1e8/1e6:,.2f}M sats. "
            f"At launch 1 BTC bought {fmt_ratio(r['launch_ratio'])}. Charts, stats and sold-price history.")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{meta_block(title, desc, url, f"{base}/assets/img/og/{r['id']}.png?v={stamp}")}
<meta name="theme-color" content="#090b10">
<meta http-equiv="refresh" content="0; url=../../#open={r['id']}">
<style>body{{background:#090b10;color:#f0efec;font:16px system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0}}a{{color:#f7931a}}</style>
</head>
<body><p>Opening <a href="../../#open={r['id']}">{html.escape(r['name'])}</a>…</p>
<script>location.replace('../../#open={r['id']}')</script>
</body>
</html>
"""


def main():
    cfg = json.loads((ROOT / "data" / "models.json").read_text())
    data = json.loads((ROOT / "data" / "data.json").read_text())
    bdate, bprice, rows = stats(cfg, data)
    stamp = data["updated"][:10].replace("-", "")
    OG.mkdir(parents=True, exist_ok=True)
    site_card(cfg, bdate, bprice, rows, OG / "og.png")
    for r in rows:
        if not r["price"]:
            continue
        model_card(cfg, bdate, bprice, r, OG / f"{r['id']}.png")
        p = ROOT / "m" / r["id"] / "index.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(model_page(cfg, r, bprice, stamp))

    # refresh the home page's OG block
    idx = ROOT / "index.html"
    if idx.exists():
        base = cfg["site"]["base_url"].rstrip("/")
        top = next(r for r in rows if r["id"] == "rtx-5090")
        title = f"{cfg['site']['title']}: How many GPUs does 1 BTC buy?"
        desc = (f"Today 1 BTC buys {fmt_ratio(top['ratio'])} RTX 5090s. Interactive BTC/GPU ratio charts for "
                "RTX 50, Radeon RX 9000 and Intel Arc: price history, eBay sold data, stats.")
        block = meta_block(title, desc, base + "/", f"{base}/assets/img/og/og.png?v={stamp}")
        s = idx.read_text()
        s = re.sub(r"<!-- og:start -->.*?<!-- og:end -->", lambda _: block, s, flags=re.S)
        idx.write_text(s)
    print(f"built cards for {len(rows)} models, BTC ${bprice:,.0f} on {bdate}")


if __name__ == "__main__":
    main()
