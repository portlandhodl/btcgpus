# Sats per Silicon

**How many GPUs does one bitcoin buy?** An interactive, static dashboard that tracks the BTC/GPU ratio for
23 products, from gaming to the data center:

- **Gaming:** NVIDIA RTX 50 (plus the 4090), AMD Radeon RX 9000 (plus the 7900 XTX), Intel Arc
- **Workstation:** Radeon AI PRO R9700, Radeon PRO W7900, RTX PRO 6000 Blackwell
- **Data center:** H100, H200 NVL, A100, L40S, Instinct MI300X
- **AI systems:** NVIDIA DGX Spark (GB10), AMD Strix Halo (Framework Desktop, Ryzen AI Max+ 395, 128GB)

- Hero ticker and a lineup wall with cut-out GPU photos, sparklines and 30-day change
- Main chart: GPUs per BTC, sats per GPU, USD price or indexed, priced at retail average, lowest listing,
  or launch MSRP (which isolates bitcoin's move and reaches back to each launch day), with range presets,
  log scale, zoom, PNG export and a table view
- Sortable leaderboard: retail, lowest, eBay sold median, premium over MSRP, sats per GB of VRAM, and more
- "Then vs now" dumbbell (launch vs today) and a sats-per-GB-VRAM chart
- Time machine: a racing bar chart you can scrub or play from Oct 2022 to today
- Rent instead: cloud GPU-hours per BTC (H100, H200, B200, B300, MI300X and more), plus rent-vs-buy break-even per GPU
- Stack calculator in BTC, sats or USD
- Per-GPU drawer: stats, ratio and price charts, the eBay sold range, current retail listings, and links to
  historic sales (eBay sold, pcprice.watch, GPU Price History, Best Value GPU, r/hardwareswap and others)
- Sharing: a 1200×630 unfurl card for the site and for every GPU (`/m/<id>/` share URLs), X, Reddit,
  Telegram, Bluesky, Nostr, copy link and native share. View state is kept in the URL hash.

## Data

| What | Source | Script |
|---|---|---|
| BTC/USD daily close | Binance BTCUSDT (Coinbase fallback) | `scripts/update_data.py` |
| New retail, US daily min and avg | gpupricehistory.com | `scripts/update_data.py` |
| Used, eBay sold 90-day median | pcprice.watch | `scripts/update_data.py` |
| Workstation / data-center asks (avg of 3 cheapest) | gpupoet.com | `scripts/update_data.py` |
| Cloud $/GPU-hour, daily | gpuperhour.com CSV | `scripts/update_data.py` |
| DGX Spark, Strix Halo list prices | `list_history` in `data/models.json` (hand-curated) | n/a |
| GPU photos, background removed | retailer product images | `scripts/fetch_images.py` |
| Unfurl cards and share pages | generated | `scripts/build_site.py` |

`data/data.json` is merged, never truncated, so the archive grows past the sources' rolling windows.
Model metadata (MSRP, launch date, VRAM, pinned photo URL) is in `data/models.json`.

## Run locally

```sh
pip install pillow numpy
python scripts/update_data.py      # refresh prices (stdlib only)
python scripts/fetch_images.py     # only fetches photos that are missing; --force to redo
python scripts/build_site.py       # share cards + /m/<id>/ pages + index OG tags
python -m http.server 8000         # open http://localhost:8000
```

## Deploy (GitHub Pages)

1. Push to `main`.
2. Settings → Pages → Build and deployment → **Source: GitHub Actions**.
3. `.github/workflows/update.yml` refreshes data every 6 hours, commits it, and deploys.

If the repo name or owner changes, update `site.base_url` in `data/models.json`. Unfurl cards need absolute URLs.

## Adding a GPU

Add an entry to `data/models.json`. The `id` must match the slug used by gpupricehistory.com and pcprice.watch,
for example `rtx-5070`. Optionally pin a white-background product photo with `img_url`, then run the three scripts.

Data-center parts have no public MSRP. Their launch prices are estimates and are flagged `msrp_est` (shown with *).
Some images come from NVIDIA/AMD press pages and Wikimedia Commons (DGX Spark photo: Daniel Lu, CC BY-SA 4.0, background removed).

Not financial advice. Prices are US only and exclude tax.
