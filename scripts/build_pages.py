#!/usr/bin/env python3
"""Pre-render the site for speed and search.

Run by build_site.py after the share cards are drawn (or on its own):

  index.html ............. head block (meta, inlined CSS, preloads, JSON-LD) and the
                           above-the-fold content (hero, ticker, lineup, leaderboard,
                           cloud table, FAQ) rendered from today's data, so the page
                           paints before any JavaScript runs. app.js re-renders the
                           same markup on load.
  m/<id>/index.html ...... a real, indexable landing page per GPU: answer, stats,
                           static SVG history chart, monthly table, listings, FAQ,
                           related GPUs, structured data. No JavaScript.
  assets/img/gpus/<id>-480.webp, <id>-160.webp ... resized photos
  sitemap.xml, robots.txt, llms.txt, 404.html

Stdlib + Pillow only.
"""
from __future__ import annotations

import bisect
import datetime as dt
import hashlib
import html
import json
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
GPU_IMG = ROOT / "assets" / "img" / "gpus"
GOOD, BAD = "#0ca30c", "#e66767"
SLOTS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c", "#9085e9", "#e66767"]
DEFAULT_SEL = ["rtx-5090", "rtx-5080", "rx-9070-xt", "arc-b580"]
CATS = {"gaming": "Gaming", "workstation": "Workstation", "datacenter": "Data center", "system": "AI system"}
PRICE_KIND = {
    "retail": ("Retail avg", "average US retail price"),
    "ask": ("Lowest asks", "average of the 3 cheapest eBay/Amazon asking prices"),
    "list": ("List price", "official list price"),
}
CLOUD = [("h100-sxm-80gb", "H100 SXM"), ("h200-sxm", "H200 SXM"), ("b200-sxm", "B200"), ("b300-sxm", "B300"),
         ("mi300x", "MI300X"), ("rtx-pro-6000-blackwell", "RTX PRO 6000"), ("a100-sxm-80gb", "A100 SXM"), ("rtx-5090", "RTX 5090")]
HERO_ID = "rtx-5090"
LAZY = 'loading="lazy"'
VARIANTS = (160, 320, 480, 640)
HERO_SIZES = "(max-width: 600px) 82vw, (max-width: 980px) 560px, 580px"
CARD_SIZES = "(max-width: 600px) 44vw, 230px"
esc = lambda s: html.escape(str(s), True)  # noqa: E731


# ----------------------------------------------------------------- formatting (mirrors app.js)
def num(v, d=1):
    return "–" if v is None else f"{v:,.{d}f}"


def ratio(v):
    return "–" if v is None else num(v, 2) if v < 10 else num(v, 1) if v < 1000 else num(v, 0)


def sats(v):
    if v is None:
        return "–"
    return num(v / 1e6, 2) + "M" if v >= 1e6 else num(v / 1e3, 1) + "k" if v >= 1e3 else num(v, 0)


def usd(v, d=0):
    return "–" if v is None else "$" + num(v, d)


def pct(v, d=0):
    return "–" if v is None else ("+" if v >= 0 else "−") + num(abs(v) * 100, d) + "%"


def cls(v):
    return "" if v is None else "up" if v >= 0 else "down"


def add_days(iso, n):
    return (dt.date.fromisoformat(iso) + dt.timedelta(days=n)).isoformat()


def fmt_date(iso):
    d = dt.date.fromisoformat(iso[:10])
    return f"{d:%b} {d.day}, {d.year}"


def article(name):
    """'an' for names that start with a vowel sound, read as letters for initialisms (an RTX 5090, an H100, a DGX Spark)."""
    w = name.split()[0]
    initialism = w.isupper() or any(c.isdigit() for c in w)
    return "an" if (w[0] in "AEFHILMNORSX" if initialism else w[0].lower() in "aeiou") else "a"


def plural(short):
    return short if short.endswith("s") else short + "s"


# ----------------------------------------------------------------- model stats (mirrors prep() in app.js)
class Btc:
    def __init__(self, series: dict):
        self.d = sorted(series)
        self.p = [series[k] for k in self.d]

    def at(self, iso):
        if iso < self.d[0]:
            return self.p[0]
        return self.p[bisect.bisect_right(self.d, iso) - 1]

    @property
    def last(self):
        return self.d[-1]

    @property
    def now(self):
        return self.p[-1]


def prep(cfg, data):
    btc = Btc(data["btc"])
    last = btc.last
    out = []
    for m in cfg["models"]:
        g = data["gpus"].get(m["id"]) or {"retail": {}, "used": {}, "listings": []}
        retail = [(d, v[0], v[1]) for d, v in sorted(g.get("retail", {}).items())]
        if m.get("list_history"):
            steps = sorted(m["list_history"])
            retail, i, d = [], 0, steps[0][0]
            while d <= last:
                while i + 1 < len(steps) and steps[i + 1][0] <= d:
                    i += 1
                retail.append((d, steps[i][1], steps[i][1]))
                d = add_days(d, 1)
        used_k = sorted(g.get("used") or {})
        used = {"date": used_k[-1], **g["used"][used_k[-1]]} if used_k else None
        cur = retail[-1] if retail else None
        kind = "list" if m.get("list_history") else "ask" if (m.get("src") or {}).get("gpupoet") else "retail"
        o = dict(m, kind=kind, retail=retail, used=used, listings=g.get("listings") or [])
        o["price"] = cur[2] if cur else None
        o["low"] = cur[1] if cur else None
        o["ratio"] = btc.now / o["price"] if o["price"] else None
        o["sats"] = o["price"] / btc.now * 1e8 if o["price"] else None
        o["launch_btc"] = btc.at(m["launch"])
        o["launch_ratio"] = o["launch_btc"] / m["msrp"]
        o["since_launch"] = o["ratio"] / o["launch_ratio"] - 1 if o["ratio"] else None
        o["premium"] = o["price"] / m["msrp"] - 1 if o["price"] else None
        o["sats_gb"] = o["sats"] / m["vram"] if o["sats"] else None
        gpb = [(d, btc.at(d) / av) for d, _, av in retail]
        if o["ratio"] and cur and cur[0] < last:
            gpb.append((last, o["ratio"]))
        o["gpb"] = gpb

        def ago(n, gpb=gpb, cur=cur):
            t = add_days(cur[0] if cur else last, -n)
            p = [v for d, v in gpb if d <= t]
            return p[-1] if p else None
        o["chg30"] = o["ratio"] / ago(30) - 1 if o["ratio"] and ago(30) else None
        o["chg7"] = o["ratio"] / ago(7) - 1 if o["ratio"] and ago(7) else None
        o["ath"] = max(gpb, key=lambda x: x[1]) if gpb else None
        o["atl"] = min(gpb, key=lambda x: x[1]) if gpb else None
        out.append(o)
    return btc, out


