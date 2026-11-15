/* Sats per Silicon: BTC / GPU purchasing-power dashboard */
(() => {
  "use strict";

  // ------------------------------------------------------------------ tokens
  const css = getComputedStyle(document.documentElement);
  const tok = (n) => css.getPropertyValue(n).trim();
  const C = {
    surface: tok("--surface"), page: tok("--page"), line: tok("--line"), grid: tok("--grid"),
    axis: tok("--axis"), ink: tok("--ink"), ink2: tok("--ink-2"), muted: tok("--muted"),
    accent: tok("--accent"), good: tok("--good"), bad: tok("--bad"),
    slots: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => tok(`--s${i}`)),
    brand: { NVIDIA: tok("--nv"), AMD: tok("--amd"), Intel: tok("--intel") },
  };
  const MONO = '"JetBrains Mono", ui-monospace, monospace';
  const SANS = 'Inter, system-ui, sans-serif';
  const MAX_SERIES = 8;
  const DEFAULT_SEL = ["rtx-5090", "rtx-5080", "rx-9070-xt", "arc-b580"];
  const VCP = new Set(["rtx-5090", "rtx-5080", "rtx-5070-ti", "rtx-5070", "rtx-5060-ti", "rx-9070-xt", "rx-9070", "rx-9060-xt", "arc-b580", "arc-b570"]);

  // ------------------------------------------------------------------ utils
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const usd = (v, d = 0) => v == null ? "–" : "$" + v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const num = (v, d = 1) => v == null ? "–" : v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const ratio = (v) => v == null ? "–" : v < 10 ? num(v, 2) : v < 1000 ? num(v, 1) : num(v, 0);
  const sats = (v) => v == null ? "–" : v >= 1e6 ? num(v / 1e6, 2) + "M" : v >= 1e3 ? num(v / 1e3, 1) + "k" : num(v, 0);
  const pct = (v, d = 0) => v == null ? "–" : (v >= 0 ? "+" : "−") + num(Math.abs(v) * 100, d) + "%";
  const cls = (v) => v == null ? "" : v >= 0 ? "up" : "down";
  const dayMs = 864e5;
  const addDays = (iso, n) => new Date(Date.parse(iso) + n * dayMs).toISOString().slice(0, 10);
  const fmtDate = (iso) => new Date(iso + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  const toast = (msg) => { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 1800); };
  const metricName = { gpb: "GPUs per BTC", sats: "Sats per GPU", usd: "USD price", idx: "Indexed GPUs per BTC" };
  const basisName = { avg: "retail average", min: "lowest retail listing", msrp: "launch MSRP" };

  // ------------------------------------------------------------------ state
  const S = {
    metric: "gpb", basis: "avg", range: "all", log: false, brand: "all",
    sel: [], slot: new Map(), unit: "btc", sort: { key: "ratio", dir: -1 },
  };
  let M = [], byId = {}, BTC = { d: [], p: [] }, DATA, CFG;
  const charts = {};

  // ------------------------------------------------------------------ data
  function btcAt(iso) {
    const d = BTC.d; let lo = 0, hi = d.length - 1;
    if (iso < d[0]) return BTC.p[0];
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (d[mid] <= iso) lo = mid; else hi = mid - 1; }
    return BTC.p[lo];
  }

  function prep(cfg, data) {
    CFG = cfg; DATA = data;
    BTC.d = Object.keys(data.btc); BTC.p = BTC.d.map((k) => data.btc[k]);
    const last = BTC.d[BTC.d.length - 1], btcNow = BTC.p[BTC.p.length - 1];
    M = cfg.models.map((m) => {
      const g = data.gpus[m.id] || { retail: {}, used: {}, listings: [] };
      const retail = Object.entries(g.retail).map(([d, [mn, av]]) => ({ d, min: mn, avg: av }));
      const usedK = Object.keys(g.used || {});
      const used = usedK.length ? { date: usedK[usedK.length - 1], ...g.used[usedK[usedK.length - 1]] } : null;
      const usedHist = usedK.map((k) => [k, g.used[k].median]);
      const cur = retail[retail.length - 1];
      const launchBtc = btcAt(m.launch);
      const o = { ...m, retail, used, usedHist, listings: g.listings || [], retailMap: new Map(retail.map((r) => [r.d, r])) };
      o.price = cur ? cur.avg : null;
      o.low = cur ? cur.min : null;
      o.ratio = o.price ? btcNow / o.price : null;
      o.sats = o.price ? (o.price / btcNow) * 1e8 : null;
      o.launchBtc = launchBtc;
      o.launchRatio = launchBtc / m.msrp;
      o.sinceLaunch = o.ratio ? o.ratio / o.launchRatio - 1 : null;
      o.premium = o.price ? o.price / m.msrp - 1 : null;
      o.satsPerGB = o.sats ? o.sats / m.vram : null;
      const gpb = retail.map((r) => ({ d: r.d, v: btcAt(r.d) / r.avg }));
      if (o.ratio && cur && cur.d < last) gpb.push({ d: last, v: o.ratio }); // include today's live point
      o.gpb = gpb;
      const ago = (n) => { const t = addDays(cur ? cur.d : last, -n); const p = gpb.filter((x) => x.d <= t).pop(); return p ? p.v : null; };
      o.chg30 = o.ratio && ago(30) ? o.ratio / ago(30) - 1 : null;
      o.chg7 = o.ratio && ago(7) ? o.ratio / ago(7) - 1 : null;
      if (gpb.length) {
        o.ath = gpb.reduce((a, b) => (b.v > a.v ? b : a));
        o.atl = gpb.reduce((a, b) => (b.v < a.v ? b : a));
      }
      return o;
    });
    byId = Object.fromEntries(M.map((m) => [m.id, m]));
  }

  /** price series for a model under a basis: [[iso, usd], ...] */
  function priceSeries(m, basis) {
    if (basis === "msrp") {
      const out = []; const start = m.launch > BTC.d[0] ? m.launch : BTC.d[0];
      for (const d of BTC.d) if (d >= start) out.push([d, m.msrp]);
      return out;
    }
    const out = m.retail.map((r) => [r.d, basis === "min" ? r.min : r.avg]);
    // carry the latest GPU price forward to today's BTC close so the line ends where the cards do
    const lastBtc = BTC.d[BTC.d.length - 1], tail = out[out.length - 1];
    if (tail && tail[0] < lastBtc && Date.parse(lastBtc) - Date.parse(tail[0]) <= 5 * dayMs) out.push([lastBtc, tail[1]]);
    return out;
  }
  function metricSeries(m, metric, basis, idxFrom) {
    const ps = priceSeries(m, basis);
    let out = ps.map(([d, p]) => {
      const b = btcAt(d);
      const v = metric === "usd" ? p : metric === "sats" ? (p / b) * 1e8 : b / p;
      return [d, v];
    });
    if (metric === "idx") {
      const first = out.find(([d]) => d >= idxFrom) || out[0];
      if (first) out = out.map(([d, v]) => [d, (v / first[1]) * 100]);
    }
    return out;
  }
  function fmtMetric(v, metric) {
    if (v == null || isNaN(v)) return "–";
    if (metric === "usd") return usd(v);
    if (metric === "sats") return sats(v) + " sats";
    if (metric === "idx") return num(v, 1);
    return ratio(v);
  }

  // ------------------------------------------------------------------ chart helpers
  const baseAxis = () => ({
    axisLine: { lineStyle: { color: C.axis } }, axisTick: { show: false },
    axisLabel: { color: C.muted, fontFamily: SANS, fontSize: 11 },
    splitLine: { lineStyle: { color: C.grid, width: 1 } },
  });
  const tooltipBase = () => ({
    backgroundColor: "rgba(17,20,27,.96)", borderColor: C.line, borderWidth: 1, padding: [10, 12],
    textStyle: { color: C.ink, fontFamily: SANS, fontSize: 12 }, extraCssText: "border-radius:10px;box-shadow:0 10px 30px rgba(0,0,0,.4);",
  });
  function mk(id) {
    const el = document.getElementById(id);
    if (charts[id]) { charts[id].dispose(); }
    charts[id] = echarts.init(el, null, { renderer: "canvas" });
    return charts[id];
  }
  window.addEventListener("resize", () => Object.values(charts).forEach((c) => c && !c.isDisposed() && c.resize()));

  // ------------------------------------------------------------------ selection
  function colorOf(id) { return S.slot.has(id) ? C.slots[S.slot.get(id)] : C.muted; }
  function addSel(id) {
    if (S.sel.includes(id)) return true;
    if (S.sel.length >= MAX_SERIES) { toast(`Chart holds ${MAX_SERIES} lines. Remove one first.`); return false; }
    const used = new Set(S.slot.values());
    let s = 0; while (used.has(s)) s++;
    S.slot.set(id, s); S.sel.push(id); return true;
  }
  function delSel(id) { S.sel = S.sel.filter((x) => x !== id); S.slot.delete(id); }
  function toggleSel(id) { S.sel.includes(id) ? delSel(id) : addSel(id); syncSel(); }
  function syncSel() { renderWallState(); renderLegend(); renderMain(); writeHash(); }

  // ------------------------------------------------------------------ hero
  let heroI = 0, heroTimer;
  function renderHero() {
    const order = ["rtx-5090", "rtx-5080", "rx-9070-xt", "arc-b580", "rtx-5070-ti", "rx-9060-xt", "rtx-5070", "arc-b570", "rx-9070", "rtx-4090", "rx-7900-xtx", "rtx-5060-ti", "arc-a770"]
      .map((id) => byId[id]).filter((m) => m && m.ratio);
    const show = (m) => {
      const img = $("#heroImg"), num = $("#heroNum"), mod = $("#heroModel");
      img.classList.add("swap"); num.classList.add("fade");
      setTimeout(() => {
        img.src = `assets/img/gpus/${m.id}.webp`; img.alt = m.name;
        num.textContent = ratio(m.ratio);
        mod.textContent = m.short + (m.ratio >= 2 ? "s" : "");
        $("#heroSub").textContent = `${usd(m.price)} avg retail · ${sats(m.sats)} sats each`;
        const s = m.sinceLaunch;
        $("#heroNote").innerHTML = `At launch on ${fmtDate(m.launch)}, 1&nbsp;BTC bought <b>${ratio(m.launchRatio)}</b> at the ${usd(m.msrp)} MSRP. ` +
          `Bitcoin's GPU purchasing power is <b class="${cls(s)}">${pct(s)}</b> since then.`;
        img.onload = () => img.classList.remove("swap");
        num.classList.remove("fade");
      }, 260);
    };
    const tick = () => { show(order[heroI % order.length]); heroI++; };
    clearInterval(heroTimer); tick();
    if (!matchMedia("(prefers-reduced-motion: reduce)").matches) heroTimer = setInterval(tick, 4200);
    $("#heroStat").onclick = () => openDrawer(order[(heroI - 1 + order.length) % order.length].id);
    $("#heroStat").style.cursor = "pointer";
  }

  // ------------------------------------------------------------------ wall
  function spark(m) {
    const pts = m.gpb.slice(-90); if (pts.length < 2) return "";
    const vs = pts.map((p) => p.v), lo = Math.min(...vs), hi = Math.max(...vs), w = 180, h = 34;
    const xy = pts.map((p, i) => [(i / (pts.length - 1)) * w, h - 3 - ((p.v - lo) / (hi - lo || 1)) * (h - 6)]);
    const d = xy.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join("");
    const up = vs[vs.length - 1] >= vs[0];
    const col = up ? C.good : C.bad;
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
      <path d="${d}L${w} ${h}L0 ${h}Z" fill="${col}" opacity=".10"/><path d="${d}" fill="none" stroke="${col}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`;
  }
  function renderWall() {
    $("#wall").innerHTML = M.map((m) => `
      <div class="card" data-id="${m.id}" data-brand="${m.brand}" role="button" tabindex="0" aria-label="${esc(m.name)} details">
        <button class="add" type="button" aria-pressed="false" aria-label="Add ${esc(m.short)} to chart" title="Add to chart">＋</button>
        <div class="img"><img src="assets/img/gpus/${m.id}.webp" alt="${esc(m.name)}" loading="lazy"></div>
        <div class="name"><i class="b-${m.brand}"></i>${esc(m.short)}</div>
        <div class="big">${ratio(m.ratio)}<small>per BTC</small></div>
        <div class="meta"><span>${usd(m.price)} · ${sats(m.sats)} sats</span><span class="${cls(m.chg30)}">${pct(m.chg30, 1)} 30d</span></div>
        ${spark(m)}
      </div>`).join("");
    $$("#wall .card").forEach((el) => {
      const id = el.dataset.id;
      el.addEventListener("click", (e) => { if (e.target.closest(".add")) return; openDrawer(id); });
      el.addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && e.target === el) { e.preventDefault(); openDrawer(id); } });
      $(".add", el).addEventListener("click", (e) => { e.stopPropagation(); toggleSel(id); });
    });
    renderWallState();
  }
  function renderWallState() {
    $$("#wall .card").forEach((el) => {
      const id = el.dataset.id, on = S.sel.includes(id);
      el.classList.toggle("on", on);
      el.style.setProperty("--sc", on ? colorOf(id) : "transparent");
      const b = $(".add", el); b.setAttribute("aria-pressed", on); b.textContent = on ? "✓" : "＋";
      el.classList.toggle("hide", S.brand !== "all" && el.dataset.brand !== S.brand);
    });
  }

  // ------------------------------------------------------------------ main chart
  function renderLegend() {
    const lg = $("#legend");
    const btns = S.sel.map((id) => {
      const m = byId[id];
      return `<button type="button" data-id="${id}" title="Remove ${esc(m.short)}"><i class="sw" style="background:${colorOf(id)}"></i>${esc(m.short)}<span class="x">✕</span></button>`;
    }).join("");
    const avail = M.filter((m) => !S.sel.includes(m.id));
    const add = S.sel.length < MAX_SERIES && avail.length
      ? `<select id="addSel" aria-label="Add a GPU to the chart" class="chip" style="height:28px;border-radius:8px"><option value="">＋ Add GPU…</option>${avail.map((m) => `<option value="${m.id}">${esc(m.short)}</option>`).join("")}</select>` : "";
    lg.innerHTML = (btns || `<span class="empty">No GPUs selected</span>`) + add;
    $$("button", lg).forEach((b) => {
      b.onclick = () => { delSel(b.dataset.id); syncSel(); };
      b.onmouseenter = () => charts.mainChart && charts.mainChart.dispatchAction({ type: "highlight", seriesName: byId[b.dataset.id].short });
      b.onmouseleave = () => charts.mainChart && charts.mainChart.dispatchAction({ type: "downplay", seriesName: byId[b.dataset.id].short });
    });
    const sel = $("#addSel"); if (sel) sel.onchange = () => { if (sel.value) { addSel(sel.value); syncSel(); } };
  }

  function rangeStart(lastIso) {
    const y = lastIso.slice(0, 4);
    return { "1m": addDays(lastIso, -30), "3m": addDays(lastIso, -91), "6m": addDays(lastIso, -182), ytd: `${y}-01-01`, all: null }[S.range];
  }

  function renderMain() {
    const ch = charts.mainChart || mk("mainChart");
    const last = BTC.d[BTC.d.length - 1];
    let start = rangeStart(last);
    if (!start) {
      const firsts = S.sel.map((id) => (priceSeries(byId[id], S.basis)[0] || [last])[0]);
      start = firsts.length ? firsts.sort()[0] : addDays(last, -365);
    }
    const series = S.sel.map((id) => {
      const m = byId[id];
      return {
        name: m.short, id, type: "line", showSymbol: false, symbolSize: 8, sampling: "lttb",
        data: metricSeries(m, S.metric, S.basis, start),
        lineStyle: { width: 2, color: colorOf(id) }, itemStyle: { color: colorOf(id), borderColor: C.surface, borderWidth: 2 },
        emphasis: { focus: "series", lineStyle: { width: 3 } }, blur: { lineStyle: { opacity: 0.15 } },
        endLabel: { show: S.sel.length <= 4, formatter: (p) => `${m.short}  ${fmtMetric(p.value[1], S.metric)}`, color: C.ink2, fontFamily: SANS, fontSize: 11, fontWeight: 600, distance: 6 },
        labelLayout: { moveOverlap: "shiftY" },
      };
    });
    if (S.metric === "idx") series.push({ type: "line", data: [], markLine: { silent: true, symbol: "none", lineStyle: { color: C.axis, type: "dashed" }, label: { show: false }, data: [{ yAxis: 100 }] } });
    $("#chartSub").textContent = `${metricName[S.metric]} · priced at ${basisName[S.basis]}` +
      (S.basis === "msrp" ? " (bitcoin's move alone)" : " · retail tracking from Jan 2026");
    const ya = baseAxis();
    ch.setOption({
      backgroundColor: "transparent", animationDuration: 600, color: S.sel.map(colorOf),
      grid: { left: 8, right: S.sel.length <= 4 ? 150 : 24, top: 16, bottom: 70, containLabel: true },
      tooltip: {
        ...tooltipBase(), trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: C.axis }, label: { show: false } },
        formatter: (ps) => {
          if (!ps.length) return "";
          const d = ps[0].value[0];
          const rows = ps.filter((p) => p.seriesId && p.value).sort((a, b) => b.value[1] - a.value[1]).map((p) =>
            `<div style="display:flex;gap:14px;justify-content:space-between;align-items:center"><span><i style="display:inline-block;width:10px;height:3px;border-radius:2px;background:${p.color};margin-right:7px;vertical-align:middle"></i>${esc(p.seriesName)}</span><b style="font-family:${MONO}">${fmtMetric(p.value[1], S.metric)}</b></div>`).join("");
          return `<div style="font-weight:700;margin-bottom:6px">${fmtDate(d)}</div>${rows}<div style="margin-top:6px;color:${C.muted}">BTC ${usd(btcAt(d))}</div>`;
        },
      },
      xAxis: { type: "time", ...baseAxis(), splitLine: { show: false }, axisLabel: { ...baseAxis().axisLabel, hideOverlap: true } },
      yAxis: {
        type: S.log ? "log" : "value", scale: true, ...ya,
        axisLine: { show: false },
        axisLabel: { ...ya.axisLabel, formatter: (v) => S.metric === "usd" ? "$" + (v >= 1000 ? num(v / 1000, 1) + "k" : v) : S.metric === "sats" ? sats(v) : num(v, v < 10 ? 1 : 0) },
      },
      dataZoom: [
        { type: "inside", startValue: start, endValue: last, filterMode: "none" },
        { type: "slider", startValue: start, endValue: last, height: 26, bottom: 14, borderColor: C.line, backgroundColor: C.page, fillerColor: "rgba(247,147,26,.10)",
          handleStyle: { color: C.ink2, borderColor: C.axis }, moveHandleStyle: { color: C.axis }, textStyle: { color: C.muted, fontSize: 10 },
          dataBackground: { lineStyle: { color: C.axis }, areaStyle: { color: C.surface } }, selectedDataBackground: { lineStyle: { color: C.accent }, areaStyle: { color: "rgba(247,147,26,.08)" } } },
      ],
      series,
    }, { replaceMerge: ["series", "dataZoom"] });
    renderChartTable(start);
  }

  function renderChartTable(start) {
    const box = $("#chartTable"); if (box.hidden) return;
    const cols = S.sel.map((id) => ({ m: byId[id], data: new Map(metricSeries(byId[id], S.metric, S.basis, start)) }));
    const dates = [];
    for (let d = BTC.d[BTC.d.length - 1]; d >= start && dates.length < 60; d = addDays(d, -7)) dates.push(d);
    const near = (map, d) => { for (let i = 0; i < 7; i++) { const v = map.get(addDays(d, -i)); if (v != null) return v; } return null; };
    box.innerHTML = `<table><thead><tr><th>Week of</th><th>BTC</th>${cols.map((c) => `<th>${esc(c.m.short)}</th>`).join("")}</tr></thead><tbody>${dates.map((d) =>
      `<tr><td>${fmtDate(d)}</td><td class="mono">${usd(btcAt(d))}</td>${cols.map((c) => `<td class="mono">${fmtMetric(near(c.data, d), S.metric)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }

  // ------------------------------------------------------------------ leaderboard
  const LB_COLS = [
    { key: "name", label: "GPU", val: (m) => m.short, fmt: (m) => `<span class="m"><img src="assets/img/gpus/${m.id}.webp" alt="" loading="lazy"><i class="b-${m.brand}"></i>${esc(m.short)}</span>` },
    { key: "vram", label: "VRAM", val: (m) => m.vram, fmt: (m) => m.vram + " GB" },
    { key: "msrp", label: "MSRP", val: (m) => m.msrp, fmt: (m) => usd(m.msrp) },
    { key: "price", label: "Retail avg", val: (m) => m.price, fmt: (m) => usd(m.price) },
    { key: "low", label: "Lowest", val: (m) => m.low, fmt: (m) => usd(m.low) },
    { key: "used", label: "eBay sold", val: (m) => m.used?.median, fmt: (m) => m.used ? usd(m.used.median) : "–" },
    { key: "premium", label: "vs MSRP", val: (m) => m.premium, fmt: (m) => `<span class="${m.premium > 0 ? "down" : "up"}">${pct(m.premium)}</span>` },
    { key: "ratio", label: "GPUs / BTC", val: (m) => m.ratio, fmt: (m) => `<b>${ratio(m.ratio)}</b>`, bar: true },
    { key: "sats", label: "Sats each", val: (m) => m.sats, fmt: (m) => sats(m.sats) },
    { key: "satsPerGB", label: "Sats / GB", val: (m) => m.satsPerGB, fmt: (m) => sats(m.satsPerGB) },
    { key: "chg30", label: "30d", val: (m) => m.chg30, fmt: (m) => `<span class="${cls(m.chg30)}">${pct(m.chg30, 1)}</span>` },
    { key: "sinceLaunch", label: "Since launch", val: (m) => m.sinceLaunch, fmt: (m) => `<span class="${cls(m.sinceLaunch)}">${pct(m.sinceLaunch)}</span>` },
  ];
  function renderLB() {
    const { key, dir } = S.sort, col = LB_COLS.find((c) => c.key === key);
    const rows = M.filter((m) => S.brand === "all" || m.brand === S.brand).slice().sort((a, b) => {
      const x = col.val(a), y = col.val(b);
      if (x == null) return 1; if (y == null) return -1;
      return (typeof x === "string" ? x.localeCompare(y) : x - y) * dir;
    });
    const maxR = Math.max(...M.map((m) => m.ratio || 0));
    $("#lbTable").innerHTML = `<thead><tr>${LB_COLS.map((c) => `<th data-k="${c.key}" ${c.key === key ? `aria-sort="${dir > 0 ? "ascending" : "descending"}"` : ""} tabindex="0">${c.label}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((m) => `<tr data-id="${m.id}" tabindex="0">${LB_COLS.map((c) => c.bar
        ? `<td class="bar-cell">${c.fmt(m)}<span class="bar" style="width:${Math.max(4, ((m.ratio || 0) / maxR) * 90)}px"></span></td>`
        : `<td>${c.fmt(m)}</td>`).join("")}</tr>`).join("")}</tbody>`;
    $$("#lbTable th").forEach((th) => {
      const go = () => { const k = th.dataset.k; S.sort = { key: k, dir: S.sort.key === k ? -S.sort.dir : k === "name" ? 1 : -1 }; renderLB(); };
      th.onclick = go; th.onkeydown = (e) => e.key === "Enter" && go();
    });
    $$("#lbTable tbody tr").forEach((tr) => { tr.onclick = () => openDrawer(tr.dataset.id); tr.onkeydown = (e) => e.key === "Enter" && openDrawer(tr.dataset.id); });
  }

  // ------------------------------------------------------------------ dumbbell + vram
  function renderDumbbell() {
    const list = M.filter((m) => m.ratio && (S.brand === "all" || m.brand === S.brand)).sort((a, b) => a.ratio - b.ratio);
    const ch = mk("dumbbell");
    ch.setOption({
      backgroundColor: "transparent",
      grid: { left: 8, right: 56, top: 8, bottom: 28, containLabel: true },
      tooltip: { ...tooltipBase(), trigger: "item", formatter: (p) => { const m = list[p.value[2]];
        return `<b>${esc(m.name)}</b><br>Launch ${fmtDate(m.launch)}: <b style="font-family:${MONO}">${ratio(m.launchRatio)}</b> per BTC<br><span style="color:${C.muted}">${usd(m.msrp)} MSRP · BTC ${usd(m.launchBtc)}</span><br>Today: <b style="font-family:${MONO}">${ratio(m.ratio)}</b> per BTC<br><span style="color:${C.muted}">${usd(m.price)} retail · BTC ${usd(BTC.p[BTC.p.length - 1])}</span><br><b class="${cls(m.sinceLaunch)}" style="color:${m.sinceLaunch >= 0 ? C.good : C.bad}">${pct(m.sinceLaunch)}</b>`; } },
      xAxis: { type: "log", ...baseAxis(), axisLabel: { ...baseAxis().axisLabel, formatter: (v) => num(v, 0) }, min: 1 },
      yAxis: { type: "category", data: list.map((m) => m.short), ...baseAxis(), splitLine: { show: false }, axisLine: { show: false }, axisLabel: { color: C.ink2, fontFamily: SANS, fontSize: 12, fontWeight: 600 } },
      series: [{
        type: "custom", encode: { x: [0, 1], y: 2 },
        data: list.map((m, i) => [m.launchRatio, m.ratio, i]),
        renderItem: (params, api) => {
          const a = api.coord([api.value(0), api.value(2)]), b = api.coord([api.value(1), api.value(2)]);
          const m = list[api.value(2)], up = m.sinceLaunch >= 0;
          return { type: "group", children: [
            { type: "line", shape: { x1: a[0], y1: a[1], x2: b[0], y2: b[1] }, style: { stroke: C.axis, lineWidth: 3, lineCap: "round" } },
            { type: "circle", shape: { cx: a[0], cy: a[1], r: 5.5 }, style: { fill: C.muted, stroke: C.surface, lineWidth: 2 } },
            { type: "circle", shape: { cx: b[0], cy: b[1], r: 6.5 }, style: { fill: C.slots[0], stroke: C.surface, lineWidth: 2 } },
            { type: "text", x: Math.max(a[0], b[0]) + 10, y: a[1], style: { text: pct(m.sinceLaunch), fill: up ? C.good : C.bad, font: `600 11px ${SANS}`, verticalAlign: "middle" } },
          ] };
        },
      }],
    });
    ch.off("click"); ch.on("click", (p) => openDrawer(list[p.value[2]].id));
  }
  function renderVram() {
    const list = M.filter((m) => m.satsPerGB && (S.brand === "all" || m.brand === S.brand)).sort((a, b) => b.satsPerGB - a.satsPerGB);
    const ch = mk("vramChart");
    ch.setOption({
      backgroundColor: "transparent",
      grid: { left: 8, right: 64, top: 8, bottom: 28, containLabel: true },
      tooltip: { ...tooltipBase(), trigger: "item", formatter: (p) => { const m = list[p.dataIndex]; return `<b>${esc(m.name)}</b><br><b style="font-family:${MONO}">${sats(m.satsPerGB)}</b> sats per GB<br><span style="color:${C.muted}">${m.vram} GB · ${sats(m.sats)} sats · ${usd(m.price)}</span>`; } },
      xAxis: { type: "value", ...baseAxis(), axisLabel: { ...baseAxis().axisLabel, formatter: (v) => sats(v) } },
      yAxis: { type: "category", data: list.map((m) => `${m.short}  ·  ${m.vram}GB`), ...baseAxis(), splitLine: { show: false }, axisLine: { show: false }, axisLabel: { color: C.ink2, fontFamily: SANS, fontSize: 12, fontWeight: 600 } },
      series: [{ type: "bar", data: list.map((m) => m.satsPerGB), barWidth: "56%", itemStyle: { color: C.slots[0], borderRadius: [0, 4, 4, 0] },
        emphasis: { itemStyle: { color: "#5598e7" } },
        label: { show: true, position: "right", color: C.ink2, fontFamily: MONO, fontSize: 11, formatter: (p) => sats(p.value) } }],
    });
    ch.off("click"); ch.on("click", (p) => openDrawer(list[p.dataIndex].id));
  }

  // ------------------------------------------------------------------ time machine
  const TM = { dates: [], i: 0, timer: null };
  function tmValue(m, d) {
    if (d < m.launch) return null;
    for (let k = 0; k < 4; k++) { const r = m.retailMap.get(addDays(d, -k)); if (r) return { v: btcAt(d) / r.avg, p: r.avg, msrp: false }; }
    if (m.retail.length && d > m.retail[0].d) { const prev = m.retail.filter((r) => r.d <= d).pop(); if (prev) return { v: btcAt(d) / prev.avg, p: prev.avg, msrp: false }; }
    return { v: btcAt(d) / m.msrp, p: m.msrp, msrp: true };
  }
  function initTM() {
    const first = M.map((m) => m.launch).sort()[0];
    TM.dates = BTC.d.filter((d) => d >= first);
    const sl = $("#tmSlider"); sl.max = TM.dates.length - 1; sl.value = TM.i = TM.dates.length - 1;
    sl.oninput = () => { stopTM(); TM.i = +sl.value; renderTM(); };
    $("#tmPlay").onclick = () => (TM.timer ? stopTM() : playTM());
    mk("tmChart"); renderTM(true);
  }
  function playTM() {
    if (TM.i >= TM.dates.length - 1) TM.i = 0;
    $("#tmPlay").textContent = "❚❚ Pause";
    TM.timer = setInterval(() => {
      TM.i = Math.min(TM.dates.length - 1, TM.i + 4);
      $("#tmSlider").value = TM.i; renderTM();
      if (TM.i >= TM.dates.length - 1) stopTM();
    }, 90);
  }
  function stopTM() { clearInterval(TM.timer); TM.timer = null; $("#tmPlay").textContent = "▶ Play"; }
  function renderTM(first) {
    const d = TM.dates[TM.i];
    $("#tmDate").textContent = fmtDate(d);
    $("#tmBtc").textContent = "BTC " + usd(btcAt(d));
    const list = M.filter((m) => S.brand === "all" || m.brand === S.brand);
    const vals = list.map((m) => tmValue(m, d));
    const ch = charts.tmChart;
    ch.setOption({
      backgroundColor: "transparent",
      animationDuration: first ? 400 : 0, animationDurationUpdate: 160, animationEasing: "linear", animationEasingUpdate: "linear",
      grid: { left: 8, right: 70, top: 6, bottom: 24, containLabel: true },
      tooltip: { ...tooltipBase(), trigger: "item", formatter: (p) => { const m = list[p.dataIndex], v = vals[p.dataIndex]; if (!v) return `${esc(m.name)}: not launched until ${fmtDate(m.launch)}`;
        return `<b>${esc(m.name)}</b> · ${fmtDate(d)}<br><b style="font-family:${MONO}">${ratio(v.v)}</b> per BTC<br><span style="color:${C.muted}">${usd(v.p)} ${v.msrp ? "MSRP (before retail tracking)" : "retail avg"} · BTC ${usd(btcAt(d))}</span>`; } },
      xAxis: { type: "value", max: "dataMax", ...baseAxis(), axisLabel: { ...baseAxis().axisLabel, formatter: (v) => num(v, 0) } },
      yAxis: { type: "category", inverse: true, data: list.map((m) => m.short), animationDuration: 300, animationDurationUpdate: 300, ...baseAxis(), splitLine: { show: false }, axisLine: { show: false }, axisLabel: { color: C.ink2, fontFamily: SANS, fontSize: 12, fontWeight: 600 } },
      series: [{
        type: "bar", realtimeSort: true, barWidth: "62%",
        data: vals.map((v, i) => ({
          value: v ? +v.v.toFixed(2) : 0,
          itemStyle: {
            color: v ? C.brand[list[i].brand] : "transparent", borderRadius: [0, 4, 4, 0], opacity: v ? 0.92 : 0,
            ...(v && v.msrp ? { decal: { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [3, 5], rotation: Math.PI / 4, color: "rgba(0,0,0,.45)", symbolSize: 1 } } : {}),
          },
        })),
        label: { show: true, position: "right", valueAnimation: true, color: C.ink, fontFamily: MONO, fontSize: 12, fontWeight: 700, formatter: (p) => (p.value ? ratio(p.value) : "") },
      }],
    });
    if (first) { ch.off("click"); ch.on("click", (p) => openDrawer(list[p.dataIndex].id)); }
  }

  // ------------------------------------------------------------------ calculator
  function renderCalc() {
    const amt = parseFloat($("#calcAmt").value) || 0;
    const btcNow = BTC.p[BTC.p.length - 1];
    const btc = S.unit === "btc" ? amt : S.unit === "sats" ? amt / 1e8 : amt / btcNow;
    $("#calcEquiv").textContent = `= ${num(btc, btc < 1 ? 6 : 4)} BTC · ${sats(btc * 1e8)} sats · ${usd(btc * btcNow)}`;
    const list = M.filter((m) => m.price && (S.brand === "all" || m.brand === S.brand)).sort((a, b) => b.price - a.price);
    $("#calcGrid").innerHTML = list.map((m) => {
      const n = (btc * btcNow) / m.price, then = btc * m.launchRatio;
      const whole = Math.floor(n), cap = 48, pips = Math.min(whole, cap);
      const pipHtml = n > 0 ? Array.from({ length: pips }, () => "<b></b>").join("") + (whole < cap && n - whole > 0.05 ? `<b class="part"></b>` : "") + (whole > cap ? `<span class="t">+${whole - cap}</span>` : "") : "";
      return `<div class="calc-item"><span class="l"><i class="b-${m.brand}"></i>${esc(m.short)}</span><span class="n">${num(n, n < 10 ? 2 : 1)}</span>
        <span class="t">at launch: ${num(then, then < 10 ? 2 : 1)} <span class="${cls(n / then - 1)}">(${pct(n / then - 1)})</span></span><div class="pips">${pipHtml}</div></div>`;
    }).join("");
  }

  // ------------------------------------------------------------------ drawer
  let lastFocus = null, openId = null;
  function links(m) {
    const q = encodeURIComponent(m.name.replace(/^(GeForce|Radeon) /, (s) => s));
    const qs = encodeURIComponent(m.short);
    const L = [
      ["eBay sold listings", "Completed sales, newest first", `https://www.ebay.com/sch/i.html?_nkw=${q}&_sacat=27386&LH_Sold=1&LH_Complete=1&_sop=13`],
      ["pcprice.watch", "eBay sold medians across 7 markets", `https://www.pcprice.watch/gpu-buying-guide/${m.id}-price-used-and-specs`],
      ["GPU Price History", "Daily US retail min/avg chart", `https://gpupricehistory.com/us/${m.id}`],
      ["Best Value GPU", "Monthly new and used price history", `https://bestvaluegpu.com/history/new-and-used-${m.id}-price-history-and-specs/`],
      VCP.has(m.id) ? ["videocardprices", "Daily Amazon/Newegg tracker", `https://videocardprices.com/card/${m.brand.toLowerCase()}-${m.id}/`] : null,
      ["r/hardwareswap", "Peer-to-peer sales threads", `https://www.reddit.com/r/hardwareswap/search/?q=${qs}&restrict_sr=1&sort=new`],
      ["PCPartPicker", "Retailer price comparison", `https://pcpartpicker.com/search/?q=${qs}`],
      ["Newegg", "Current new listings", `https://www.newegg.com/p/pl?d=${q}`],
      ["Amazon", "Current new listings", `https://www.amazon.com/s?k=${q}+graphics+card`],
      ["Micro Center", "In-store stock and price", `https://www.microcenter.com/search/search_results.aspx?Ntt=${qs}`],
      ["TechPowerUp specs", "Full specification sheet", `https://www.techpowerup.com/gpu-specs/?q=${qs}`],
    ].filter(Boolean);
    return L.map(([t, s, u]) => `<a href="${u}" target="_blank" rel="noopener"><b>${t} ↗</b><span>${s}</span></a>`).join("");
  }
  function openDrawer(id) {
    const m = byId[id]; if (!m) return;
    openId = id; lastFocus = document.activeElement;
    const btcNow = BTC.p[BTC.p.length - 1];
    const u = m.used;
    let usedHtml = `<p class="muted">No eBay sold data right now.</p>`;
    if (u) {
      const lo = Math.min(u.low, m.msrp) * 0.92, hi = Math.max(u.high, m.price || 0) * 1.04, X = (v) => ((v - lo) / (hi - lo)) * 100;
      usedHtml = `<div class="used-bar" role="img" aria-label="eBay sold range ${usd(u.low)} to ${usd(u.high)}, median ${usd(u.median)}, MSRP ${usd(m.msrp)}">
        <div class="rng" style="left:${X(u.low)}%;width:${X(u.high) - X(u.low)}%"></div>
        <div class="msrp" style="left:${X(m.msrp)}%" title="MSRP"></div>
        <div class="med" style="left:${X(u.median)}%" title="Median"></div></div>
        <div class="used-legend"><span>MSRP ${usd(m.msrp)}</span><span>typical ${usd(u.low)}–${usd(u.high)}</span><span style="color:var(--accent)">median ${usd(u.median)}</span></div>
        <p class="sub" style="margin-top:8px">${u.sales} completed eBay sales over 90 days (as of ${fmtDate(u.date)}).${u.peak ? ` Peak monthly median ${usd(u.peak)} in ${esc(u.peak_month)}.` : ""}
        In bitcoin, a used one costs <b class="mono">${sats((u.median / btcNow) * 1e8)}</b> sats, so 1 BTC buys <b class="mono">${ratio(btcNow / u.median)}</b>.</p>`;
    }
    const listings = m.listings.slice(0, 8).map((l) => `<a class="listing" href="https://www.google.com/search?tbm=shop&q=${encodeURIComponent(l.name)}" target="_blank" rel="noopener">
        <img src="${esc(l.img)}" alt="" loading="lazy" referrerpolicy="no-referrer"><span class="nm" title="${esc(l.name)}">${esc(l.name)}</span><span class="sats">${sats((l.price / btcNow) * 1e8)}</span><span class="pr">${usd(l.price)}</span></a>`).join("");
    $("#drawerBody").innerHTML = `
      <div class="d-hero">
        <img src="assets/img/gpus/${m.id}.webp" alt="${esc(m.name)}">
        <div>
          <span class="d-brand"><i class="dot b-${m.brand}"></i>${m.brand} · ${esc(m.arch)}</span>
          <h2 class="d-title" id="dTitle">${esc(m.name)}</h2>
          <div class="d-ratio">${ratio(m.ratio)}<small>per BTC today</small></div>
          <div class="specs"><span>${m.vram} GB ${m.mem}</span><span>${m.tdp} W</span><span>MSRP ${usd(m.msrp)}</span><span>Launched ${fmtDate(m.launch)}</span></div>
          <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap">
            <button class="btn btn-accent" type="button" id="dShare">Share this GPU</button>
            <button class="btn" type="button" id="dChart">${S.sel.includes(m.id) ? "✓ On main chart" : "＋ Add to main chart"}</button>
          </div>
        </div>
      </div>
      <div class="tiles">
        <div class="tile"><div class="k">Retail avg</div><div class="v">${usd(m.price)}</div><div class="s">low ${usd(m.low)}</div></div>
        <div class="tile"><div class="k">Sats each</div><div class="v">${sats(m.sats)}</div><div class="s">${num(m.sats / 1e8, 4)} BTC</div></div>
        <div class="tile"><div class="k">vs MSRP</div><div class="v ${m.premium > 0 ? "down" : "up"}">${pct(m.premium)}</div><div class="s">${usd(m.msrp)} launch</div></div>
        <div class="tile"><div class="k">30-day</div><div class="v ${cls(m.chg30)}">${pct(m.chg30, 1)}</div><div class="s">7d ${pct(m.chg7, 1)}</div></div>
        <div class="tile"><div class="k">At launch</div><div class="v">${ratio(m.launchRatio)}</div><div class="s">per BTC · BTC ${usd(m.launchBtc)}</div></div>
        <div class="tile"><div class="k">Since launch</div><div class="v ${cls(m.sinceLaunch)}">${pct(m.sinceLaunch)}</div><div class="s">BTC purchasing power</div></div>
        <div class="tile"><div class="k">Best (tracked)</div><div class="v">${m.ath ? ratio(m.ath.v) : "–"}</div><div class="s">${m.ath ? fmtDate(m.ath.d) : ""}</div></div>
        <div class="tile"><div class="k">Worst (tracked)</div><div class="v">${m.atl ? ratio(m.atl.v) : "–"}</div><div class="s">${m.atl ? fmtDate(m.atl.d) : ""}</div></div>
      </div>
      <div class="d-sec"><h3>GPUs per BTC</h3><div class="legend static" style="margin:0;min-height:0">
        <span><i class="sw" style="background:${C.slots[0]}"></i>Retail avg</span><span><i class="sw" style="background:${C.slots[2]}"></i>Lowest</span><span><i class="sw" style="background:${C.muted}"></i>At MSRP</span></div></div>
      <div class="d-chart" id="dRatio" role="img" aria-label="GPUs per BTC for ${esc(m.short)}"></div>
      <div class="d-sec"><h3>USD price</h3><div class="legend static" style="margin:0;min-height:0">
        <span><i class="sw" style="background:${C.slots[0]}"></i>Retail avg</span><span><i class="sw" style="background:${C.slots[2]}"></i>Lowest</span><span><i class="sw" style="background:${C.accent};height:8px;width:8px;border-radius:50%"></i>eBay sold median</span><span><i class="sw" style="background:${C.muted}"></i>MSRP</span></div></div>
      <div class="d-chart" id="dPrice" role="img" aria-label="USD price history for ${esc(m.short)}"></div>
      <div class="d-sec"><h3>Used market (eBay sold)</h3></div>
      ${usedHtml}
      ${listings ? `<div class="d-sec"><h3>Current retail listings</h3><span class="muted" style="font-size:12px">sats · USD</span></div><div class="listings">${listings}</div>` : ""}
      <div class="d-sec"><h3>Historic sales & price trackers</h3></div>
      <div class="links">${links(m)}</div>`;
    $("#scrim").hidden = false;
    const dr = $("#drawer"); dr.classList.add("open"); dr.setAttribute("aria-hidden", "false"); dr.scrollTop = 0;
    document.body.style.overflow = "hidden";
    setTimeout(() => dr.focus(), 50);
    $("#dShare").onclick = () => openShare(m.id);
    $("#dChart").onclick = (e) => { toggleSel(m.id); e.target.textContent = S.sel.includes(m.id) ? "✓ On main chart" : "＋ Add to main chart"; };
    requestAnimationFrame(() => drawerCharts(m));
    writeHash();
  }
  function drawerCharts(m) {
    const start = m.retail.length ? addDays(m.retail[0].d, -30) : m.launch;
    const common = (fmt) => ({
      backgroundColor: "transparent", animationDuration: 500,
      grid: { left: 6, right: 14, top: 10, bottom: 54, containLabel: true },
      tooltip: { ...tooltipBase(), trigger: "axis", axisPointer: { lineStyle: { color: C.axis } },
        formatter: (ps) => `<b>${fmtDate(ps[0].value[0])}</b><br>` + ps.filter((p) => p.value && p.value[1] != null).map((p) => `<span style="color:${C.ink2}">${p.seriesName}</span> <b style="font-family:${MONO}">${fmt(p.value[1])}</b>`).join("<br>") + `<br><span style="color:${C.muted}">BTC ${usd(btcAt(ps[0].value[0]))}</span>` },
      xAxis: { type: "time", ...baseAxis(), splitLine: { show: false }, axisLabel: { ...baseAxis().axisLabel, hideOverlap: true } },
      dataZoom: [{ type: "inside", startValue: start, filterMode: "none" }, { type: "slider", startValue: start, height: 22, bottom: 8, borderColor: C.line, backgroundColor: C.page, fillerColor: "rgba(247,147,26,.10)", textStyle: { color: C.muted, fontSize: 10 }, handleStyle: { color: C.ink2, borderColor: C.axis }, dataBackground: { lineStyle: { color: C.axis }, areaStyle: { color: C.surface } } }],
    });
    const line = (name, data, color, extra = {}) => ({ name, type: "line", data, showSymbol: false, lineStyle: { width: 2, color }, itemStyle: { color }, ...extra });
    const r = mk("dRatio");
    r.setOption({ ...common(ratio),
      yAxis: { type: "value", scale: true, ...baseAxis(), axisLine: { show: false } },
      series: [
        line("At MSRP", metricSeries(m, "gpb", "msrp"), C.muted, { lineStyle: { width: 1.5, color: C.muted, type: [4, 4] }, sampling: "lttb" }),
        line("Lowest", metricSeries(m, "gpb", "min"), C.slots[2]),
        line("Retail avg", metricSeries(m, "gpb", "avg"), C.slots[0], { areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: "rgba(57,135,229,.22)" }, { offset: 1, color: "rgba(57,135,229,0)" }]) } }),
      ] });
    const p = mk("dPrice");
    p.setOption({ ...common(usd),
      yAxis: { type: "value", scale: true, min: (v) => Math.floor(Math.min(v.min, m.msrp) * 0.9), ...baseAxis(), axisLine: { show: false }, axisLabel: { ...baseAxis().axisLabel, formatter: (v) => "$" + (v >= 1000 ? num(v / 1000, 1) + "k" : v) } },
      series: [
        line("Lowest", m.retail.map((x) => [x.d, x.min]), C.slots[2]),
        line("Retail avg", m.retail.map((x) => [x.d, x.avg]), C.slots[0], {
          markLine: { silent: true, symbol: "none", lineStyle: { color: C.muted, type: [4, 4] }, label: { color: C.muted, formatter: `MSRP ${usd(m.msrp)}`, position: "insideStartTop", fontSize: 11 }, data: [{ yAxis: m.msrp }] } }),
        { name: "eBay sold median", type: "scatter", data: m.usedHist, symbolSize: 9, itemStyle: { color: C.accent, borderColor: C.surface, borderWidth: 2 } },
      ] });
  }
  function closeDrawer() {
    const dr = $("#drawer"); dr.classList.remove("open"); dr.setAttribute("aria-hidden", "true");
    $("#scrim").hidden = true; document.body.style.overflow = ""; openId = null;
    ["dRatio", "dPrice"].forEach((k) => { if (charts[k]) { charts[k].dispose(); delete charts[k]; } });
    writeHash(); if (lastFocus) lastFocus.focus();
  }

  // ------------------------------------------------------------------ share
  function siteBase() { const u = new URL(location.href); u.hash = ""; u.search = ""; u.pathname = u.pathname.replace(/[^/]*$/, ""); return u.toString(); }
  function openShare(id) {
    const m = id && byId[id];
    const base = siteBase();
    const url = m ? `${base}m/${m.id}/` : base + (location.hash || "");
    const text = m
      ? `1 BTC buys ${ratio(m.ratio)} ${m.name}s today (${usd(m.price)} each, ${sats(m.sats)} sats). At launch it was ${ratio(m.launchRatio)}.`
      : `How many GPUs does 1 bitcoin buy? ${M.filter((x) => ["rtx-5090", "rx-9070-xt", "arc-b580"].includes(x.id)).map((x) => `${x.short}: ${ratio(x.ratio)}`).join(" · ")}`;
    $("#sharePreview").src = `assets/img/og/${m ? m.id : "og"}.png?v=${DATA.updated.slice(0, 10)}`;
    $("#shareText").textContent = text;
    const enc = encodeURIComponent;
    const btns = [
      navigator.share ? `<button class="btn btn-accent" data-act="native" type="button">Share…</button>` : "",
      `<a class="btn" target="_blank" rel="noopener" href="https://twitter.com/intent/tweet?text=${enc(text)}&url=${enc(url)}">X / Twitter</a>`,
      `<a class="btn" target="_blank" rel="noopener" href="https://www.reddit.com/submit?url=${enc(url)}&title=${enc(text)}">Reddit</a>`,
      `<a class="btn" target="_blank" rel="noopener" href="https://t.me/share/url?url=${enc(url)}&text=${enc(text)}">Telegram</a>`,
      `<a class="btn" target="_blank" rel="noopener" href="https://bsky.app/intent/compose?text=${enc(text + " " + url)}">Bluesky</a>`,
      `<button class="btn" data-act="nostr" type="button" title="Copy a note for Nostr">Nostr</button>`,
      `<button class="btn" data-act="copy" type="button">Copy link</button>`,
      `<a class="btn" href="assets/img/og/${m ? m.id : "og"}.png" download="sats-per-silicon-${m ? m.id : "card"}.png">Download card</a>`,
    ];
    $("#shareRow").innerHTML = btns.join("");
    $("#shareRow").onclick = async (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act; if (!act) return;
      try {
        if (act === "native") await navigator.share({ title: "Sats per Silicon", text, url });
        if (act === "copy") { await navigator.clipboard.writeText(url); toast("Link copied"); }
        if (act === "nostr") { await navigator.clipboard.writeText(`${text}\n\n${url}`); toast("Note copied. Paste it into your Nostr client."); }
      } catch (_) { /* user cancelled */ }
    };
    $("#shareSheet").hidden = false;
    $("#shareSheet [data-close]").focus();
  }

  // ------------------------------------------------------------------ hash state
  function writeHash() {
    const p = new URLSearchParams();
    if (S.sel.join() !== DEFAULT_SEL.join()) p.set("m", S.sel.join(","));
    if (S.metric !== "gpb") p.set("metric", S.metric);
    if (S.basis !== "avg") p.set("basis", S.basis);
    if (S.range !== "all") p.set("range", S.range);
    if (S.log) p.set("log", "1");
    if (S.brand !== "all") p.set("brand", S.brand);
    if (openId) p.set("open", openId);
    const h = p.toString();
    history.replaceState(null, "", h ? "#" + h.replace(/%2C/g, ",") : location.pathname + location.search);
  }
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    const ids = (p.get("m") || DEFAULT_SEL.join(",")).split(",").filter((id) => byId[id]);
    S.sel = []; S.slot.clear(); ids.slice(0, MAX_SERIES).forEach(addSel);
    if (["gpb", "sats", "usd", "idx"].includes(p.get("metric"))) S.metric = p.get("metric");
    if (["avg", "min", "msrp"].includes(p.get("basis"))) S.basis = p.get("basis");
    if (["1m", "3m", "6m", "ytd", "all"].includes(p.get("range"))) S.range = p.get("range");
    S.log = p.get("log") === "1";
    if (["NVIDIA", "AMD", "Intel"].includes(p.get("brand"))) S.brand = p.get("brand");
    return p.get("open");
  }

  // ------------------------------------------------------------------ controls
  function bindSeg(id, key, after) {
    const el = $(id);
    const paint = () => $$("button", el).forEach((b) => b.setAttribute("aria-checked", String(b.dataset.v === S[key])));
    el.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S[key] = b.dataset.v; paint(); after(); writeHash(); });
    paint();
  }
  function bind() {
    bindSeg("#metricSeg", "metric", renderMain);
    bindSeg("#basisSeg", "basis", renderMain);
    bindSeg("#rangeSeg", "range", renderMain);
    bindSeg("#unitSeg", "unit", () => {
      const btcNow = BTC.p[BTC.p.length - 1], inp = $("#calcAmt");
      inp.value = S.unit === "btc" ? 0.1 : S.unit === "sats" ? 1e6 : Math.round(btcNow * 0.1);
      renderCalc();
    });
    $("#logToggle").checked = S.log;
    $("#logToggle").onchange = (e) => { S.log = e.target.checked; renderMain(); writeHash(); };
    $("#calcAmt").oninput = renderCalc;
    $$("#brandChips .chip").forEach((c) => {
      c.classList.toggle("on", c.dataset.brand === S.brand);
      c.onclick = () => {
        S.brand = c.dataset.brand; $$("#brandChips .chip").forEach((x) => x.classList.toggle("on", x === c));
        renderWallState(); renderLB(); renderDumbbell(); renderVram(); renderTM(); renderCalc(); writeHash();
      };
    });
    $("#dlChart").onclick = () => {
      const a = document.createElement("a");
      a.href = charts.mainChart.getDataURL({ pixelRatio: 2, backgroundColor: C.surface });
      a.download = `sats-per-silicon-${S.metric}-${BTC.d[BTC.d.length - 1]}.png`; a.click();
    };
    $("#tableToggle").onclick = (e) => {
      const box = $("#chartTable"); box.hidden = !box.hidden; e.target.setAttribute("aria-pressed", String(!box.hidden));
      e.target.textContent = box.hidden ? "Table" : "Chart only"; renderMain();
    };
    $("#shareBtn").onclick = () => openShare(null);
    $("#drawerClose").onclick = closeDrawer;
    $("#scrim").onclick = closeDrawer;
    $("#shareSheet").addEventListener("click", (e) => { if (e.target.id === "shareSheet" || e.target.closest("[data-close]")) $("#shareSheet").hidden = true; });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (!$("#shareSheet").hidden) $("#shareSheet").hidden = true; else if (openId) closeDrawer();
    });
    window.addEventListener("hashchange", () => { const o = new URLSearchParams(location.hash.slice(1)).get("open"); if (o && o !== openId) openDrawer(o); });
  }

  // ------------------------------------------------------------------ boot
  async function boot() {
    const [cfg, data] = await Promise.all([
      fetch("data/models.json").then((r) => r.json()),
      fetch("data/data.json", { cache: "no-cache" }).then((r) => r.json()),
    ]);
    prep(cfg, data);
    const open = readHash();
    const btcNow = BTC.p[BTC.p.length - 1], btcPrev = btcAt(addDays(BTC.d[BTC.d.length - 1], -1));
    $("#btcPrice").textContent = usd(btcNow);
    const ch = btcNow / btcPrev - 1; $("#btcChg").textContent = pct(ch, 1); $("#btcChg").className = "ticker-chg mono " + cls(ch);
    const upd = new Date(data.updated);
    $("#updated").textContent = upd.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    $("#footUpdated").textContent = "Data updated " + upd.toUTCString().replace(" GMT", " UTC");
    bind();
    renderHero(); renderWall(); renderLegend(); renderMain(); renderLB(); renderDumbbell(); renderVram(); initTM(); renderCalc();
    if (open && byId[open]) openDrawer(open);
  }
  boot().catch((e) => { console.error(e); document.querySelector("#heroNote").textContent = "Could not load data: " + e.message; });
})();
