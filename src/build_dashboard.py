"""Build docs/dashboard.html: an interactive, single-file version of the Excel tracker for GitHub Pages.

    python src/build_dashboard.py

The data comes from data/marts (same tables as the Excel tracker) and is embedded as JSON, so the
page needs no server: GitHub Pages serves it as a static file. Charts use Chart.js from a CDN.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / "data" / "marts"
OUT = ROOT / "docs" / "dashboard.html"
REPO = "https://github.com/albt-france/techinsights-materials-pricing-case-study"


def r(x, d=4):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), d)


def build_data() -> dict:
    m = pd.read_csv(M / "monthly_prices.csv")
    mats = pd.read_csv(ROOT / "seeds" / "materials.csv").sort_values(["stage_order", "material_id"])
    periods = sorted(m.period.str[:7].unique())
    series = {}
    for mid, g in m.groupby("material_id"):
        g = g.assign(p=g.period.str[:7]).set_index("p").reindex(periods)
        series[mid] = {k: [r(v) for v in g[c]] for k, c in [("valid", "eu_import_uv_eur_kg"), ("raw", "eu_import_uv_raw_eur_kg"),
                                                             ("uv3", "eu_import_uv3_eur_kg"), ("lme", "wb_price_eur_kg"),
                                                             ("kg", "eu_import_kg")]}
        series[mid]["outlier"] = [bool(v) if isinstance(v, (bool, np.bool_)) else str(v).lower() == "true" for v in g.is_outlier.fillna(False)]
    nc = pd.read_csv(M / "nowcast.csv")
    nowcast = {mid: [{"period": p[:7], "value": r(v), "lo": r(lo), "hi": r(hi), "method": meth}
                     for p, v, lo, hi, meth in zip(g.period, g.nowcast_eur_kg, g.lo80_eur_kg, g.hi80_eur_kg, g.method)]
               for mid, g in nc[nc.selected == 1].sort_values("horizon").groupby("material_id")}
    bt = pd.read_csv(M / "nowcast_backtest.csv")
    backtest = {mid: {meth: [r(x) for x in gg.sort_values("horizon").mape] for meth, gg in g.groupby("method")}
                for mid, g in bt.groupby("material_id")}
    rs = pd.read_csv(M / "reconciliation_summary.csv")
    rd = pd.read_csv(M / "reconciliation_detail.csv")
    dl = pd.read_csv(M / "discrepancy_log.csv").set_index("discrepancy_id")
    pairs = []
    for row in rs.itertuples():
        d = rd[rd.pair_id == row.pair_id].sort_values("period")
        card = row.discrepancy_id if isinstance(row.discrepancy_id, str) else None
        pairs.append({"id": row.pair_id, "materials": row.material_key.strip("|").split("|"), "label": row.material_id,
                      "comparison": row.comparison, "median": r(row.median_gap), "latest": r(row.latest_gap),
                      "lo": r(row.expected_low), "hi": r(row.expected_high), "status": row.latest_status, "alerts": int(row.alerts),
                      "n": int(row.observations), "card": card,
                      "card_title": dl.loc[card, "title"] if card else None,
                      "cause": dl.loc[card, "root_cause"].split(". ")[0] + "." if card else None,
                      "detail": {"period": [p[:7] for p in d.period], "gap": [r(x) for x in d.gap],
                                 "series": [x if isinstance(x, str) else "" for x in d.detail]}})
    o = pd.read_csv(M / "origin_monthly.csv")
    o["year"] = o.period.str[:4]
    o["group"] = np.where(o.origin == "CN", "China", np.where(o.origin == "Confidential", "Confidential", "Other origins"))
    og = o.groupby(["material_id", "year", "group"]).quantity_kg.sum().unstack(fill_value=0) / 1000
    origins = {mid: {"years": list(g.index.get_level_values(1)),
                     **{grp: [r(x, 1) for x in g.get(grp, pd.Series(0, index=g.index))] for grp in ["China", "Other origins", "Confidential"]}}
               for mid, g in og.groupby(level=0)}
    collected = (ROOT / "data" / "raw" / "comext" / "_collected_on.txt").read_text().strip()
    return {"periods": periods, "materials": [{"id": x.material_id, "name": x.material, "stage": x.chain_stage,
                                               "grade": x.purity_or_grade, "use": x.fab_use} for x in mats.itertuples()],
            "series": series, "nowcast": nowcast, "backtest": backtest, "pairs": pairs, "origins": origins,
            "collected": collected, "repo": REPO}


HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fab Materials Price Tracker</title>
<meta name="description" content="Interactive tracker of semiconductor materials prices from public data: validated EU import unit values, source reconciliation and nowcasts.">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root { --bg:#F4F4F2; --card:#FCFCFB; --ink:#0B0B0B; --ink2:#52514E; --muted:#898781; --grid:#E1E0D9;
        --blue:#2A78D6; --orange:#EB6834; --green:#1BAF7A; --red:#D03B3B; --redtint:#F4C7C6; --bluetint:#CDE2FB; --grey:#B4B2AD; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg:#161615; --card:#1F1F1E; --ink:#F1F0EC; --ink2:#C2C0B9; --muted:#8F8D86; --grid:#34332F;
  --blue:#5598E7; --orange:#F08458; --green:#3CC28E; --red:#E5605F; --redtint:#4A2524; --bluetint:#1D3554; --grey:#6E6C66; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font-family:'Segoe UI', system-ui, -apple-system, sans-serif; font-size:14px; }
.wrap { max-width:1280px; margin:0 auto; padding:24px 16px 40px; }
header { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }
h1 { font-size:26px; margin:0 0 4px; line-height:1.2; }
.sub { color:var(--ink2); margin:0 0 6px; max-width:900px; line-height:1.45; }
.tag { font-size:11px; font-weight:700; letter-spacing:.06em; color:var(--ink2); white-space:nowrap; padding-top:8px; }
.links a { color:var(--blue); text-decoration:none; margin-right:14px; font-size:13px; }
.controls { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin:18px 0 14px; }
select { font:inherit; padding:7px 10px; border-radius:8px; border:1px solid var(--grid); background:var(--card); color:var(--ink); min-width:260px; }
.card { background:var(--card); border:1px solid var(--grid); border-radius:8px; padding:14px 16px; min-width:0; }
.card h3 { font-size:11px; letter-spacing:.05em; text-transform:uppercase; color:var(--ink2); margin:0 0 8px; }
.kpis { display:grid; grid-template-columns:repeat(4, 1fr); gap:12px; }
.kpi .v { font-size:30px; font-weight:700; line-height:1.1; }
.kpi .l { color:var(--ink2); font-size:12.5px; margin-top:4px; line-height:1.35; }
.grid2 { display:grid; grid-template-columns:2fr 1fr; gap:12px; margin-top:12px; }
.grid2b { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px; }
.chartbox { position:relative; height:330px; }
.chartbox.sm { height:240px; }
table { border-collapse:collapse; width:100%; font-size:13px; }
th { text-align:left; color:var(--ink2); font-weight:600; border-bottom:1px solid var(--ink2); padding:5px 6px; white-space:nowrap; }
td { padding:5px 6px; border-bottom:1px solid var(--grid); vertical-align:middle; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
tr.sel td { background:var(--bluetint); }
tbody.click tr { cursor:pointer; }
tbody.click tr:hover td { background:var(--bluetint); }
.alert { color:var(--red); font-weight:600; }
.pos { color:var(--blue); } .neg { color:var(--red); }
.pill { display:inline-block; padding:1px 7px; border-radius:9px; font-size:11.5px; background:var(--redtint); }
.note { color:var(--ink2); font-size:12.5px; line-height:1.45; margin:8px 0 0; }
.tablewrap { overflow-x:auto; }
h2 { font-size:18px; margin:28px 0 4px; }
footer { color:var(--muted); font-size:11.5px; margin-top:26px; line-height:1.5; }
a { color:var(--blue); }
@media (max-width: 900px) { .kpis { grid-template-columns:1fr 1fr; } .grid2, .grid2b { grid-template-columns:1fr; } h1 { font-size:21px; } }
</style></head>
<body><div class="wrap">
<header><div><h1>Fab materials prices, validated and reconciled</h1>
<p class="sub">15 semiconductor materials, from feedstock to doped wafers: EU import unit values (Eurostat Comext, EUR/kg) after quality checks,
compared with exchange prices and other sources, with a nowcast of the months not yet published.</p>
<div class="links"><a href="__REPO__">Repository</a><a href="__REPO__/blob/main/docs/TechInsights_MaterialsPricing_CaseStudy.pdf">Report (PDF)</a><a href="__REPO__/raw/main/excel/Semiconductor_Materials_Price_Tracker.xlsx">Excel tracker (.xlsx)</a><a href="__REPO__/blob/main/docs/DISCREPANCY_LOG.md">Discrepancy log</a></div></div>
<div class="tag">PUBLIC DATA</div></header>

<div class="controls"><label for="mat"><b>Material</b></label><select id="mat"></select><span id="matinfo" class="note" style="margin:0"></span></div>

<div class="kpis">
  <div class="card kpi"><h3>Latest validated unit value</h3><div class="v" id="k1"></div><div class="l" id="k1l"></div></div>
  <div class="card kpi"><h3>Change vs 12 months earlier</h3><div class="v" id="k2"></div><div class="l">3-month weighted unit value</div></div>
  <div class="card kpi"><h3>Nowcast, next month</h3><div class="v" id="k3"></div><div class="l" id="k3l"></div></div>
  <div class="card kpi"><h3>Source pairs in alert · outlier months</h3><div class="v alert" id="k4"></div><div class="l">latest gap outside its expected band · robust outliers (median/MAD)</div></div>
</div>

<div class="grid2">
  <div class="card"><h3 id="c1t">EUR per kg</h3><div class="chartbox"><canvas id="c1" aria-label="Unit value history"></canvas></div>
    <p class="note">Validated = partner flows inside the material's plausible price range. Hover for values; click legend items to hide series.</p></div>
  <div class="card"><h3>Where EU imports come from (tonnes per year)</h3><div class="chartbox"><canvas id="c2" aria-label="Import origins"></canvas></div>
    <p class="note" id="c2n"></p></div>
</div>

<div class="grid2b">
  <div class="card"><h3>Source pairs for this material</h3><div class="tablewrap"><table><thead><tr><th>Pair</th><th>Comparison</th><th class="num">Median gap</th><th class="num">Latest</th><th>Status</th><th>Card</th></tr></thead><tbody id="pairs" class="click"></tbody></table></div>
    <p class="note">Gap = source A / source B − 1. Click a pair to plot it below.</p></div>
  <div class="card"><h3>Nowcast back-test: mean absolute error by horizon</h3><div class="chartbox sm"><canvas id="c3" aria-label="Back-test errors"></canvas></div>
    <p class="note">24 rolling origins. naive = last value, ets = damped-trend exponential smoothing (Excel FORECAST.ETS), signal = regression on the LME price (metals only).</p></div>
</div>

<h2>Reconciliation explorer</h2>
<p class="sub">Each source pair has an expected band from its known cause (e.g. a CIF border value sits above a warehouse price). Outside the band = alert and a discrepancy card.</p>
<div class="controls"><label for="pair"><b>Pair</b></label><select id="pair"></select></div>
<div class="grid2">
  <div class="card"><h3 id="c4t"></h3><div class="chartbox"><canvas id="c4" aria-label="Gap between sources"></canvas></div></div>
  <div class="card"><h3>Discrepancy card</h3><div id="cardbox"></div></div>
</div>

<h2>All materials</h2>
<p class="sub">Click a row to select the material. Sparkline = last 24 months of the 3-month weighted unit value.</p>
<div class="card tablewrap"><table><thead><tr><th>Stage</th><th>Material</th><th class="num">Unit value 3m (EUR/kg)</th><th class="num">12-month change</th><th>Last 24 months</th><th class="num">Alerts</th><th class="num">Nowcast next month</th><th class="num">80% interval</th></tr></thead><tbody id="all" class="click"></tbody></table></div>

<footer>Sources: Eurostat Comext DS-045409 (CC BY 4.0), World Bank Pink Sheet (CC BY 4.0), USGS Mineral Commodity Summaries (public domain), UN Comtrade, IMF and BLS via FRED, ECB. Collected __COLLECTED__.
A customs unit value (value / kg) is a price indicator that mixes grades, not a transaction price.<br>
Independent case study based on public data · not affiliated with or endorsed by TechInsights.</footer>
</div>
<script>
const D = __DATA__;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const nf = (x, d) => x == null ? "–" : x.toLocaleString("en-US", {minimumFractionDigits: d, maximumFractionDigits: d});
const dec = x => x == null ? 2 : (Math.abs(x) >= 1000 ? 0 : Math.abs(x) >= 100 ? 1 : 2);
const pct = (x, d = 0) => x == null ? "–" : (x > 0 ? "+" : "") + (x * 100).toFixed(d) + "%";
const P = D.periods, byId = Object.fromEntries(D.materials.map(m => [m.id, m]));
let charts = {}, mat = "GE", pair = "R08";

function chg12(id) {
  const u = D.series[id].uv3, n = u.length - 1;
  return (u[n] != null && u[n - 12]) ? u[n] / u[n - 12] - 1 : null;
}
function lastValid(id) {
  const v = D.series[id].valid; for (let i = v.length - 1; i >= 0; i--) if (v[i] != null) return [v[i], P[i]]; return [null, null];
}
function pairsFor(id) { return D.pairs.filter(p => p.materials.includes(id)); }
function base(o = {}) {
  const ink2 = css("--ink2"), grid = css("--grid");
  return Object.assign({ responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: { legend: { position: "bottom", labels: { color: ink2, boxWidth: 14, font: { size: 12 } } },
               tooltip: { backgroundColor: css("--card"), titleColor: css("--ink"), bodyColor: ink2, borderColor: grid, borderWidth: 1 } },
    scales: { x: { ticks: { color: css("--muted"), maxTicksLimit: 9, maxRotation: 0 }, grid: { display: false } },
              y: { ticks: { color: css("--muted") }, grid: { color: grid } } } }, o);
}
function make(id, cfg) { if (charts[id]) charts[id].destroy(); charts[id] = new Chart(document.getElementById(id), cfg); }

function renderMaterial() {
  const s = D.series[mat], m = byId[mat], nc = D.nowcast[mat] || [];
  document.getElementById("mat").value = mat;
  document.getElementById("matinfo").textContent = m.stage + " · " + m.grade + " · used for: " + m.use;
  const [lv, lp] = lastValid(mat);
  document.getElementById("k1").textContent = nf(lv, dec(lv));
  document.getElementById("k1l").textContent = "EUR/kg, " + lp;
  const c = chg12(mat), k2 = document.getElementById("k2");
  k2.textContent = pct(c); k2.className = "v " + (c > 0 ? "pos" : "neg");
  if (nc.length) {
    document.getElementById("k3").textContent = nf(nc[0].value, dec(nc[0].value));
    document.getElementById("k3l").textContent = nc[0].period + " · 80% interval " + nf(nc[0].lo, dec(nc[0].lo)) + " – " + nf(nc[0].hi, dec(nc[0].hi)) + " · method " + nc[0].method;
  }
  const pa = pairsFor(mat), out = s.outlier.filter(Boolean).length;
  document.getElementById("k4").textContent = pa.filter(p => p.status === "ALERT").length + " · " + out;

  // history + nowcast
  const labels = P.concat(nc.map(n => n.period)), pad = a => a.concat(nc.map(() => null));
  const ncLine = P.map((_, i) => i === P.length - 1 ? s.valid[i] : null).concat(nc.map(n => n.value));
  const lo = P.map(() => null).concat(nc.map(n => n.lo)), hi = P.map(() => null).concat(nc.map(n => n.hi));
  const ds = [
    { label: "Validated unit value", data: pad(s.valid), borderColor: css("--blue"), borderWidth: 2, pointRadius: 0, spanGaps: false },
    { label: "As published", data: pad(s.raw), borderColor: css("--grey"), borderWidth: 1.5, pointRadius: 0 },
  ];
  if (s.lme.some(v => v != null)) ds.push({ label: "LME (World Bank), EUR/kg", data: pad(s.lme), borderColor: css("--ink2"), borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0 });
  ds.push({ label: "Nowcast", data: ncLine, borderColor: css("--red"), borderWidth: 2, pointRadius: 3, pointBackgroundColor: css("--red") });
  ds.push({ label: "80% interval", data: lo, borderColor: css("--red"), borderWidth: 1, borderDash: [3, 3], pointRadius: 0 });
  ds.push({ label: "80% interval (high)", data: hi, borderColor: css("--red"), borderWidth: 1, borderDash: [3, 3], pointRadius: 0 });
  document.getElementById("c1t").textContent = m.name + ": EUR per kg, monthly";
  make("c1", { type: "line", data: { labels, datasets: ds }, options: base({ plugins: Object.assign(base().plugins, {
    legend: { position: "bottom", labels: { color: css("--ink2"), boxWidth: 14, filter: i => !i.text.includes("(high)") } },
    tooltip: Object.assign(base().plugins.tooltip, { callbacks: { label: c => c.raw == null ? null : c.dataset.label + ": " + nf(c.raw, dec(c.raw)) } }) }) }) });

  // origins
  const o = D.origins[mat];
  make("c2", { type: "bar", data: { labels: o.years, datasets: [
      { label: "China", data: o["China"], backgroundColor: css("--blue") },
      { label: "Other origins", data: o["Other origins"], backgroundColor: css("--grey") },
      { label: "Confidential", data: o["Confidential"], backgroundColor: css("--orange") }] },
    options: base({ scales: { x: { stacked: true, ticks: { color: css("--muted") }, grid: { display: false } },
                              y: { stacked: true, ticks: { color: css("--muted") }, grid: { color: css("--grid") } } },
      plugins: Object.assign(base().plugins, { tooltip: Object.assign(base().plugins.tooltip, { callbacks: { label: c => c.dataset.label + ": " + nf(c.raw, 1) + " t" } }) }) }) });
  const tot = o.years.map((_, i) => o["China"][i] + o["Other origins"][i] + o["Confidential"][i]);
  const shares = o.years.map((y, i) => y + ": " + Math.round(100 * o["China"][i] / (tot[i] || 1)) + "%");
  document.getElementById("c2n").textContent = "Share from China by weight - " + shares.slice(-4).join(" · ") + ". Partial current year.";

  // pairs table
  const tb = document.getElementById("pairs");
  tb.innerHTML = pa.length ? pa.map(p => `<tr data-p="${p.id}"><td>${p.id}</td><td>${p.comparison}</td><td class="num">${pct(p.median)}</td><td class="num">${pct(p.latest)}</td>` +
      `<td>${p.status === "ALERT" ? '<span class="pill">ALERT</span>' : p.status}</td><td>${p.card ? `<a href="${D.repo}/blob/main/docs/DISCREPANCY_LOG.md#${p.card.toLowerCase()}" target="_blank" rel="noopener">${p.card}</a>` : ""}</td></tr>`).join("")
    : '<tr><td colspan="6">No second source for this material: it relies on the quality checks.</td></tr>';
  tb.querySelectorAll("tr[data-p]").forEach(tr => tr.onclick = e => { if (e.target.tagName !== "A") { pair = tr.dataset.p; renderPair(); document.getElementById("pair").scrollIntoView({ behavior: "smooth", block: "center" }); } });

  // back-test
  const b = D.backtest[mat] || {}, cols = { naive: css("--grey"), ets: css("--orange"), signal: css("--blue") };
  make("c3", { type: "bar", data: { labels: [1, 2, 3, 4, 5, 6].map(h => h + " mo"), datasets: Object.keys(b).map(k => ({ label: k, data: b[k], backgroundColor: cols[k] })) },
    options: base({ scales: { x: { ticks: { color: css("--muted") }, grid: { display: false } },
                              y: { ticks: { color: css("--muted"), callback: v => (v * 100).toFixed(0) + "%" }, grid: { color: css("--grid") } } },
      plugins: Object.assign(base().plugins, { tooltip: Object.assign(base().plugins.tooltip, { callbacks: { label: c => c.dataset.label + ": " + (c.raw * 100).toFixed(1) + "%" } }) }) }) });

  document.querySelectorAll("#all tr").forEach(tr => tr.classList.toggle("sel", tr.dataset.m === mat));
}

function renderPair() {
  const p = D.pairs.find(x => x.id === pair);
  document.getElementById("pair").value = pair;
  document.getElementById("c4t").textContent = p.id + " · " + p.label + " · " + p.comparison;
  const L = p.detail.period.map((x, i) => p.detail.series[i] ? x.slice(0, 4) + " " + p.detail.series[i].replace("USGS_", "") : x);
  const ds = [{ label: "Gap (A/B − 1)", data: p.detail.gap, borderColor: css("--blue"), borderWidth: 2, pointRadius: p.detail.gap.length < 40 ? 3 : 0,
                pointBackgroundColor: p.detail.gap.map(g => (p.lo != null && (g < p.lo || g > p.hi)) ? css("--red") : css("--blue")) }];
  if (p.lo != null) {
    ds.push({ label: "Expected band", data: L.map(() => p.lo), borderColor: css("--muted"), borderDash: [5, 4], borderWidth: 1.2, pointRadius: 0 });
    ds.push({ label: "band high", data: L.map(() => p.hi), borderColor: css("--muted"), borderDash: [5, 4], borderWidth: 1.2, pointRadius: 0 });
  }
  make("c4", { type: "line", data: { labels: L, datasets: ds }, options: base({
    scales: { x: { ticks: { color: css("--muted"), maxTicksLimit: 9, maxRotation: 0 }, grid: { display: false } },
              y: { ticks: { color: css("--muted"), callback: v => (v * 100).toFixed(0) + "%" }, grid: { color: css("--grid") } } },
    plugins: Object.assign(base().plugins, { legend: { position: "bottom", labels: { color: css("--ink2"), filter: i => i.text !== "band high" } },
      tooltip: Object.assign(base().plugins.tooltip, { callbacks: { label: c => c.dataset.label + ": " + pct(c.raw, 1) } }) }) }) });
  const band = p.lo == null ? "no band: the two series are not comparable per kg" : pct(p.lo) + " to " + pct(p.hi);
  document.getElementById("cardbox").innerHTML =
    `<p><b>${p.card ? p.card + " · " + p.card_title : "Control pair (no card)"}</b></p>` +
    `<p class="note">Expected band: ${band}. Median gap ${pct(p.median, 1)}, latest ${pct(p.latest, 1)}, ${p.alerts} alert(s) out of ${p.n} comparisons. Status: <b>${p.status}</b>.</p>` +
    (p.cause ? `<p class="note"><b>Root cause:</b> ${p.cause}</p><p class="note"><a href="${D.repo}/blob/main/docs/DISCREPANCY_LOG.md#${p.card.toLowerCase()}" target="_blank" rel="noopener">Open the full card: evidence, correction, prevention</a></p>` : "");
}

function renderAll() {
  const rows = D.materials.map(m => {
    const u = D.series[m.id].uv3, last = u[u.length - 1], c = chg12(m.id), nc = (D.nowcast[m.id] || [])[0] || {};
    const sp = u.slice(-24), mn = Math.min(...sp.filter(v => v != null)), mx = Math.max(...sp.filter(v => v != null));
    const pts = sp.map((v, i) => v == null ? null : `${(i * 100 / 23).toFixed(1)},${(22 - 20 * (v - mn) / ((mx - mn) || 1)).toFixed(1)}`).filter(Boolean).join(" ");
    const al = pairsFor(m.id).filter(p => p.status === "ALERT").length;
    return `<tr data-m="${m.id}"><td>${m.stage}</td><td><b>${m.id}</b> ${m.name}</td><td class="num">${nf(last, dec(last))}</td>` +
      `<td class="num ${c > 0 ? "pos" : "neg"}">${pct(c)}</td><td><svg width="110" height="24" viewBox="0 0 100 24" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${css("--blue")}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg></td>` +
      `<td class="num">${al ? '<span class="pill">' + al + "</span>" : 0}</td><td class="num">${nf(nc.value, dec(nc.value))}</td><td class="num">${nf(nc.lo, dec(nc.lo))} – ${nf(nc.hi, dec(nc.hi))}</td></tr>`;
  });
  const tb = document.getElementById("all");
  tb.innerHTML = rows.join("");
  tb.querySelectorAll("tr").forEach(tr => tr.onclick = () => { mat = tr.dataset.m; renderMaterial(); window.scrollTo({ top: 0, behavior: "smooth" }); });
}

function init() {
  const sel = document.getElementById("mat");
  let stage = "", html = "";
  D.materials.forEach(m => { if (m.stage !== stage) { if (stage) html += "</optgroup>"; html += `<optgroup label="${m.stage}">`; stage = m.stage; } html += `<option value="${m.id}">${m.name}</option>`; });
  sel.innerHTML = html + "</optgroup>";
  sel.onchange = () => { mat = sel.value; renderMaterial(); };
  const ps = document.getElementById("pair");
  ps.innerHTML = D.pairs.map(p => `<option value="${p.id}">${p.id} · ${p.label} · ${p.comparison}${p.status === "ALERT" ? "  (alert)" : ""}</option>`).join("");
  ps.onchange = () => { pair = ps.value; renderPair(); };
  renderAll(); renderMaterial(); renderPair();
}
init();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { renderAll(); renderMaterial(); renderPair(); });
</script>
</body></html>
"""


def main() -> None:
    data = build_data()
    html = (HTML.replace("__DATA__", json.dumps(data, separators=(",", ":"), ensure_ascii=False))
                .replace("__REPO__", REPO).replace("__COLLECTED__", data["collected"]))
    OUT.write_text(html, encoding="utf-8")
    (ROOT / "docs" / ".nojekyll").write_text("", encoding="utf-8")   # serve docs/ as plain static files
    print(f"  {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