def cloud_now(data, slug):
    c = (data.get("cloud") or {}).get(slug)
    if not c or not c["series"]:
        return None
    k = sorted(c["series"])
    mn, med, prov = c["series"][k[-1]][:3]
    return {"date": k[-1], "min": mn, "med": med, "prov": prov, "name": c.get("name", slug), "keys": k, "series": c["series"]}


# ----------------------------------------------------------------- assets
def file_hash(p: Path) -> str:
    return hashlib.sha1(p.read_bytes()).hexdigest()[:10]


def make_variants(models) -> dict:
    """Resized webp copies: 160w table thumbs, 320/480w cards, 640w hero on phones. Returns id -> [w, h] of the 480 copy."""
    dims = {}
    for m in models:
        src = GPU_IMG / f"{m['id']}.webp"
        if not src.exists():
            src = GPU_IMG / f"{m['id']}.png"
        if not src.exists():
            continue
        for w in VARIANTS:
            dst = GPU_IMG / f"{m['id']}-{w}.webp"
            if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
                im = Image.open(src).convert("RGBA")
                if im.width > w:
                    im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
                im.save(dst, "WEBP", quality=78, alpha_quality=80, method=6)
        with Image.open(GPU_IMG / f"{m['id']}-480.webp") as im:
            dims[m["id"]] = [im.width, im.height]
    return dims


