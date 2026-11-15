#!/usr/bin/env python3
"""Refresh data/data.json: BTC daily closes + GPU retail/used price history.

Stdlib only so it runs anywhere (GitHub Actions, laptop).

Sources
  BTC/USD daily close ..... Binance public market data (BTCUSDT), Coinbase fallback
  GPU retail (new) ........ gpupricehistory.com  (daily US min + average across retailers)
  GPU used (eBay sold) .... pcprice.watch         (90-day eBay sold median / range / count)

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
BTC_START = dt.date(2022, 9, 1)


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
    ok = 0
    for m in cfg["models"]:
        mid = m["id"]
        g = gpus.setdefault(mid, {"retail": {}, "used": {}, "listings": []})
        try:
            series, listings = fetch_retail(mid)
            g["retail"].update(series)
            if listings:
                g["listings"] = listings[:12]
            log(f"{mid}: retail {len(series)} pts, {len(listings)} listings")
            ok += 1
        except Exception as e:  # noqa: BLE001
            log(f"{mid}: retail failed: {e}")
        try:
            used = fetch_used(mid)
            if used:
                g["used"][today] = used
                log(f"{mid}: used median ${used['median']:,.0f} ({used['sales']} sales)")
        except Exception as e:  # noqa: BLE001
            log(f"{mid}: used failed: {e}")
        time.sleep(1.0)

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
        },
        "btc": dict(sorted(btc.items())),
        "gpus": gpus,
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    log(f"wrote {OUT} ({OUT.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
