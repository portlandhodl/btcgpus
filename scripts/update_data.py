#!/usr/bin/env python3
"""Refresh data/data.json: BTC daily closes + GPU retail/used price history.

Stdlib only so it runs anywhere (GitHub Actions, laptop).

Sources
  BTC/USD daily close ..... Binance public market data (BTCUSDT), Coinbase fallback
  GPU retail (new) ........ gpupricehistory.com  (daily US min + average across retailers)
  GPU used (eBay sold) .... pcprice.watch         (90-day eBay sold median / range / count)
  Pro / data-center ....... gpupoet.com           (daily avg of the 3 lowest eBay/Amazon asks)
  Cloud rental ............ gpuperhour.com        (daily min / median $ per GPU-hour, CSV)
  AI systems .............. list-price history curated in models.json (no scraping)

History is merged, never truncated: each run keeps every date already in
data.json and overwrites/adds what the sources return, so the archive keeps
growing past the source sites' own rolling windows.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "data" / "models.json"
OUT = ROOT / "data" / "data.json"
UA = "Mozilla/5.0 (compatible; btcgpus-dashboard/1.0; +https://github.com/)"
BTC_START = dt.date(2021, 1, 1)


def get(url: str, retries: int = 3) -> str:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + i * 3)
    raise RuntimeError(f"GET {url} failed: {last}")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- BTC
def btc_binance(start: dt.date) -> dict[str, float]:
    out: dict[str, float] = {}
    ms = int(dt.datetime.combine(start, dt.time(), dt.timezone.utc).timestamp() * 1000)
    while True:
        rows = json.loads(get(
            "https://data-api.binance.vision/api/v3/klines"
            f"?symbol=BTCUSDT&interval=1d&limit=1000&startTime={ms}"))
        if not rows:
            break
        for r in rows:
            d = dt.datetime.fromtimestamp(r[0] / 1000, dt.timezone.utc).date().isoformat()
            out[d] = round(float(r[4]), 2)
        if len(rows) < 1000:
            break
        ms = rows[-1][0] + 86_400_000
    return out


def btc_coinbase(start: dt.date) -> dict[str, float]:
    out: dict[str, float] = {}
    cur = start
    today = dt.date.today()
    while cur <= today:
        end = min(cur + dt.timedelta(days=299), today)
        rows = json.loads(get(
            "https://api.exchange.coinbase.com/products/BTC-USD/candles"
            f"?granularity=86400&start={cur.isoformat()}&end={end.isoformat()}"))
        for t, _lo, _hi, _op, close, _v in rows:
            out[dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat()] = round(float(close), 2)
        cur = end + dt.timedelta(days=1)
        time.sleep(0.4)
    return out


def fetch_btc() -> dict[str, float]:
    for fn in (btc_binance, btc_coinbase):
        try:
            d = fn(BTC_START)
            if len(d) > 300:
                log(f"BTC: {len(d)} days via {fn.__name__}")
                return d
        except Exception as e:  # noqa: BLE001
            log(f"BTC source {fn.__name__} failed: {e}")
    return {}


# ---------------------------------------------------------------- GPU retail
def next_flight(page: str) -> str:
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', page, re.S)
    return "".join(json.loads(f'"{c}"') for c in chunks)


def fetch_retail(model_id: str) -> tuple[dict[str, list], list[dict]]:
    flight = next_flight(get(f"https://gpupricehistory.com/us/{model_id}"))
    series: dict[str, list] = {}
    i = flight.find('{"data":[{"date"')
    if i >= 0:
        dec = json.JSONDecoder()
        obj, _ = dec.raw_decode(flight, i)
        for p in obj.get("data", []):
            pr = p.get("price") or {}
            if pr.get("average"):
                series[p["date"][:10]] = [round(pr.get("min") or pr["average"], 2), round(pr["average"], 2)]
    listings = []
    for m in re.finditer(
        r'"img",null,\{"src":"([^"]+)","alt":"([^"]+)".*?"children":"([^"]*)"\}\],\["\$","h3".*?'
        r'"children":\["\$\$","([\d,\.]+)"\]', flight):
        img, name, brand, price = m.groups()
        listings.append({"name": html.unescape(name), "brand": brand, "price": float(price.replace(",", "")), "img": img})
    return series, listings


# ---------------------------------------------------------------- GPU used
def money(s: str) -> float | None:
    try:
        return float(s.replace("$", "").replace(",", ""))
    except ValueError:
        return None


def fetch_used(model_id: str) -> dict | None:
    page = get(f"https://www.pcprice.watch/gpu-buying-guide/{model_id}-price-used-and-specs")
    text = re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S))
    text = re.sub(r"\s+", " ", html.unescape(text))
    m = re.search(r"sells for a median of \$([\d,]+) on eBay\s*[—-]\s*typically \$([\d,]+)\s*[–-]\s*\$([\d,]+), from (\d+) completed sales", text)
    if not m:
        return None
    out = {"median": money(m[1]), "low": money(m[2]), "high": money(m[3]), "sales": int(m[4])}
    if a := re.search(r"\$([\d,]+) US asking now", text):
        out["asking"] = money(a[1])
    if p := re.search(r"\$([\d,]+) peak \(([A-Za-z]{3} \d{4})\)", text):
        out["peak"], out["peak_month"] = money(p[1]), p[2]
    return out


# ---------------------------------------------------------------- GPU Poet (pro / data-center)
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
MONTHS_LONG = ["january", "february", "march", "april", "may", "june", "july", "august",
               "september", "october", "november", "december"]


def fetch_gpupoet(slug: str, today: dt.date) -> dict[str, list]:
    """Daily 'lowest average' (mean of the 3 cheapest whole-card listings) for ~4 months.

    Labels come without a year ("Jul 14"); walk backwards from today to assign one.
    """
    page = get(f"https://gpupoet.com/gpu/learn/price/{MONTHS_LONG[today.month-1]}-{today.year}/{slug}")
    flight = next_flight(page)
    m = re.search(r'"series":\[\{"label":"[^"]+".*?"data":(\[[^\]]*\])', flight)
    if not m:
        return {}
    pts = json.loads(m.group(1))
    out: dict[str, list] = {}
    year, prev_month = today.year, 13
    for p in reversed(pts):
        mon, day = p["x"].split()
        mi = MONTHS.index(mon[:3].lower()) + 1
        if mi > prev_month:
            year -= 1
        prev_month = mi
        d = dt.date(year, mi, int(day))
        if d <= today and p.get("y"):
            v = round(float(p["y"]), 2)
            out[d.isoformat()] = [v, v]
    return out


# ---------------------------------------------------------------- cloud rental
def fetch_cloud() -> dict[str, dict[str, list]]:
    import csv, io
    text = get("https://api.gpuperhour.com/api/price-index/export.csv?days=365")
    out: dict[str, dict[str, list]] = {}
    for r in csv.DictReader(io.StringIO(text)):
        try:
            mn, med = float(r["min_price_per_gpu"]), float(r["median_price_per_gpu"])
        except (TypeError, ValueError):
            continue
        out.setdefault(r["gpu_slug"], {"name": r["gpu_name"], "series": {}})["series"][r["snapshot_date"]] = [mn, med, int(r["provider_count"] or 0)]
    return out


# ---------------------------------------------------------------- main
def main() -> int:
    cfg = json.loads(MODELS.read_text())
    prev = json.loads(OUT.read_text()) if OUT.exists() else {"btc": {}, "gpus": {}}
    today = dt.date.today().isoformat()

    btc = dict(prev.get("btc", {}))
    btc.update(fetch_btc())
    if not btc:
        log("no BTC data, aborting")
        return 1

    gpus = prev.get("gpus", {})
    today_d = dt.date.today()
    ok = 0
    for m in cfg["models"]:
        mid, src = m["id"], m.get("src", {"retail": "gph", "used": "pcprice"})
        g = gpus.setdefault(mid, {"retail": {}, "used": {}, "listings": []})
        if src.get("list"):
            ok += 1  # list-price products are curated in models.json
            continue
        try:
            if src.get("retail") == "gph":
                series, listings = fetch_retail(mid)
                if listings:
                    g["listings"] = listings[:12]
                log(f"{mid}: retail {len(series)} pts, {len(listings)} listings")
            elif src.get("gpupoet"):
                series = fetch_gpupoet(src["gpupoet"], today_d)
                log(f"{mid}: gpupoet {len(series)} pts")
            else:
                series = {}
            g["retail"].update(series)
            ok += bool(series)
        except Exception as e:  # noqa: BLE001
            log(f"{mid}: retail failed: {e}")
        if src.get("used") == "pcprice":
            try:
                used = fetch_used(mid)
                if used:
                    g["used"][today] = used
                    log(f"{mid}: used median ${used['median']:,.0f} ({used['sales']} sales)")
            except Exception as e:  # noqa: BLE001
                log(f"{mid}: used failed: {e}")
        time.sleep(1.0)

    cloud = prev.get("cloud", {})
    try:
        for slug, c in fetch_cloud().items():
            cur = cloud.setdefault(slug, {"name": c["name"], "series": {}})
            cur["name"] = c["name"]
            cur["series"].update(c["series"])
        log(f"cloud: {len(cloud)} GPU types")
    except Exception as e:  # noqa: BLE001
        log(f"cloud failed: {e}")
    for c in cloud.values():
        c["series"] = dict(sorted(c["series"].items()))

    if ok == 0:
        log("every GPU source failed, not writing")
        return 1

    for g in gpus.values():
        g["retail"] = dict(sorted(g["retail"].items()))
        g["used"] = dict(sorted(g["used"].items()))
    out = {
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": {
            "btc": "Binance BTCUSDT daily close (Coinbase BTC-USD fallback)",
            "retail": "gpupricehistory.com, US retail, daily min and average",
            "used": "pcprice.watch, eBay sold listings, 90-day median",
            "pro": "gpupoet.com, average of the 3 lowest eBay/Amazon asking prices per day",
            "cloud": "gpuperhour.com cloud GPU price index, $ per GPU-hour (min and median)",
        },
        "btc": dict(sorted(btc.items())),
        "gpus": gpus,
        "cloud": cloud,
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    log(f"wrote {OUT} ({OUT.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