def minify_css(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*([{};,>])\s*", r"\1", s)
    s = re.sub(r":\s+", ":", s)
    return s.replace(";}", "}").strip()


def inline_css(root: str) -> str:
    css = minify_css((ROOT / "assets" / "css" / "style.css").read_text())
    return css.replace("url(../", f"url({root}assets/")


def jsonld(obj) -> str:
    return '<script type="application/ld+json">' + json.dumps(obj, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/") + "</script>"


def meta_block(site, title, desc, url, image, image_alt) -> str:
    t, d = esc(title), esc(desc)
    tw = site.get("twitter")
    return f"""<title>{t}</title>
<meta name="description" content="{d}">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{esc(site['title'])}">
<meta property="og:locale" content="en_US">
<meta property="og:title" content="{t}">
<meta property="og:description" content="{d}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{image}">
<meta property="og:image:secure_url" content="{image}">
<meta property="og:image:type" content="image/jpeg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{esc(image_alt)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{t}">
<meta name="twitter:description" content="{d}">
<meta name="twitter:image" content="{image}">
<meta name="twitter:image:alt" content="{esc(image_alt)}">""" + (f'\n<meta name="twitter:creator" content="{esc(tw)}">' if tw else "")


def common_head(root: str) -> str:
    return f"""<meta name="theme-color" content="#090b10">
<meta name="color-scheme" content="dark">
<link rel="icon" href="{root}assets/img/favicon.svg" type="image/svg+xml">
<link rel="icon" href="{root}favicon.ico" sizes="32x32">
<link rel="apple-touch-icon" href="{root}assets/img/apple-touch-icon.png">
<link rel="manifest" href="{root}site.webmanifest">
<link rel="preload" href="{root}assets/fonts/inter-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="{root}assets/fonts/jbmono-latin.woff2" as="font" type="font/woff2" crossorigin>"""


# ----------------------------------------------------------------- home page fragments
def spark(o) -> str:
    pts = o["gpb"][-90:]
    if len(pts) < 2:
        return ""
    vs = [v for _, v in pts]
    lo, hi, w, h = min(vs), max(vs), 180, 34
    xy = [((i / (len(pts) - 1)) * w, h - 3 - ((v - lo) / ((hi - lo) or 1)) * (h - 6)) for i, v in enumerate(vs)]
    d = "".join(("L" if i else "M") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(xy))
    col = GOOD if vs[-1] >= vs[0] else BAD
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">'
            f'<path d="{d}L{w} {h}L0 {h}Z" fill="{col}" opacity=".10"/><path d="{d}" fill="none" stroke="{col}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>')


def img(id_, alt, size, dims, root="", extra="", defer=False):
    d = dims.get(id_)
    wh = f' width="{size}" height="{round(d[1] / d[0] * size)}"' if d else ""
    p = f"{root}assets/img/gpus/{id_}"
    ss = f' srcset="{p}-320.webp 320w, {p}-480.webp 480w" sizes="{CARD_SIZES}"' if size == 480 else ""
    if defer:  # home page: no request until app.js hydrates, so photos never compete with first paint
        return f'<img data-src="{p}-{size}.webp"{wh} alt="{esc(alt)}" decoding="async">'
    return f'<img src="{p}-{size}.webp"{ss}{wh} alt="{esc(alt)}" decoding="async" {extra}>'


def wall_html(rows, dims) -> str:
    out = []
    for o in rows:
        on = o["id"] in DEFAULT_SEL
        col = SLOTS[DEFAULT_SEL.index(o["id"])] if on else "transparent"
        tag = f'<span class="tag">{CATS[o["category"]]}</span>' if o["category"] != "gaming" else ""
        out.append(f"""
      <div class="card{' on' if on else ''}" data-id="{o['id']}" data-brand="{o['brand']}" style="--sc:{col}">
        <button class="add" type="button" aria-pressed="{'true' if on else 'false'}" aria-label="Add {esc(o['short'])} to chart" title="Add to chart">{'✓' if on else '＋'}</button>
        <div class="img">{img(o['id'], o['name'], 480, dims, defer=True)}</div>
        {tag}
        <div class="name"><i class="b-{o['brand']}"></i><a href="m/{o['id']}/">{esc(o['short'])}</a></div>
        <div class="big">{ratio(o['ratio'])}<small>per BTC</small></div>
        <div class="meta"><span>{usd(o['price'])} · {sats(o['sats'])} sats</span><span class="{cls(o['chg30'])}">{pct(o['chg30'], 1)} 30d</span></div>
        {spark(o)}
      </div>""")
    return "".join(out) + "\n    "


LB_HEAD = ["GPU", "VRAM", "MSRP", "Price now", "Lowest", "eBay sold", "vs MSRP", "GPUs / BTC", "Sats each", "Sats / GB", "30d", "Since launch"]
LB_KEYS = ["name", "vram", "msrp", "price", "low", "used", "premium", "ratio", "sats", "satsPerGB", "chg30", "sinceLaunch"]


def lb_html(rows, dims) -> str:
    srt = sorted(rows, key=lambda o: (o["ratio"] is None, -(o["ratio"] or 0)))
    max_r = max(o["ratio"] or 0 for o in rows)
    srt_attr = ' aria-sort="descending"'
    head = "".join(f'<th data-k="{k}"{srt_attr if k == "ratio" else ""} tabindex="0">{h}</th>' for k, h in zip(LB_KEYS, LB_HEAD))
    body = []
    for o in srt:
        tag = f'<span class="tag">{CATS[o["category"]]}</span>' if o["category"] != "gaming" else ""
        sup = f'<sup class="k-{o["kind"]}">{"L" if o["kind"] == "list" else "A"}</sup>' if o["kind"] != "retail" else ""
        cells = [
            f'<span class="m">{img(o["id"], "", 160, dims, defer=True)}<i class="b-{o["brand"]}"></i><a href="m/{o["id"]}/">{esc(o["short"])}</a>{tag}</span>',
            f'{o["vram"]} GB', usd(o["msrp"]) + ("*" if o.get("msrp_est") else ""),
            f'<span title="{PRICE_KIND[o["kind"]][1]}">{usd(o["price"])}{sup}</span>',
            usd(o["low"]) if o["kind"] == "retail" else "–",
            usd(o["used"]["median"]) if o["used"] else "–",
            f'<span class="{"down" if (o["premium"] or 0) > 0 else "up"}">{pct(o["premium"])}</span>',
            None, sats(o["sats"]), sats(o["sats_gb"]),
            f'<span class="{cls(o["chg30"])}">{pct(o["chg30"], 1)}</span>',
            f'<span class="{cls(o["since_launch"])}">{pct(o["since_launch"])}</span>',
        ]
        tds = []
        for c in cells:
            if c is None:
                tds.append(f'<td class="bar-cell"><b>{ratio(o["ratio"])}</b><span class="bar" style="width:{max(4, (o["ratio"] or 0) / max_r * 90):.2f}px"></span></td>')
            else:
                tds.append(f"<td>{c}</td>")
        body.append(f'<tr data-id="{o["id"]}" tabindex="0">{"".join(tds)}</tr>')
    return f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"


def cloud_rows(data, btc):
    rows = []
    for slug, name in CLOUD:
        c = cloud_now(data, slug)
        if not c:
            continue
        h = btc.now / c["med"]
        t = add_days(c["date"], -30)
        old = [k for k in c["keys"] if k <= t]
        oh = btc.at(old[-1]) / c["series"][old[-1]][1] if old else None
        rows.append((slug, c, h, h / oh - 1 if oh else None))
    return rows


def cloud_html(data, btc) -> str:
    body = []
    for slug, c, h, chg in cloud_rows(data, btc):
        col = SLOTS[[s for s, _ in CLOUD].index(slug)]
        body.append(f'<tr><td><span class="m"><i class="sw" style="background:{col};width:10px"></i>{esc(c["name"])}</span></td><td>{usd(c["med"], 2)}</td><td>{usd(c["min"], 2)}</td>'
                    f'<td>{c["prov"]}</td><td><b>{num(h, 0)}</b></td><td>{num(h / 24, 1)}</td><td class="{cls(chg)}">{pct(chg, 1) if chg is not None else "–"}</td></tr>')
    return ("<thead><tr><th>Cloud GPU</th><th>Median $/hr</th><th>Cheapest $/hr</th><th>Providers</th><th>GPU-hours / BTC</th><th>Days of 24/7 / BTC</th><th>30d</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody>")


def hero_html(o, dims) -> dict:
    kind = "list price" if o["kind"] == "list" else "lowest asks" if o["kind"] == "ask" else "avg retail"
    d = dims.get(o["id"], [480, 300])
    return {
        "heroNum": ratio(o["ratio"]),
        "heroModel": o["short"] + ("s" if o["ratio"] >= 2 else ""),
        "heroSub": f"{usd(o['price'])} {kind} · {sats(o['sats'])} sats each",
        "heroNote": (f"At launch on {fmt_date(o['launch'])}, 1&nbsp;BTC bought <b>{ratio(o['launch_ratio'])}</b> at the {usd(o['msrp'])} "
                     f"{'estimated launch price' if o.get('msrp_est') else 'MSRP'}. Bitcoin's GPU purchasing power is "
                     f"<b class=\"{cls(o['since_launch'])}\">{pct(o['since_launch'])}</b> since then."),
        "heroImg": (f'<img id="heroImg" alt="{esc(o["name"])}" data-id="{o["id"]}" src="assets/img/gpus/{o["id"]}.webp" '
                    f'srcset="assets/img/gpus/{o["id"]}-480.webp 480w, assets/img/gpus/{o["id"]}-640.webp 640w, assets/img/gpus/{o["id"]}.webp 900w" '
                    f'sizes="{HERO_SIZES}" width="{d[0]}" height="{d[1]}" fetchpriority="high" decoding="async">'),
    }


def home_faq(rows, by, btc, data, upd):
    def r(i):
        return ratio(by[i]["ratio"]) if i in by and by[i]["ratio"] else "–"
    priced = [o for o in rows if o["ratio"]]
    cheapest = max(priced, key=lambda o: o["ratio"])
    vram = min(priced, key=lambda o: o["sats_gb"])
    up = [o for o in priced if (o["since_launch"] or 0) >= 0]
    h100 = cloud_now(data, "h100-sxm-80gb")
    qa = [
        ("How many GPUs does 1 bitcoin buy today?",
         f"As of {upd}, with bitcoin at {usd(btc.now)}, 1 BTC buys {r('rtx-5090')} RTX 5090s, {r('rtx-5080')} RTX 5080s, "
         f"{r('rx-9070-xt')} Radeon RX 9070 XTs, {r('arc-b580')} Intel Arc B580s, {r('h100-pcie')} H100 PCIe cards and {r('dgx-spark')} DGX Sparks."),
        ("Which GPU is cheapest in bitcoin?",
         f"Of the {len(priced)} GPUs tracked, the {cheapest['name']} is cheapest at {sats(cheapest['sats'])} sats ({ratio(cheapest['ratio'])} per BTC). "
         f"For memory, the {vram['name']} costs the fewest sats per GB of VRAM: {sats(vram['sats_gb'])} sats per GB."),
        ("Does bitcoin buy more or fewer GPUs than at launch?",
         f"Bitcoin buys more today than at launch for {len(up)} of {len(priced)} GPUs. The RTX 5090 is {pct(by['rtx-5090']['since_launch'])} "
         f"since launch: 1 BTC bought {ratio(by['rtx-5090']['launch_ratio'])} at its {usd(by['rtx-5090']['msrp'])} MSRP and buys {r('rtx-5090')} now."),
    ]
    if h100:
        qa.append(("How many H100 GPU-hours does 1 bitcoin rent?",
                   f"At the median on-demand price of {usd(h100['med'], 2)} per hour across {h100['prov']} cloud providers, "
                   f"1 BTC rents about {num(btc.now / h100['med'], 0)} H100 SXM GPU-hours, roughly {num(btc.now / h100['med'] / 24 / 365, 1)} years of one GPU running 24/7."))
    qa += [
        ("What does sats per GPU mean?",
         "A sat (satoshi) is one hundred-millionth of a bitcoin. Sats per GPU is a card's US dollar price divided by the BTC/USD price, times 100,000,000: "
         "what the GPU costs when you pay in bitcoin."),
        ("Where do the prices come from, and how often are they updated?",
         "Bitcoin closes come from Binance (Coinbase fallback). New GPU prices are US retail averages from gpupricehistory.com, used prices are 90-day eBay sold "
         "medians from pcprice.watch, workstation and data-center cards use the cheapest eBay/Amazon asks from GPU Poet, and cloud rental prices come from GPUPerHour. "
         "Data refreshes automatically several times a day and the archive only grows."),
    ]
    return qa


def faq_html(qa) -> str:
    return "".join(f"\n      <details{' open' if i == 0 else ''}><summary><h3>{esc(q)}</h3></summary><p>{esc(a)}</p></details>" for i, (q, a) in enumerate(qa)) + "\n    "


def faq_ld(qa):
    return {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in qa]}


def set_block(s: str, name: str, content: str) -> str:
    pat = re.compile(rf"(<!-- pre:{name} -->).*?(<!-- /pre:{name} -->)", re.S)
    if not pat.search(s):
        raise SystemExit(f"index.html is missing the pre:{name} markers")
    return pat.sub(lambda m: m.group(1) + content + m.group(2), s)


def build_home(cfg, data, btc, rows, dims, stamp):
    site, base = cfg["site"], cfg["site"]["base_url"].rstrip("/")
    by = {o["id"]: o for o in rows}
    upd_dt = dt.datetime.fromisoformat(data["updated"].replace("Z", "+00:00"))
    upd = fmt_date(upd_dt.date().isoformat())
    top = by[HERO_ID]
    title = "How Many GPUs Does 1 Bitcoin Buy? Live BTC/GPU Tracker"
    desc = (f"Today 1 BTC buys {ratio(top['ratio'])} RTX 5090s. Live bitcoin vs GPU prices for RTX 50, Radeon RX 9000, Intel Arc, RTX PRO, "
            "H100/H200, MI300X, DGX Spark and Strix Halo, plus cloud GPU-hours per BTC.")
    qa = home_faq(rows, by, btc, data, upd)
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "WebSite", "@id": base + "/#website", "url": base + "/", "name": site["title"], "description": site["tagline"], "inLanguage": "en"},
        {"@type": "WebPage", "@id": base + "/#page", "url": base + "/", "name": title, "description": desc, "isPartOf": {"@id": base + "/#website"},
         "dateModified": data["updated"], "primaryImageOfPage": f"{base}/assets/img/og/og.jpg"},
        {"@type": "Dataset", "name": "Sats per Silicon: GPU prices in bitcoin",
         "description": "Daily BTC/USD closes with US retail, used (eBay sold) and asking prices for consumer, workstation and data-center GPUs, "
                        "plus daily cloud GPU rental prices, used to compute how many GPUs one bitcoin buys.",
         "url": base + "/", "keywords": ["bitcoin", "GPU prices", "RTX 5090", "H100", "sats", "BTC/GPU ratio", "cloud GPU pricing"],
         "temporalCoverage": f"{btc.d[0]}/{btc.last}", "dateModified": data["updated"], "isAccessibleForFree": True,
         "creator": {"@type": "Person", "name": site.get("author", "Portland.HODL"), "url": site.get("author_url", "https://github.com/portlandhodl")},
         "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": base + "/data/data.json"}]},
        {"@type": "ItemList", "name": "GPUs priced in bitcoin", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "url": f"{base}/m/{o['id']}/", "name": o["name"]}
            for i, o in enumerate(sorted([o for o in rows if o["ratio"]], key=lambda o: -o["ratio"]))]},
        faq_ld(qa),
    ]}
    hero = hero_html(top, dims)
    app_v = file_hash(ROOT / "assets" / "js" / "app.js")
    ec_v = file_hash(ROOT / "assets" / "vendor" / "echarts.custom.min.js")
    cfg_inline = dict(cfg, img=dims)
    head = f"""<!-- head:start -->
{meta_block(site, title, desc, base + "/", f"{base}/assets/img/og/og.jpg?v={stamp}", "How many GPUs 1 bitcoin buys today: RTX 5090, RTX 5080, RX 9070 XT and Arc B580")}
{common_head("")}
<link rel="preload" as="image" href="assets/img/gpus/{HERO_ID}.webp" imagesrcset="assets/img/gpus/{HERO_ID}-480.webp 480w, assets/img/gpus/{HERO_ID}-640.webp 640w, assets/img/gpus/{HERO_ID}.webp 900w" imagesizes="{HERO_SIZES}" fetchpriority="high">
<style>{inline_css("")}</style>
<meta name="echarts-src" content="assets/vendor/echarts.custom.min.js?v={ec_v}">
<script src="assets/js/app.js?v={app_v}" defer></script>
<script id="cfg" type="application/json">{json.dumps(cfg_inline, separators=(",", ":")).replace("</", "<\\/")}</script>
{jsonld(ld)}
<!-- head:end -->"""
    idx = ROOT / "index.html"
    s = idx.read_text()
    s = re.sub(r"<!-- head:start -->.*?<!-- head:end -->", lambda _: head, s, flags=re.S)
    prev = btc.at(add_days(btc.last, -1))
    chg = btc.now / prev - 1
    for k in ("heroNum", "heroModel", "heroSub", "heroNote", "heroImg"):
        s = set_block(s, k, hero[k])
    s = set_block(s, "btcPrice", usd(btc.now))
    s = set_block(s, "btcChg", f'<span class="ticker-chg mono {cls(chg)}" id="btcChg">{pct(chg, 1)}</span>')
    s = set_block(s, "updated", f'<time datetime="{data["updated"]}">{upd}</time>')
    s = set_block(s, "footUpdated", "Data updated " + upd_dt.strftime("%a, %d %b %Y %H:%M:%S UTC"))
    s = set_block(s, "wall", wall_html(rows, dims))
    s = set_block(s, "lb", lb_html(rows, dims))
    s = set_block(s, "cloud", cloud_html(data, btc))
    s = set_block(s, "tmDate", fmt_date(btc.last))
    s = set_block(s, "tmBtc", "BTC " + usd(btc.now))
    s = set_block(s, "faq", faq_html(qa))
    idx.write_text(s)


# ----------------------------------------------------------------- model pages
def nice_ticks(lo, hi, n=4):
    span = hi - lo or 1
    raw = span / n
    mag = 10 ** int(f"{raw:e}".split("e")[1])
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    t = (lo // step + 1) * step
    out = []
    while t < hi:
        out.append(t)
        t += step
    return out


def svg_chart(o, btc) -> str:
    """Static GPUs-per-BTC chart: at MSRP since launch (dashed) and at street price (solid)."""
    start = max(o["launch"], btc.d[0])
    msrp = [(d, p / o["msrp"]) for d, p in zip(btc.d, btc.p) if d >= start]
    step = max(1, len(msrp) // 260)
    msrp = msrp[::step] + ([msrp[-1]] if msrp and msrp[-1] != msrp[::step][-1] else [])
    street = o["gpb"]
    if len(msrp) < 2:
        return ""
    W, H, L, R, T, B = 800, 300, 52, 16, 14, 30
    x0, x1 = dt.date.fromisoformat(msrp[0][0]).toordinal(), dt.date.fromisoformat(btc.last).toordinal()
    vals = [v for _, v in msrp] + [v for _, v in street]
    lo, hi = min(vals) * 0.92, max(vals) * 1.06
    X = lambda d: L + (dt.date.fromisoformat(d).toordinal() - x0) / ((x1 - x0) or 1) * (W - L - R)  # noqa: E731
    Y = lambda v: T + (1 - (v - lo) / (hi - lo)) * (H - T - B)  # noqa: E731
    path = lambda pts: "".join(("L" if i else "M") + f"{X(d):.1f} {Y(v):.1f}" for i, (d, v) in enumerate(pts))  # noqa: E731
    g = []
    for t in nice_ticks(lo, hi):
        g.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="var(--grid)"/><text x="{L - 8}" y="{Y(t) + 4:.1f}" text-anchor="end">{num(t, 0 if t >= 10 else 1)}</text>')
    d0, d1 = dt.date.fromordinal(x0), dt.date.fromordinal(x1)
    months = (d1.year - d0.year) * 12 + d1.month - d0.month
    every = max(1, round(months / 5))
    y_, m_ = (d0.year + 1, 1) if d0.month == 12 else (d0.year, d0.month + 1)
    i = 0
    while (y_, m_) <= (d1.year, d1.month):
        if i % every == 0:
            iso = f"{y_}-{m_:02d}-01"
            g.append(f'<text x="{X(iso):.1f}" y="{H - 8}" text-anchor="middle">{dt.date(y_, m_, 1):%b %Y}</text>')
        m_ += 1
        if m_ > 12:
            y_, m_ = y_ + 1, 1
        i += 1
    label = f"GPUs per bitcoin for the {o['name']} since launch"
    lines = [f'<path d="{path(msrp)}" fill="none" stroke="var(--muted)" stroke-width="1.6" stroke-dasharray="4 4"/>']
    if len(street) > 1:
        sp = path(street)
        lines.append(f'<path d="{sp}L{X(street[-1][0]):.1f} {H - B}L{X(street[0][0]):.1f} {H - B}Z" fill="var(--s1)" opacity=".12"/>')
        lines.append(f'<path d="{sp}" fill="none" stroke="var(--s1)" stroke-width="2.2"/>')
    end = street[-1] if street else msrp[-1]
    lines.append(f'<circle cx="{X(end[0]):.1f}" cy="{Y(end[1]):.1f}" r="4.5" fill="var(--accent)"/>')
    return (f'<svg class="svgchart" viewBox="0 0 {W} {H}" role="img" aria-labelledby="chT chD"><title id="chT">{esc(label)}</title>'
            f'<desc id="chD">At launch MSRP 1 BTC bought {ratio(o["launch_ratio"])}; today at {PRICE_KIND[o["kind"]][1]} it buys {ratio(o["ratio"])}.</desc>'
            + "".join(g) + "".join(lines) + "</svg>")


def monthly_rows(o, btc, limit=24):
    out = []
    first_retail = o["retail"][0][0] if o["retail"] else None
    rmap = {d: av for d, _, av in o["retail"]}
    rkeys = sorted(rmap)
    d = dt.date.fromisoformat(btc.last)
    launch = dt.date.fromisoformat(max(o["launch"], btc.d[0]))
    while (d.year, d.month) >= (launch.year, launch.month) and len(out) < limit:
        iso = d.isoformat()
        b = btc.at(iso)
        if first_retail and iso >= first_retail:
            k = rkeys[bisect.bisect_right(rkeys, iso) - 1]
            price, basis = rmap[k], PRICE_KIND[o["kind"]][0]
        else:
            price, basis = o["msrp"], "MSRP" if not o.get("msrp_est") else "Est. launch price"
        out.append((iso, b, price, basis, b / price))
        d = d.replace(day=1) - dt.timedelta(days=1)  # last day of the previous month
    return out


def ext_links(o):
    q = o["name"].replace(" ", "+")
    if o["category"] == "gaming":
        L = [("eBay sold listings", f"https://www.ebay.com/sch/i.html?_nkw={q}&_sacat=27386&LH_Sold=1&LH_Complete=1&_sop=13"),
             ("pcprice.watch used prices", f"https://www.pcprice.watch/gpu-buying-guide/{o['id']}-price-used-and-specs"),
             ("GPU Price History", f"https://gpupricehistory.com/us/{o['id']}"),
             ("Best Value GPU history", f"https://bestvaluegpu.com/history/new-and-used-{o['id']}-price-history-and-specs/")]
    else:
        gp = (o.get("src") or {}).get("gpupoet")
        L = ([("eBay sold listings", f"https://www.ebay.com/sch/i.html?_nkw={q}&LH_Sold=1&LH_Complete=1&_sop=13")] if o["category"] != "system" else []) + \
            ([("GPU Poet listings", f"https://gpupoet.com/gpu/shop/{gp}")] if gp else [])
    L.append(("TechPowerUp specs", f"https://www.techpowerup.com/gpu-specs/?q={o['short'].replace(' ', '+')}"))
    return L


def model_faq(o, btc, data, upd):
    kind = PRICE_KIND[o["kind"]][1]
    s_ = plural(o["short"])
    qa = [
        (f"How many {s_} does 1 bitcoin buy?",
         f"As of {upd}, 1 BTC ({usd(btc.now)}) buys {ratio(o['ratio'])} {o['name']} cards at the {usd(o['price'])} {kind}."),
        (f"How much is {article(o['short'])} {o['short']} in bitcoin?",
         f"The {o['name']} costs {sats(o['sats'])} sats, or {num(o['sats'] / 1e8, 4)} BTC, at {usd(o['price'])} with bitcoin at {usd(btc.now)}."),
        (f"How many {s_} did 1 BTC buy at launch?",
         f"On launch day, {fmt_date(o['launch'])}, bitcoin closed at {usd(o['launch_btc'])}, so 1 BTC bought {ratio(o['launch_ratio'])} at the "
         f"{usd(o['msrp'])} {'estimated launch price' if o.get('msrp_est') else 'MSRP'}. Bitcoin's purchasing power in {s_} is {pct(o['since_launch'])} since then."),
    ]
    if o["used"]:
        u = o["used"]
        qa.append((f"How much does a used {o['short']} sell for?",
                   f"The 90-day median eBay sold price is {usd(u['median'])} across {u['sales']} completed sales (typical range {usd(u['low'])}–{usd(u['high'])}), "
                   f"or {sats(u['median'] / btc.now * 1e8)} sats."))
    c = o.get("cloud") and cloud_now(data, o["cloud"])
    if c and o["price"]:
        be = o["price"] / c["med"]
        qa.append((f"Is it cheaper to rent or buy {article(o['short'])} {o['short']}?",
                   f"Cloud rental costs a median {usd(c['med'], 2)} per hour across {c['prov']} providers, so 1 BTC rents about {num(btc.now / c['med'], 0)} GPU-hours. "
                   f"Buying at {usd(o['price'])} pays off after about {num(be, 0)} rented hours, roughly {num(be / 24 / 30.4, 1)} months of 24/7 use."))
    return qa


def topbar(root, btc, chg):
    return f"""<header class="topbar">
  <div class="wrap topbar-in">
    <a class="brand" href="{root}" aria-label="Sats per Silicon home">
      <span class="brand-mark" aria-hidden="true">₿</span>
      <span class="brand-name">Sats per Silicon</span>
    </a>
    <div class="ticker"><span class="ticker-label">BTC</span><span class="ticker-val mono">{usd(btc.now)}</span><span class="ticker-chg mono {cls(chg)}">{pct(chg, 1)}</span></div>
    <nav class="topnav" aria-label="Sections"><a href="{root}#chart">Chart</a><a href="{root}#leaderboard">Leaderboard</a><a href="{root}#rent">Rent</a><a href="{root}#faq">FAQ</a></nav>
  </div>
</header>"""


def model_page(cfg, data, btc, o, rows, dims, stamp, upd) -> str:
    site, base, root = cfg["site"], cfg["site"]["base_url"].rstrip("/"), "../../"
    url = f"{base}/m/{o['id']}/"
    s_ = plural(o["short"])
    kind = PRICE_KIND[o["kind"]][1]
    title = f"How Many {s_} Does 1 Bitcoin Buy? Price in BTC & Sats"
    desc = (f"1 BTC buys {ratio(o['ratio'])} {s_} today ({usd(o['price'])}, {sats(o['sats'])} sats). At launch it bought {ratio(o['launch_ratio'])}. "
            f"{o['name']} price history in bitcoin, used eBay prices{', cloud rental' if o.get('cloud') else ''} and specs.")
    prev = btc.at(add_days(btc.last, -1))
    chg = btc.now / prev - 1
    qa = model_faq(o, btc, data, upd)
    d = dims.get(o["id"], [480, 300])
    cat = CATS[o["category"]]
    lede = (f"The {o['name']} costs {usd(o['price'])} ({kind}) as of {upd}. With bitcoin at {usd(btc.now)}, that is {sats(o['sats'])} sats "
            f"({num(o['sats'] / 1e8, 4)} BTC) per card, so one bitcoin buys {ratio(o['ratio'])}. "
            f"At launch on {fmt_date(o['launch'])} one bitcoin bought {ratio(o['launch_ratio'])} at the {usd(o['msrp'])} "
            f"{'estimated launch price' if o.get('msrp_est') else 'MSRP'}, so bitcoin's {o['short']} purchasing power is {pct(o['since_launch'])} since launch.")
    stats = [
        (PRICE_KIND[o["kind"]][0], usd(o["price"])),
        ("Lowest US retail listing", usd(o["low"])) if o["kind"] == "retail" else None,
        ("Price in sats", f"{sats(o['sats'])} sats"),
        ("Price in BTC", f"{num(o['sats'] / 1e8, 4)} BTC"),
        ("GPUs per BTC", ratio(o["ratio"])),
        ("Change, 30 days", pct(o["chg30"], 1)),
        ("Change since launch", pct(o["since_launch"])),
        ("Price vs MSRP", pct(o["premium"])),
        ("Sats per GB of VRAM", sats(o["sats_gb"])),
        ("Best ratio tracked", f"{ratio(o['ath'][1])} on {fmt_date(o['ath'][0])}" if o["ath"] else None),
        ("Worst ratio tracked", f"{ratio(o['atl'][1])} on {fmt_date(o['atl'][0])}" if o["atl"] else None),
        ("eBay sold median (90d)", f"{usd(o['used']['median'])} · {o['used']['sales']} sales") if o["used"] else None,
    ]
    specs = [("Brand", o["brand"]), ("Architecture", o["arch"]), ("Memory", f"{o['vram']} GB {o['mem']}"), ("Board power", f"{o['tdp']} W"),
             ("Launch date", fmt_date(o["launch"])), ("Launch price", usd(o["msrp"]) + (" (estimate)" if o.get("msrp_est") else " MSRP")),
             ("Segment", cat), ("BTC on launch day", usd(o["launch_btc"]))]
    kv = lambda items: "".join(f"<tr><th scope=\"row\">{esc(k)}</th><td>{v}</td></tr>" for k, v in (i for i in items if i))  # noqa: E731
    months = monthly_rows(o, btc)
    mt = "".join(f'<tr><td>{dt.date.fromisoformat(i):%b %Y}</td><td>{usd(b)}</td><td>{usd(p)} <span class="muted">{esc(bs)}</span></td><td><b>{ratio(r)}</b></td></tr>'
                 for i, b, p, bs, r in months)
    listings = o["listings"][:6]
    lt = "".join(f'<tr><td><a href="https://www.google.com/search?tbm=shop&q={html.escape(l["name"].replace(" ", "+"), True)}" rel="noopener nofollow" target="_blank">{esc(l["name"])}</a></td>'
                 f'<td>{usd(l["price"])}</td><td>{sats(l["price"] / btc.now * 1e8)}</td></tr>' for l in listings)
    rel = sorted([r for r in rows if r["id"] != o["id"] and r["ratio"]], key=lambda r: (r["category"] != o["category"], abs((r["price"] or 0) - (o["price"] or 0))))[:8]
    rel_html = "".join(f'<a href="{root}m/{r["id"]}/">{esc(r["short"])}<span>{ratio(r["ratio"])}</span></a>' for r in rel)
    c = o.get("cloud") and cloud_now(data, o["cloud"])
    rent = ""
    if c and o["price"]:
        be = o["price"] / c["med"]
        rent = (f'<div class="rent"><div><span class="k">Rent instead</span><b class="mono big">{num(btc.now / c["med"], 0)}</b> GPU-hours per BTC</div>'
                f'<div class="s">{usd(c["med"], 2)}/hr median across {c["prov"]} cloud provider{"" if c["prov"] == 1 else "s"} ({esc(c["name"])}, low {usd(c["min"], 2)}). '
                f'Buying pays off after <b class="mono">{num(be, 0)}</b> rented hours, about {num(be / 24 / 30.4, 1)} months of 24/7 use.</div></div>')
    used = ""
    if o["used"]:
        u = o["used"]
        used = (f'<p>Used cards sell for a median {usd(u["median"])} on eBay ({u["sales"]} completed sales in 90 days, typical {usd(u["low"])}–{usd(u["high"])}). '
                f'Paid in bitcoin that is {sats(u["median"] / btc.now * 1e8)} sats, so 1 BTC buys {ratio(btc.now / u["median"])} used.</p>')
    image = f"{base}/assets/img/og/{o['id']}.jpg?v={stamp}"
    graph = [
        {"@type": "WebPage", "@id": url + "#page", "url": url, "name": title, "description": desc, "dateModified": data["updated"],
         "isPartOf": {"@type": "WebSite", "@id": base + "/#website", "url": base + "/", "name": site["title"]}, "primaryImageOfPage": image},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": site["title"], "item": base + "/"},
            {"@type": "ListItem", "position": 2, "name": cat + " GPUs", "item": base + "/#leaderboard"},
            {"@type": "ListItem", "position": 3, "name": o["name"], "item": url}]},
        faq_ld(qa),
    ]
    prices = [l["price"] for l in listings if l.get("price")]
    if prices and o["kind"] == "retail":
        graph.append({"@type": "Product", "name": o["name"], "brand": {"@type": "Brand", "name": o["brand"]},
                      "image": f"{base}/assets/img/gpus/{o['id']}.webp", "description": lede, "category": "Graphics card",
                      "offers": {"@type": "AggregateOffer", "priceCurrency": "USD", "lowPrice": f"{min(prices + [o['low']]):.2f}",
                                 "highPrice": f"{max(prices):.2f}", "offerCount": len(prices)}})
    share = f"1 BTC buys {ratio(o['ratio'])} {s_} today ({usd(o['price'])} each, {sats(o['sats'])} sats). At launch it was {ratio(o['launch_ratio'])}."
    from urllib.parse import quote
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{meta_block(site, title, desc, url, image, f"1 BTC buys {ratio(o['ratio'])} {s_}")}
{common_head(root)}
<link rel="preload" as="image" href="{root}assets/img/gpus/{o['id']}.webp" imagesrcset="{root}assets/img/gpus/{o['id']}-480.webp 480w, {root}assets/img/gpus/{o['id']}-640.webp 640w, {root}assets/img/gpus/{o['id']}.webp 900w" imagesizes="{HERO_SIZES}" fetchpriority="high">
<style>{inline_css(root)}</style>
{jsonld({"@context": "https://schema.org", "@graph": graph})}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
{topbar(root, btc, chg)}
<main id="main" class="wrap">
  <nav class="crumbs" aria-label="Breadcrumb"><ol><li><a href="{root}">Sats per Silicon</a></li><li><a href="{root}#leaderboard">{cat} GPUs</a></li><li aria-current="page">{esc(o['name'])}</li></ol></nav>
  <section class="mp-hero">
    <div>
      <p class="eyebrow">{esc(o['brand'])} · {esc(o['arch'])} · updated <time datetime="{data['updated']}">{upd}</time></p>
      <h1>How many {esc(s_)} does 1&nbsp;bitcoin buy?</h1>
      <div class="mp-num">{ratio(o['ratio'])}<small>{esc(o['name'])} per BTC · {usd(o['price'])} {esc(kind)} · {sats(o['sats'])} sats each</small></div>
      <p class="mp-lede">{esc(lede)}</p>
      <div class="mp-cta">
        <a class="btn btn-accent" href="{root}#open={o['id']}">Open interactive charts</a>
        <a class="btn" href="https://twitter.com/intent/tweet?text={quote(share)}&amp;url={quote(url)}" target="_blank" rel="noopener">Share on X</a>
        <a class="btn" href="https://www.reddit.com/submit?url={quote(url)}&amp;title={quote(share)}" target="_blank" rel="noopener">Reddit</a>
      </div>
    </div>
    <div class="mp-img"><img src="{root}assets/img/gpus/{o['id']}.webp" srcset="{root}assets/img/gpus/{o['id']}-480.webp 480w, {root}assets/img/gpus/{o['id']}-640.webp 640w, {root}assets/img/gpus/{o['id']}.webp 900w" sizes="{HERO_SIZES}" width="{d[0]}" height="{d[1]}" alt="{esc(o['name'])} graphics card" fetchpriority="high" decoding="async"></div>
  </section>

  <div class="stack">
  <section class="panel" aria-labelledby="hTitle">
    <h2 id="hTitle">{esc(o['short'])} per bitcoin since launch</h2>
    <p class="sub">GPUs per BTC. Solid: {esc(kind)}{' (tracked since ' + fmt_date(o['retail'][0][0]) + ')' if o['retail'] and o['kind'] != 'list' else ''}. Dashed: at the launch price, which moves only with bitcoin.</p>
    {svg_chart(o, btc)}
  </section>

  <section class="grid2">
    <div class="panel"><h2>{esc(o['short'])} price in bitcoin</h2><table class="kv"><tbody>{kv(stats)}</tbody></table></div>
    <div class="panel"><h2>{esc(o['short'])} specs</h2><table class="kv"><tbody>{kv(specs)}</tbody></table>{rent}</div>
  </section>

  <section class="panel prose" aria-labelledby="mTitle">
    <h2 id="mTitle">{esc(o['short'])} vs bitcoin, month by month</h2>
    <p class="sub">Month-end bitcoin close, {esc(o['short'])} price, and how many one bitcoin bought.</p>
    {used}
    <div class="table-wrap"><table class="lb"><thead><tr><th>Month</th><th>BTC close</th><th>{esc(o['short'])} price</th><th>Per BTC</th></tr></thead><tbody>{mt}</tbody></table></div>
  </section>

  {f'<section class="panel" aria-labelledby="lTitle"><h2 id="lTitle">Current {esc(o["short"])} listings</h2><p class="sub">Lowest US retail listings today, in dollars and sats.</p><div class="table-wrap"><table class="lb"><thead><tr><th>Listing</th><th>USD</th><th>Sats</th></tr></thead><tbody>{lt}</tbody></table></div></section>' if lt else ''}

  <section class="panel" id="faq" aria-labelledby="fTitle">
    <h2 id="fTitle">{esc(o['short'])} FAQ</h2>
    <div class="faq" style="margin-top:12px">{faq_html(qa)}</div>
  </section>

  <section class="panel" aria-labelledby="rTitle">
    <h2 id="rTitle">Compare other GPUs in bitcoin</h2>
    <p class="sub">GPUs per BTC today.</p>
    <div class="related">{rel_html}</div>
    <h3 style="margin-top:18px">Price history elsewhere</h3>
    <ul class="srclist">{''.join(f'<li><a href="{esc(u)}" target="_blank" rel="noopener">{esc(t)}</a></li>' for t, u in ext_links(o))}</ul>
  </section>
  </div>
</main>
<footer class="wrap foot">
  <span><a href="{root}">Sats per Silicon</a> · open data in <a href="{root}data/data.json">data.json</a></span>
  <span class="muted">Data updated {upd}. Not financial advice. US prices, excluding tax.</span>
</footer>
</body>
</html>
"""


# ----------------------------------------------------------------- crawl files
def write_crawl_files(cfg, rows, data, btc):
    base = cfg["site"]["base_url"].rstrip("/")
    lm = data["updated"][:10]
    urls = [(base + "/", "1.0")] + [(f"{base}/m/{o['id']}/", "0.8") for o in rows if o["ratio"]]
    (ROOT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
                                      "".join(f"  <url><loc>{u}</loc><lastmod>{lm}</lastmod><changefreq>hourly</changefreq><priority>{p}</priority></url>\n" for u, p in urls) +
                                      "</urlset>\n")
    (ROOT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n")
    priced = sorted([o for o in rows if o["ratio"]], key=lambda o: -o["ratio"])
    (ROOT / "llms.txt").write_text(
        f"# {cfg['site']['title']}\n\n> {cfg['site']['tagline']} Live bitcoin vs GPU prices: how many of each GPU one BTC buys, "
        f"sats per GPU, history since launch, used eBay prices and cloud GPU-hours per BTC.\n\n"
        f"Updated {data['updated']}. BTC/USD {usd(btc.now)}.\n\n## GPUs per BTC today\n\n" +
        "".join(f"- [{o['name']}]({base}/m/{o['id']}/): {ratio(o['ratio'])} per BTC ({usd(o['price'])}, {sats(o['sats'])} sats)\n" for o in priced) +
        f"\n## Data\n\n- [data.json]({base}/data/data.json): full daily archive (BTC closes, GPU retail/used/ask prices, cloud $/GPU-hour)\n"
        f"- [models.json]({base}/data/models.json): GPU metadata (MSRP, launch date, VRAM)\n")
    (ROOT / "404.html").write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Page not found · {esc(cfg['site']['title'])}</title><meta name="robots" content="noindex">
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#090b10;color:#f0efec;font:16px/1.5 system-ui,sans-serif;text-align:center;padding:16px}}a{{color:#f7931a}}h1{{font-size:40px;margin:0 0 8px}}ul{{list-style:none;padding:0;columns:2;text-align:left}}</style></head>
<body><main><h1>404</h1><p>That page does not exist. <a href="{base}/">Back to Sats per Silicon</a>, or jump to a GPU:</p>
<ul>{''.join(f'<li><a href="{base}/m/{o["id"]}/">{esc(o["short"])}</a></li>' for o in priced)}</ul></main></body></html>
""")


def main():
    cfg = json.loads((ROOT / "data" / "models.json").read_text())
    data = json.loads((ROOT / "data" / "data.json").read_text())
    btc, rows = prep(cfg, data)
    dims = make_variants(cfg["models"])
    stamp = re.sub(r"\D", "", data["updated"])[:10]  # YYYYMMDDHH: cards are redrawn every refresh
    upd = fmt_date(data["updated"][:10])
    build_home(cfg, data, btc, rows, dims, stamp)
    n = 0
    for o in rows:
        if not o["ratio"]:
            continue
        p = ROOT / "m" / o["id"] / "index.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(model_page(cfg, data, btc, o, rows, dims, stamp, upd))
        n += 1
    write_crawl_files(cfg, rows, data, btc)
    print(f"pre-rendered index.html and {n} model pages, sitemap, robots.txt, llms.txt, 404.html")


if __name__ == "__main__":
    main()
