"""Build docs/TechInsights_MaterialsPricing_CaseStudy.pdf (16:9 landscape, ~11 pages).

    python src/build_report.py

Charts are drawn with matplotlib from the pipeline's DuckDB file and marts; pages are HTML
printed to PDF by Microsoft Edge (or Chrome) in headless mode; page images for the README are
rendered from the PDF. Every number on a page is computed here from the data, not typed in.
"""
from __future__ import annotations

import html
import shutil
import subprocess
from pathlib import Path

import duckdb
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "report"
PDF = ROOT / "docs" / "TechInsights_MaterialsPricing_CaseStudy.pdf"
IMG = ROOT / "docs" / "img"

INK, INK2, MUTED, GRID, BG, CARD = "#0B0B0B", "#52514E", "#898781", "#E1E0D9", "#F4F4F2", "#FCFCFB"
BLUE, ORANGE, GREEN, AMBER, RED = "#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#D03B3B"
GREY = "#B4B2AD"
CAT = [BLUE, ORANGE, GREEN, AMBER]             # validated categorical order (validate_palette.js: pass)
FOOT = "Independent case study based on public data · not affiliated with or endorsed by TechInsights"
# The AI-use note is read from the README ("## Methods note"), so it is written in one place only.
AI_NOTE = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8").split("## Methods note", 1)[1].strip().splitlines()[0]

plt.rcParams.update({
    "font.family": "Segoe UI", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "axes.facecolor": CARD, "figure.facecolor": CARD, "legend.frameon": False, "lines.linewidth": 2,
    "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlecolor": INK, "axes.titlelocation": "left",
})

con = duckdb.connect(str(ROOT / "data" / "materials.duckdb"), read_only=True)
M = ROOT / "data" / "marts"


def df(sql: str) -> pd.DataFrame:
    return con.sql(sql).df()


def save(fig, name: str) -> str:
    BUILD.mkdir(parents=True, exist_ok=True)
    fig.savefig(BUILD / f"{name}.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    return f"{name}.png"


def end_label(ax, x, y, text, color, dy=0):
    ax.annotate(text, (x, y), xytext=(4, dy), textcoords="offset points", color=INK2, fontsize=8, va="center")


def end_labels(ax, items, min_gap_frac=0.07):
    """items = [(x, y, text)] at the right end of lines; spread vertically so labels never overlap."""
    lo, hi = ax.get_ylim()
    gap = (hi - lo) * min_gap_frac
    items = sorted(items, key=lambda i: i[1])
    placed = []
    for x, y, text in items:
        yy = max(y, placed[-1] + gap) if placed else y
        placed.append(yy)
        ax.annotate(text, (x, yy), xytext=(4, 0), textcoords="offset points", color=INK2, fontsize=8, va="center")


def pct(x, d=0):
    return f"{x:+.{d}%}"


COLLECTED = df("SELECT max(collected_on) FROM collected").iloc[0, 0]
LAST = pd.Timestamp(df("SELECT max(period) FROM mart_monthly_prices").iloc[0, 0])
monthly = df("SELECT * FROM mart_monthly_prices")
monthly["period"] = pd.to_datetime(monthly.period)
recon = pd.read_csv(M / "reconciliation_summary.csv")
detail = pd.read_csv(M / "reconciliation_detail.csv", parse_dates=["period"])
nowcast = pd.read_csv(M / "nowcast.csv", parse_dates=["period"])
backtest = pd.read_csv(M / "nowcast_backtest.csv")
disc = pd.read_csv(M / "discrepancy_log.csv")
mats = df("SELECT * FROM materials")

# ------------------------------------------------------------------ key numbers
ga = df("""SELECT sum(quantity_kg) FILTER (WHERE period BETWEEN '2023-01-01' AND '2023-06-01') h1,
                  sum(quantity_kg) FILTER (WHERE period BETWEEN '2023-08-01' AND '2024-01-01') after
           FROM mart_origin_monthly WHERE material_id='GA'""").iloc[0]
GA_DROP = ga.after / ga.h1 - 1
lvl = df(f"""SELECT material_id,
     sum(eu_import_value_eur) FILTER (WHERE year(period)=2021) / sum(eu_import_kg) FILTER (WHERE year(period)=2021) AS b21,
     sum(eu_import_value_eur) FILTER (WHERE period > DATE '{LAST:%Y-%m-%d}' - INTERVAL 12 MONTH)
       / sum(eu_import_kg) FILTER (WHERE period > DATE '{LAST:%Y-%m-%d}' - INTERVAL 12 MONTH) AS l12
     FROM mart_monthly_prices GROUP BY 1""").set_index("material_id")
lvl["ratio"] = lvl.l12 / lvl.b21
NE_EXCL = df("""SELECT sum(quantity_kg) FILTER (WHERE quantity_kg>0 AND (uv<lo OR uv>hi)) / sum(quantity_kg) s
               FROM partner_rows WHERE material_id='NE' AND flow='import'""").iloc[0, 0]
bt_cu = backtest[(backtest.material_id == "CU")].pivot_table(index="horizon", columns="method", values="mape")
QS = pd.read_csv(ROOT / "data" / "clean" / "quality_summary.csv")


# ------------------------------------------------------------------ charts
def chart_codes():
    """Nomenclature changes: aluminium (2023) and wafers (2026), kg by CN8 code."""
    d = df("""SELECT period, material_id, product_code, sum(quantity_kg)/1e6 kt FROM stg_comext_cn8
              WHERE partner='EXT_EU27_2020' AND flow='import' AND material_id IN ('AL','WAFER')
                AND ((material_id='AL' AND period BETWEEN '2022-07-01' AND '2023-06-01')
                  OR (material_id='WAFER' AND period BETWEEN '2025-07-01' AND '2026-08-01'))
              GROUP BY ALL ORDER BY period""")
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.5))
    for ax, (mat, title, unit, scale) in zip(axes, [("AL", "Aluminium: CN 76011000 split on 2023-01-01", "kt", 1),
                                                    ("WAFER", "Doped wafers: CN 38180010 split on 2026-01-01", "t", 1000)]):
        p = d[d.material_id == mat].pivot_table(index="period", columns="product_code", values="kt", aggfunc="sum").fillna(0) * scale
        bottom = np.zeros(len(p))
        for i, c in enumerate(p.columns):
            ax.bar(p.index, p[c], width=24, bottom=bottom, color=[GREY, BLUE, ORANGE][i], label=c, edgecolor=CARD, linewidth=1)
            bottom += p[c].values
        ax.set_title(title, fontsize=9)
        ax.set_ylabel(f"EU imports, {unit}")
        ax.legend(fontsize=7, loc="upper center", ncol=3, bbox_to_anchor=(0.5, -0.16))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        ax.tick_params(axis="x", labelsize=7)
        ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return save(fig, "codes")


def chart_quality():
    ex = df("""SELECT material_id, sum(quantity_kg) FILTER (WHERE quantity_kg>0 AND (uv<lo OR uv>hi)) / sum(quantity_kg) s
               FROM partner_rows WHERE flow='import' GROUP BY 1 ORDER BY 2""")
    ex = ex[ex.s > 0.001]
    fig, ax = plt.subplots(figsize=(3.6, 3.0))
    ax.barh(ex.material_id, ex.s, color=[RED if v > 0.2 else BLUE for v in ex.s], height=0.6)
    for y, v in enumerate(ex.s):
        ax.text(v + 0.01, y, f"{v:.0%}", va="center", fontsize=8, color=INK2)
    ax.xaxis.set_major_formatter(PercentFormatter(1, 0))
    ax.set_title("Share of EU import kg excluded (QC14)", fontsize=9)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, 1)
    fig.tight_layout()
    a = save(fig, "quality_excluded")
    ne = monthly[monthly.material_id == "NE"].set_index("period")
    fig, ax = plt.subplots(figsize=(4.4, 3.0))
    ax.plot(ne.index, ne.eu_import_uv_raw_eur_kg, color=GREY, lw=1.5, label="As published (all flows)")
    ax.plot(ne.index, ne.eu_import_uv_eur_kg, color=BLUE, lw=1.8, label="Validated (QC14 applied)")
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_ylabel("EUR/kg (log scale)")
    ax.set_title("Neon, krypton and xenon: EU import unit value", fontsize=9)
    ax.legend(fontsize=7, loc="upper left")
    fig.tight_layout()
    return a, save(fig, "quality_neon")


def chart_gaps():
    keep = ["R01", "R02", "R03", "R07", "R08", "R09", "R10", "R11", "R12", "R13", "R16", "R20"]
    r = recon.set_index("pair_id").loc[keep[::-1]]
    labels = {"R01": "Copper: EU CIF vs LME", "R02": "Tin: EU CIF vs LME", "R03": "Aluminium: EU CIF vs LME",
              "R07": "Aluminium: US spot vs LME", "R08": "Gallium: EU vs US import UV", "R09": "Germanium: EU UV vs metal price",
              "R10": "Indium: EU UV vs Rotterdam", "R11": "Silicon metal: EU vs US market", "R12": "Silicon metal: EU CIF vs China FOB",
              "R13": "Ammonia: EU CIF vs US Gulf FOB", "R16": "Polysilicon: DE export vs CN import", "R20": "Rare gases: published vs validated"}
    fig, ax = plt.subplots(figsize=(4.8, 3.3))
    for y, (pid, row) in enumerate(r.iterrows()):
        ax.add_patch(plt.Rectangle((row.expected_low, y - 0.32), row.expected_high - row.expected_low, 0.64, color=GRID, lw=0))
        ax.plot([row.min_gap, row.max_gap], [y, y], color=GREY, lw=1.5, solid_capstyle="round")
        out = row.latest_status == "ALERT"
        ax.plot(row.median_gap, y, "o", ms=6, color=BLUE, mec=CARD, mew=1.5)
        ax.plot(row.latest_gap, y, "D", ms=5, color=RED if out else INK2, mec=CARD, mew=1)
    ax.set_yticks(range(len(r)))
    ax.set_yticklabels([labels[p] for p in r.index], fontsize=7.5)
    ax.axvline(0, color=INK2, lw=0.8)
    ax.set_xlim(-0.8, 0.8)
    ax.xaxis.set_major_formatter(PercentFormatter(1, 0))
    ax.grid(axis="y", visible=False)
    ax.set_title("Gap A/B - 1: band (grey), range, median (dot), latest (diamond, red = alert)", fontsize=8)
    fig.tight_layout()
    a = save(fig, "gaps")
    d = detail[detail.pair_id == "R03"]
    fig, ax = plt.subplots(figsize=(4.8, 1.75))
    ax.axhspan(d.expected_low.iloc[0], d.expected_high.iloc[0], color=GRID, lw=0)
    ax.plot(d.period, d.gap, color=BLUE, lw=1.6)
    ax.scatter(d[d.status == "ALERT"].period, d[d.status == "ALERT"].gap, color=RED, s=10, zorder=3)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.yaxis.set_major_formatter(PercentFormatter(1, 0))
    ax.set_title("Aluminium: EU CIF unit value vs LME, monthly", fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    return a, save(fig, "gap_al")


def chart_trends():
    groups = [("Critical minerals", ["GE", "GA", "IN"]), ("Base metals", ["SN", "CU", "AL"]),
              ("Silicon chain", ["SI_MET", "POLYSI", "WAFER"]), ("Gases and chemicals", ["NH3", "HF", "HE"])]
    names = mats.set_index("material_id").material.str.replace(r" \(.*\)", "", regex=True).to_dict()
    names.update({"NH3": "Ammonia", "HF": "Hydrofluoric acid", "SI_MET": "Silicon metal"})
    fig, axes = plt.subplots(1, 4, figsize=(11.6, 2.45), sharey=False)
    for ax, (title, ids) in zip(axes, groups):
        ends = []
        for i, mid in enumerate(ids):
            s = monthly[monthly.material_id == mid].set_index("period").eu_import_uv3_eur_kg
            base = s[s.index.year == 2021].mean()
            idx = (s / base * 100)[s.index >= "2021-01-01"]
            ax.plot(idx.index, idx, color=CAT[i], lw=1.8)
            ends.append((idx.index[-1], idx.iloc[-1], f"{names[mid]} {idx.iloc[-1]:.0f}"))
        ax.axhline(100, color=INK2, lw=0.8, ls="--")
        ax.set_title(title, fontsize=9)
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%y"))
        ax.set_xlim(pd.Timestamp("2021-01-01"), LAST + pd.DateOffset(months=24))
        end_labels(ax, ends)
    axes[0].set_ylabel("Index, 2021 = 100 (3-month weighted)")
    fig.tight_layout()
    a = save(fig, "trends")
    ppi = df("SELECT period, series_id, price_native v FROM observations WHERE source='BLS' AND period >= DATE '2021-01-01'")
    ppi["period"] = pd.to_datetime(ppi.period)
    lab = {"PPI_NONFERROUS": "Non-ferrous metals", "PPI_GASES": "Industrial gases", "PPI_INORGANIC": "Inorganic chemicals", "PPI_SEMI": "Semiconductors"}
    fig, ax = plt.subplots(figsize=(4.6, 2.05))
    ends = []
    for i, sid in enumerate(["PPI_NONFERROUS", "PPI_GASES", "PPI_INORGANIC", "PPI_SEMI"]):
        s = ppi[ppi.series_id == sid].set_index("period").v.sort_index()
        idx = s / s[s.index.year == 2021].mean() * 100
        ax.plot(idx.index, idx, color=CAT[i], lw=1.8)
        ends.append((idx.index[-1], idx.iloc[-1], f"{lab[sid]} {idx.iloc[-1]:.0f}"))
    end_labels(ax, ends, 0.09)
    ax.axhline(100, color=INK2, lw=0.8, ls="--")
    ax.set_xlim(pd.Timestamp("2021-01-01"), LAST + pd.DateOffset(months=26))
    ax.set_title("US producer price indexes, 2021 = 100", fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    return a, save(fig, "ppi")


def chart_events():
    ev = lambda ax, d, t, y=0.97: (ax.axvline(pd.Timestamp(d), color=INK2, ls="--", lw=1),
                                   ax.text(pd.Timestamp(d), ax.get_ylim()[1] * y, " " + t, fontsize=7, color=INK2, va="top"))
    o = df("""SELECT date_trunc('quarter', period) q, material_id, origin='CN' AS cn, sum(quantity_kg)/1000 t,
                     sum(value_eur) v FROM mart_origin_monthly WHERE material_id IN ('GA','GE') AND period >= DATE '2021-01-01' GROUP BY ALL""")
    o["q"] = pd.to_datetime(o.q)
    g = o[o.material_id == "GA"].pivot_table(index="q", columns="cn", values="t", aggfunc="sum").fillna(0)
    fig, ax = plt.subplots(figsize=(3.7, 2.6))
    ax.bar(g.index, g[True], width=70, color=BLUE, label="from China", edgecolor=CARD)
    ax.bar(g.index, g[False], width=70, bottom=g[True], color=GREY, label="other origins", edgecolor=CARD)
    ax.set_ylabel("tonnes per quarter")
    ax.set_title("Gallium: EU imports by origin", fontsize=9)
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(axis="x", visible=False)
    ev(ax, "2023-08-01", "licensing")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    a = save(fig, "ev_ga")
    s = monthly[(monthly.material_id == "GE") & (monthly.period >= "2021-01-01")].set_index("period").eu_import_uv3_eur_kg
    fig, ax = plt.subplots(figsize=(3.7, 2.6))
    ax.plot(s.index, s, color=BLUE, lw=1.8)
    ax.set_ylabel("EUR/kg, 3-month weighted")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_title("Germanium: EU import unit value", fontsize=9)
    ax.set_ylim(0, s.max() * 1.15)
    ev(ax, "2023-08-01", "licensing")
    ev(ax, "2024-12-03", "US ban", 0.85)
    ev(ax, "2025-11-09", "ban suspended", 0.73)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    b = save(fig, "ev_ge")
    c = df("SELECT year(period) y, price_usd_kg v FROM observations WHERE series_id='COMTRADE_156_export_0_280429' ORDER BY 1")
    ua = df("""SELECT year(period) y, sum(quantity_kg) FILTER (WHERE origin IN ('UA','RU'))/1000 t FROM mart_origin_monthly
               WHERE material_id='NE' AND year(period) BETWEEN 2018 AND 2025 GROUP BY 1 ORDER BY 1""")
    fig, axes = plt.subplots(2, 1, figsize=(3.7, 2.9), sharex=True)
    axes[0].bar(c.y, c.v, color=[RED if y == 2022 else BLUE for y in c.y], width=0.6)
    axes[0].set_title("Rare gases: China export unit value, USD/kg", fontsize=8.5)
    axes[0].grid(axis="x", visible=False)
    axes[1].bar(ua.y, ua.t, color=GREY, width=0.6)
    axes[1].set_title("EU rare-gas imports from Ukraine + Russia, t", fontsize=8.5)
    axes[1].grid(axis="x", visible=False)
    fig.tight_layout()
    cc = save(fig, "ev_ne")
    p = df("""SELECT year(period) y, origin, sum(value_eur)/sum(quantity_kg) uv FROM mart_origin_monthly
              WHERE material_id='POLYSI' AND origin IN ('US','CN') AND year(period) >= 2019 GROUP BY ALL
              HAVING sum(quantity_kg) > 50000 ORDER BY 1""")
    allo = df("""SELECT year(period) y, sum(eu_import_value_eur)/sum(eu_import_kg) uv FROM mart_monthly_prices
                 WHERE material_id='POLYSI' AND year(period) >= 2019 GROUP BY 1 ORDER BY 1""")
    fig, ax = plt.subplots(figsize=(3.7, 2.6))
    for i, (org, lab) in enumerate([("US", "from the US"), ("CN", "from China")]):
        q = p[p.origin == org]
        ax.plot(q.y, q.uv, color=CAT[i], marker="o", ms=4)
        end_label(ax, q.y.iloc[-1], q.uv.iloc[-1], lab, CAT[i])
    ax.plot(allo.y, allo.uv, color=INK2, ls="--", lw=1.4)
    end_label(ax, allo.y.iloc[-1], allo.uv.iloc[-1], "all origins", INK2)
    ax.set_xlim(2018.7, 2027.6)
    ax.set_ylabel("EUR/kg")
    ax.set_title("Polysilicon: EU import unit value by origin", fontsize=9)
    fig.tight_layout()
    return a, b, cc, save(fig, "ev_poly")


def chart_nowcast():
    s = monthly[(monthly.material_id == "CU") & (monthly.period >= LAST - pd.DateOffset(months=30))].set_index("period")
    n = nowcast[(nowcast.material_id == "CU") & (nowcast.selected == 1)].sort_values("period")
    fig, ax = plt.subplots(figsize=(4.4, 2.8))
    ax.plot(s.index, s.eu_import_uv_eur_kg, color=BLUE, label="EU import unit value (validated)")
    ax.plot(s.index, s.wb_price_eur_kg, color=GREY, lw=1.4, label="LME (World Bank), EUR/kg")
    x = [s.index[-1]] + list(n.period)
    ax.plot(x, [s.eu_import_uv_eur_kg.iloc[-1]] + list(n.nowcast_eur_kg), color=RED, marker="o", ms=4, label="Nowcast")
    ax.fill_between(n.period, n.lo80_eur_kg, n.hi80_eur_kg, color=RED, alpha=0.12, lw=0, label="80% interval")
    ax.set_title("Copper: two missing months nowcast from the LME price", fontsize=9)
    ax.legend(fontsize=7, loc="upper left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    fig.tight_layout()
    a = save(fig, "nc_cu")
    fig, ax = plt.subplots(figsize=(3.6, 2.8))
    w = 0.26
    for i, m in enumerate(["naive", "ets", "signal"]):
        ax.bar(bt_cu.index + (i - 1) * w, bt_cu[m], width=w, color=[GREY, ORANGE, BLUE][i], label=m, edgecolor=CARD)
    ax.yaxis.set_major_formatter(PercentFormatter(1, 0))
    ax.set_xlabel("months ahead")
    ax.set_title("Copper back-test: mean abs. error", fontsize=9)
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return a, save(fig, "nc_bt")


def chart_survey():
    d = pd.read_csv(ROOT / "survey" / "simulated_processed.csv")
    r = pd.read_csv(ROOT / "survey" / "simulated_results.csv").iloc[0]
    fig, ax = plt.subplots(figsize=(4.6, 2.6))
    rng = np.random.default_rng(1)
    for i, role in enumerate(["buyer", "seller"]):
        q = d[d.role == role]
        ok = q.status == "ok"
        y = i + rng.uniform(-0.15, 0.15, len(q))
        ax.scatter(q[ok].eur_kg, y[ok.values], s=18, color=CAT[i], edgecolor=CARD, lw=0.8, label=f"{role}s")
        ax.scatter(q[~ok].eur_kg.clip(upper=8), y[(~ok).values], s=26, marker="x", color=RED)
    ax.axvline(r.weighted_mean, color=INK, lw=1.2)
    ax.text(r.weighted_mean, 1.45, f" weighted mean {r.weighted_mean:.2f}", fontsize=7, color=INK)
    ax.axvline(r.comext_q3_2026_eur_kg, color=INK2, lw=1, ls="--")
    ax.text(r.comext_q3_2026_eur_kg, -0.48, f" Comext Q3 {r.comext_q3_2026_eur_kg:.2f}", fontsize=7, color=INK2)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["buyers", "sellers"])
    ax.set_ylim(-0.6, 1.6)
    ax.set_xlim(2.5, 8.2)
    ax.set_xlabel("EUR/kg after standardisation (x = rejected, shown capped at 8)")
    ax.set_title("SIMULATED answers, AHF delivered EU, Q3-2026", fontsize=9)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    return save(fig, "survey"), r


# ------------------------------------------------------------------ html
CSS = """
@page { size: 13.333in 7.5in; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; font-family: 'Segoe UI', sans-serif; color: #0B0B0B; background: #F4F4F2; }
.page { width: 13.333in; height: 7.5in; padding: 0.42in 0.5in 0.3in; position: relative; page-break-after: always;
        background: #F4F4F2; overflow: hidden; }
h1 { font-size: 23px; margin: 0 1.6in 4px 0; line-height: 1.2; }
.sub { color: #52514E; font-size: 12.5px; margin: 0 1.5in 12px 0; line-height: 1.35; }
.tag { position: absolute; top: 0.45in; right: 0.5in; font-size: 10px; font-weight: 700; letter-spacing: .06em; color: #52514E; }
.tag.sim { color: #D03B3B; }
.foot { position: absolute; bottom: 0.16in; left: 0.5in; right: 0.5in; font-size: 8.5px; color: #898781; }
.pn { position: absolute; bottom: 0.16in; right: 0.5in; font-size: 8.5px; color: #898781; }
.row { display: flex; gap: 12px; }
.card { background: #FCFCFB; border: 1px solid #E1E0D9; border-radius: 8px; padding: 10px 13px; }
.card h3 { font-size: 10.5px; letter-spacing: .04em; text-transform: uppercase; color: #52514E; margin: 0 0 6px; }
.card p, .card li { font-size: 11.5px; line-height: 1.4; margin: 0 0 5px; color: #0B0B0B; }
.card ul { margin: 0; padding-left: 16px; }
.kpi .v { font-size: 34px; font-weight: 700; line-height: 1.05; }
.kpi .l { font-size: 11.5px; color: #52514E; line-height: 1.35; margin-top: 4px; }
.kpi .t { font-size: 9.5px; font-weight: 700; color: #52514E; letter-spacing: .04em; }
img { display: block; max-width: 100%; }
table { border-collapse: collapse; width: 100%; font-size: 10.5px; }
th { text-align: left; color: #52514E; font-weight: 600; border-bottom: 1px solid #52514E; padding: 3px 5px; }
td { padding: 3px 5px; border-bottom: 1px solid #E1E0D9; vertical-align: top; }
.num { text-align: right; white-space: nowrap; }
.alert { color: #D03B3B; font-weight: 600; }
.ok { color: #52514E; }
.b { font-weight: 700; }
.mut { color: #52514E; }
.blue { color: #2A78D6; font-weight: 700; }
.stage { border-top: 3px solid #2A78D6; }
.pill { display: inline-block; padding: 1px 6px; border-radius: 9px; font-size: 9.5px; margin: 1px 2px 1px 0; background: #CDE2FB; }
.pill.g { background: #F0EFEC; color: #52514E; }
.cov td { text-align: center; }
.cov td:first-child, .cov td:nth-child(2) { text-align: left; }
.y { background: #CDE2FB; } .p { background: #F0EFEC; color: #52514E; } .n { color: #B4B2AD; }
.tight td, .tight th { padding: 1.5px 5px; font-size: 10px; }
code { font-family: Consolas, monospace; font-size: 10.5px; background: #F0EFEC; padding: 0 3px; border-radius: 3px; }
"""


class Report:
    def __init__(self):
        self.pages = []

    def add(self, title, sub, body, tag="PUBLIC DATA", foot=""):
        n = len(self.pages)
        tag_html = f'<div class="tag{" sim" if tag == "SIMULATED" else ""}">{tag}</div>' if tag else ""
        foot_txt = (foot + " · " if foot else "") + f"Collected {COLLECTED}. " + FOOT
        self.pages.append(f'<section class="page">{tag_html}<h1>{title}</h1><div class="sub">{sub}</div>{body}'
                          f'<div class="foot">{foot_txt}</div><div class="pn">{n}</div></section>')

    def html(self):
        return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>TechInsights materials pricing case study</title>"
                f"<style>{CSS}</style></head><body>{''.join(self.pages)}</body></html>")


def t(rows, head, cls=""):
    h = "".join(f"<th class='{c}'>{x}</th>" for x, c in head)
    b = "".join("<tr>" + "".join(f"<td class='{c}'>{v}</td>" for v, (_, c) in zip(r, head)) + "</tr>" for r in rows)
    return f"<table class='{cls}'><tr>{h}</tr>{b}</table>"


def build():
    R = Report()
    ge_x = lvl.loc["GE", "ratio"]
    nb = bt_cu.loc[2]
    # ---------------------------------------------------------- 0 overview
    kpis = [("PUBLIC · PAGE 7", f"{GA_DROP:.0%}", "EU gallium imports in the six months after China's export licensing (Aug 2023-Jan 2024) vs the first half of 2023"),
            ("PUBLIC · PAGE 6", f"×{ge_x:.1f}", f"EU germanium import unit value, last 12 months vs 2021; polysilicon fell {lvl.loc['POLYSI', 'ratio'] - 1:.0%} over the same period"),
            ("PUBLIC · PAGE 4", f"{NE_EXCL:.0%}", "of the kilograms declared as neon, krypton and xenon are implausible (about EUR 1-2/kg) and are excluded"),
            ("PUBLIC · PAGE 8", f"{nb['signal']:.1%}", f"two-month nowcast error for copper using the LME price, vs {nb['naive']:.1%} for 'last value' (24-month back-test)")]
    k = "".join(f'<div class="card kpi" style="flex:1"><div class="t">{a}</div><div class="v">{b}</div><div class="l">{c}</div></div>' for a, b, c in kpis)
    qs = [("TechInsights", "What does TechInsights cover, and where do material prices fit?"),
          ("Coverage", "Which fab materials can public data track, from feedstock to wafers?"),
          ("Standards & quality", "Can sources with different units, currencies, codes and delivery terms be put on one standard and checked?"),
          ("Discrepancies", "When two sources disagree, why, and what prevents it next time?"),
          ("Trends & nowcast", "What moved prices since 2021, and can the unpublished months be estimated honestly?")]
    ql = "".join(f'<li><span class="blue">{i + 1} · {a}</span>&nbsp; {b}</li>' for i, (a, b) in enumerate(qs))
    body = f"""<div class="row" style="margin-bottom:12px">{k}</div>
    <div class="row"><div class="card" style="flex:1.1"><h3>Questions</h3><ul style="list-style:none;padding:0">{ql}</ul>
      <p style="margin-top:8px"><b>Recommendations.</b> Publish a <i>validated</i> unit value next to the raw one, with a plausible
      price range per material; track critical minerals <i>by origin</i>, because the origin mix moves the average more than prices do;
      nowcast metals from exchange prices and show intervals, not points, for thin markets; fill grade-specific gaps
      (electronic-grade gases, photoresists, NF<sub>3</sub>) with a two-sided, anchor-free survey.</p></div>
    <div class="card" style="flex:1"><h3>Data &amp; methods</h3>
      <p><b>PUBLIC</b> Eurostat Comext (EU trade by CN8 code, monthly), UN Comtrade (HS6, annual), USGS Mineral Commodity Summaries 2025-2026,
      World Bank Pink Sheet, IMF and BLS series via FRED, ECB exchange rates; TechInsights' public website only.</p>
      <p><b>SIMULATED</b> survey answers (page 9 only), labelled as such.</p>
      <p><b>Pipeline</b> Python + DuckDB SQL, raw &rarr; clean &rarr; marts, one command: <code>python -m pipeline run</code>.
      14 quality checks, 22 reconciled source pairs, 14 discrepancy cards, nowcast back-tested on 24 months.</p>
      <p><b>Excel</b> Power Query tracker with dashboard, reconciliation, FORECAST.ETS nowcast and checks.</p></div></div>
    <div class="card" style="margin-top:12px"><h3>How to read this report</h3><p><b>Titles</b> state the conclusion. <b>Tags</b> PUBLIC DATA / SIMULATED show where the data comes from.
      <b>Unit value</b> = customs value / kg: a price <i>indicator</i> that mixes grades, not a transaction price. <b>Dashed lines</b> mark events, bands or intervals.
      <b>Red</b> marks alerts and discrepancies. Code, data and the Excel tracker are in the repository.</p></div>"""
    R.add("TechInsights: tracking semiconductor materials prices from public sources, reconciled, validated and documented",
          "A reproducible pipeline and an expert Excel tracker for 15 fab materials, from raw feedstock to finished inputs, "
          "with cross-source reconciliation, root-cause analysis and nowcasts.", body, tag="OVERVIEW",
          foot="Sources: data/SOURCES.md")

    # ---------------------------------------------------------- 1 TechInsights
    facts = [("1989", "Founded in Ottawa as Semiconductor Insights"), ("2016-17", "Combined with Chipworks"),
             ("2019-21", "Acquisitions add market and manufacturing intelligence, pricing and supply chain"),
             ("Materials", "TECHCET is part of TechInsights: Semiconductor Materials Intelligence"),
             ("Nov 2026", "'Semiconductor Sustainability Outlook 2027' and 'Compute Outlook 2027' published")]
    tl = "".join(f'<tr><td class="b" style="width:80px">{a}</td><td>{b}</td></tr>' for a, b in facts)
    nums = [("650+", "customers"), ("100K+", "chip teardowns"), ("1.7M+", "images"), ("50K+", "analyses"), ("35+", "years")]
    nh = "".join(f'<div class="card kpi" style="flex:1"><div class="v" style="font-size:26px">{a}</div><div class="l">{b}</div></div>' for a, b in nums)
    segs = ["Gases", "ALD/CVD precursors", "Photoresists", "CMP consumables", "Wet chemicals", "Metal plating", "Sputtering targets",
            "Equipment consumables", "Critical raw materials"]
    body = f"""<div class="row" style="margin-bottom:12px">{nh}</div>
    <div class="row"><div class="card" style="flex:1"><h3>Company milestones</h3><table>{tl}</table>
       <p class="mut" style="margin-top:8px">Content: teardowns and reverse engineering, competitive benchmarking, patent analysis, market and trend reports;
       free, freemium and premium tiers including <b>component pricing and bills of materials</b>; a Cost Analysis capability that breaks down
       the cost of materials, manufacturing and assembly.</p></div>
    <div class="card" style="flex:1"><h3>Materials segments named on the public site</h3><p>{''.join(f'<span class="pill">{s}</span>' for s in segs)}</p>
       <h3 style="margin-top:12px">Why material prices matter to its clients</h3>
       <ul><li>A chip's cost model needs the input side: wafers, gases, wet chemicals, metals and their <b>price trend</b>.</li>
       <li>Critical minerals (gallium, germanium) are now driven by <b>export licensing</b>, not only by demand: buyers need early, sourced signals.</li>
       <li>Clients compare figures across reports, so <b>one data standard and documented discrepancies</b> are part of the product.</li>
       <li>This study rebuilds that workflow with public data only, to show how I would work on it, not to replicate paid content.</li></ul></div></div>
    <div class="card" style="margin-top:12px"><h3>The role's tasks, and where this study shows them</h3>{t([
        ["Track price trends from raw materials to finished inputs", "15 materials, 4 stages", "pages 2, 6, 7"],
        ["Set data standards; extract, synthesise and validate data from several sources", "standard schema, dictionary, code concordance", "page 3, docs/DATA_STANDARDS.md"],
        ["Monitor data quality; identify discrepancies, find root causes, prevent them", "14 checks, 22 source pairs, 14 cards", "pages 4-5, docs/DISCREPANCY_LOG.md"],
        ["Document for knowledge transfer; pipelines and ETL", "one-command pipeline, runbook", "page 10, docs/RUNBOOK.md"],
        ["Expert Excel and data extrapolation", "Power Query tracker, FORECAST.ETS nowcast, back-test", "page 8, excel/"],
        ["Unbiased survey design (asset)", "two-sided, anchor-free method, SIMULATED example", "page 9, survey/"]],
        [("Task in the job description", "b"), ("What was built", ""), ("Where", "mut")], "tight")}</div>"""
    R.add("TechInsights already covers the chip from teardown to bill of materials; material input prices are the cost-side signal",
          "What the company publishes about itself (techinsights.com, read on 2026-11-12) and why tracking fab-material prices fits its clients' questions.",
          body, foot="Sources: techinsights.com (About, Cost Analysis, Semiconductor Materials Intelligence, home page), himalayas.app job page; no paywalled content used")

    # ---------------------------------------------------------- 2 materials map
    cov = df("SELECT * FROM mart_coverage ORDER BY stage_order, material_id")
    stages = []
    for st, g in cov.groupby("stage_order"):
        items = "".join(f'<span class="pill">{r.material}</span>' for r in g.itertuples())
        stages.append(f'<div class="card stage" style="flex:1"><h3>{g.chain_stage.iloc[0]}</h3><p>{items}</p></div>')
    stages.append('<div class="card stage" style="flex:1;border-top-color:#B4B2AD"><h3>No public price source</h3><p>' +
                  "".join(f'<span class="pill g">{x}</span>' for x in ["Photoresists", "NF<sub>3</sub>", "ALD/CVD precursors", "CMP slurries"]) +
                  '</p><p class="mut" style="font-size:10px">Hidden in broad customs codes: only a survey can price them.</p></div>')
    cls = lambda v: "y" if v.startswith("yes") else ("p" if v not in ("no", "none") else "n")
    rows = [[r.material_id, r.material, f"<span class='{cls(r.comext_monthly)}'>&nbsp;monthly&nbsp;</span>",
             f"<span class='{cls(r.comtrade_annual)}'>&nbsp;{r.comtrade_annual.replace('yes ', '')}&nbsp;</span>",
             f"<span class='{cls(r.usgs_annual)}'>&nbsp;{r.usgs_annual}&nbsp;</span>",
             f"<span class='{cls(r.exchange_benchmark_monthly)}'>&nbsp;{r.exchange_benchmark_monthly}&nbsp;</span>",
             r.price_index.replace("PPI_", "PPI ").lower() if r.price_index != "none" else "<span class='n'>none</span>"] for r in cov.itertuples()]
    n_second_monthly = int((cov.exchange_benchmark_monthly == "yes").sum())
    body = f"""<div class="row" style="margin-bottom:12px">{''.join(stages)}</div>
    <div class="card"><h3>Source coverage (blue = usable price comparison, grey = partial)</h3>{t(rows, [("ID", "b"), ("Material", ""), ("Comext EU trade", ""), ("UN Comtrade", ""), ("USGS reference", ""), ("Exchange price", ""), ("US price index", "")], "cov tight")}</div>"""
    R.add(f"All 15 fab materials have a monthly EU trade series, but only {n_second_monthly} have a second monthly price to check it against",
          "The tracked range runs from raw feedstock to doped wafers. Coverage decides how far each series can be validated: everything else relies on annual references and checks.",
          body, foot="Sources: Eurostat Comext DS-045409, UN Comtrade, USGS MCS 2025-2026, World Bank, IMF/BLS via FRED")

    # ---------------------------------------------------------- 3 standard
    he = df("""SELECT * FROM stg_comext WHERE material_id='HE' AND partner='EXT_EU27_2020' AND flow='import'
               AND product_code='28042910' ORDER BY period DESC LIMIT 1""").iloc[0]
    fx = df(f"SELECT usd_per_eur FROM fx WHERE period = DATE '{pd.Timestamp(he.period):%Y-%m-%d}'").iloc[0, 0]
    cu = df("SELECT period, value FROM stg_worldbank WHERE series_id='WB_COPPER' ORDER BY period DESC LIMIT 1").iloc[0]
    cufx = df(f"SELECT usd_per_eur FROM fx WHERE period = DATE '{pd.Timestamp(cu.period):%Y-%m-%d}'")
    cufx = cufx.iloc[0, 0] if len(cufx) else fx
    si = df("SELECT value_native FROM stg_usgs WHERE series_id='USGS_SI_METAL' AND edition='MCS2026' AND year=2025").iloc[0, 0]
    am = df("SELECT value_native FROM stg_usgs WHERE series_id='USGS_AMMONIA' AND edition='MCS2026' AND year=2025").iloc[0, 0]
    fxa = df("SELECT usd_per_eur FROM fx_annual WHERE year=2025").iloc[0, 0]
    rows = [["Comext, helium (CN 28042910)", f"{he.value_eur:,.0f} EUR; {he.quantity_kg / 100:,.0f} x 100 kg; {he.quantity_supp:,.0f} m³; CIF", "value / (100 kg × 100)", f"{he.value_eur / he.quantity_kg:,.2f}", "kg kept; m³ used only as a check (QC08)"],
            ["World Bank, copper", f"{cu.value:,.0f} USD per metric ton; LME cash", f"/ 1,000 / {cufx:.4f} USD per EUR", f"{cu.value / 1000 / cufx:,.2f}", "monthly ECB average rate"],
            ["USGS, silicon metal 2025", f"{si:,.0f} US cents per pound", "× 0.01 / 0.4536 / annual FX", f"{si * 0.0220462 / fxa:,.2f}", "US market: never mixed with EU border values"],
            ["USGS, ammonia 2025", f"{am:,.0f} USD per short ton, FOB Gulf", "/ 907.18 / annual FX", f"{am * 0.00110231 / fxa:,.2f}", "FOB vs EU CIF: compared with a band"]]
    tb = t(rows, [("Source (as published)", "b"), ("Raw record", ""), ("Conversion", "mut"), ("EUR/kg", "num b"), ("Convention", "mut")])
    body = f"""<div class="row"><div class="card" style="flex:1.25"><h3>Before and after standardisation</h3>{tb}
      <p class="mut" style="margin-top:8px">Every source lands in one schema: <code>period, material_id, source, series_id, flow, reporter, partner, valuation,
      product_code, value_native, currency, quantity_kg, quantity_supp, price_eur_kg, price_usd_kg, collected_on</code>.
      Imports are valued <b>CIF</b> (cost, insurance, freight to the EU border), exports <b>FOB</b> (free on board); the valuation is a column, never implicit.</p></div>
      <div class="card" style="flex:1"><h3>Conventions (docs/DATA_STANDARDS.md)</h3><ul>
      <li><b>Unit</b>: EUR/kg and USD/kg for every price; USGS units (cents/lb, short ton, metric ton unit) converted with documented factors.</li>
      <li><b>Currency</b>: ECB monthly average; annual sources use the yearly mean.</li>
      <li><b>Territory</b>: EU27_2020 for the whole history (the 'EU' total includes the UK until January 2020).</li>
      <li><b>Codes</b>: a concordance table maps every CN8 code to a material with validity dates, so split codes are summed, never double counted.</li>
      <li><b>Unit value is not a price</b>: it mixes grades; validated by checks and compared with references.</li></ul></div></div>
    <div class="card" style="margin-top:12px"><h3>Two real nomenclature changes handled by the concordance</h3><img src="{chart_codes()}" style="height:2.15in"></div>"""
    R.add("One standard turns units, currencies, delivery terms and customs-code changes into comparable EUR per kg",
          "Four raw records from four publishers, standardised by the pipeline; two customs-code splits that would break a naive time series.",
          body, foot="Sources: Eurostat Comext, World Bank Pink Sheet (CC BY 4.0), USGS MCS 2026, ECB")

    # ---------------------------------------------------------- 4 quality
    qa, qn = chart_quality()
    what = {"QC01": "Missing month", "QC02": "Value without quantity", "QC03": "Robust outlier (median/MAD, > 3.5 z and 25%)",
            "QC04": "Thin trade month", "QC05": "Customs-code change", "QC08": "kg vs m³ inconsistent (gases)",
            "QC09": "Confidential partner > 10%", "QC11": "Freshness vs normal lag", "QC13": "Comtrade quantity estimated",
            "QC14": "Implausible partner flow, excluded"}
    rows = [[r.check_id, what.get(r.check_id, r.check_name), r.severity, f"{r.rows_flagged:,}", r.materials_affected] for r in QS.itertuples()]
    body = f"""<div class="row"><div class="card" style="flex:1.05"><h3>14 checks, every refresh (sql/03_checks.sql)</h3>
      {t(rows, [("Check", "b"), ("Rule", ""), ("Severity", "mut"), ("Rows", "num"), ("Materials", "num")])}
      <p class="mut" style="margin-top:6px">Also run with zero findings: codes outside validity (QC06), duplicates (QC07), withheld USGS values (QC10), missing FX (QC12).</p></div>
      <div class="card" style="flex:0.85"><img src="{qa}"></div><div class="card" style="flex:1.1"><img src="{qn}">
      <p class="mut">Hundreds of tonnes a year are declared under CN 28042990 at about EUR 1-2/kg, a value impossible for neon, krypton or xenon.
      The published average is pulled down by them; the validated series keeps only plausible flows.</p></div></div>"""
    R.add(f"Quality checks catch what averages hide: {NE_EXCL:.0%} of the 'rare gas' kilograms were implausible declarations",
          "Completeness, units, outliers, nomenclature, confidentiality and freshness are tested automatically; implausible partner flows are excluded "
          "from the validated series and listed for review (docs/QUALITY_REPORT.md).",
          body, foot="Sources: Eurostat Comext DS-045409, USGS, UN Comtrade; rules in sql/03_checks.sql")

    # ---------------------------------------------------------- 5 discrepancies
    ga_, gal = chart_gaps()
    pick = disc.set_index("discrepancy_id").loc[["D01", "D02", "D03", "D06", "D08", "D11"]]
    short = {"D01": ("EU border value is CIF (freight, insurance, regional premium); LME is a warehouse price.", "Expected band per pair; alert only outside it."),
             "D02": ("US prices include US trade measures (Section 232 aluminium tariff, duties on silicon metal).", "Market and valuation are mandatory schema fields."),
             "D03": ("USGS replaced a high-purity price by an import unit value between editions.", "Definition text stored per edition; a change opens a new series."),
             "D06": ("CN 28046100 mixes US electronic-grade and Chinese solar-grade polysilicon.", "Origin-stratified unit value next to the average."),
             "D08": ("EU records imports by country of origin, China exports by destination.", "Partner definition documented per source."),
             "D11": ("Hundreds of tonnes declared at about EUR 2/kg: misclassified or wrong quantity.", "Plausible price range per material (QC14).")}
    rows = [[i, f"<b>{r.title}</b>", short[i][0], short[i][1], r.status] for i, r in pick.iterrows()]
    body = f"""<div class="row"><div style="flex:1;display:flex;flex-direction:column;gap:10px"><div class="card"><img src="{ga_}"></div>
      <div class="card"><img src="{gal}"></div></div>
      <div style="flex:1.3;display:flex;flex-direction:column;gap:10px"><div class="card">{t(rows, [("ID", "b"), ("Finding", ""), ("Root cause", ""), ("Prevention", "mut"), ("Status", "mut")], "tight")}</div>
      <div class="card"><h3>Method</h3>
      <p>Each pair gets an <b>expected band</b> from its known cause (e.g. CIF value 0-20% above the LME price for aluminium). Inside the band = explained; outside = alert and a card:
      <b>finding &rarr; root cause &rarr; evidence &rarr; correction &rarr; prevention</b>. 14 cards in docs/DISCREPANCY_LOG.md; their evidence is recomputed at each run.
      Two cards stay open on purpose (D07 timing, D09 wafer weights): an unexplained gap is reported, not forced into a story.</p></div></div></div>"""
    R.add("Most gaps between sources have a known cause: valuation, market, definition, product mix or partner definition",
          "22 source pairs compared; the expected band turns 'the numbers differ' into 'the difference is normal' or 'investigate'.",
          body, foot="Sources: Eurostat Comext, World Bank, IMF via FRED, USGS MCS 2025-2026, UN Comtrade; data/marts/reconciliation_summary.csv")

    # ---------------------------------------------------------- 6 trends
    tr, pp = chart_trends()
    body = f"""<div class="card"><img src="{tr}"></div>
    <div class="row" style="margin-top:12px"><div class="card" style="flex:1"><img src="{pp}"></div>
      <div class="card" style="flex:1.6"><h3>Reading</h3><ul>
      <li><b>Critical minerals</b>: germanium ×{lvl.loc['GE', 'ratio']:.1f}, gallium ×{lvl.loc['GA', 'ratio']:.1f}, indium ×{lvl.loc['IN', 'ratio']:.1f} (last 12 months vs 2021, EU import unit values).</li>
      <li><b>Base metals</b> follow the LME: tin {pct(lvl.loc['SN', 'ratio'] - 1)}, copper {pct(lvl.loc['CU', 'ratio'] - 1)}, aluminium {pct(lvl.loc['AL', 'ratio'] - 1)}.</li>
      <li><b>Silicon chain</b>: polysilicon {pct(lvl.loc['POLYSI', 'ratio'] - 1)} after the 2022-23 peak (and a mix shift to Chinese solar grade), wafers {pct(lvl.loc['WAFER', 'ratio'] - 1)}.</li>
      <li><b>Gases and chemicals</b>: helium {pct(lvl.loc['HE', 'ratio'] - 1)} after its 2022-23 tightness; ammonia {pct(lvl.loc['NH3', 'ratio'] - 1)}, still above 2021 after the 2022 energy shock.</li>
      <li>Tungsten is excluded: its unit value tracks ore grade, not price (card D05).</li></ul></div></div>"""
    R.add("Prices diverge along the chain: critical minerals doubled to quintupled since 2021, while polysilicon, wafers and helium fell",
          "Index of the 3-month weighted EU import unit value, 2021 average = 100, validated series. US producer price indexes give the same picture on the US side.",
          body, foot="Sources: Eurostat Comext DS-045409; US BLS PPI via FRED (public domain)")

    # ---------------------------------------------------------- 7 events
    e1, e2, e3, e4 = chart_events()
    body = f"""<div class="row"><div class="card" style="flex:1"><img src="{e1}"></div><div class="card" style="flex:1"><img src="{e2}"></div>
      <div class="card" style="flex:1"><img src="{e3}"></div><div class="card" style="flex:1"><img src="{e4}"></div></div>
    <div class="row" style="margin-top:12px"><div class="card" style="flex:1"><h3>Dated facts (official or primary sources, seeds/events.csv)</h3><ul>
      <li><b>2023-07-03</b> China (MOFCOM/GAC Announcement No. 23) requires export licences for gallium and germanium items, effective <b>2023-08-01</b>.</li>
      <li><b>2024-12-03</b> MOFCOM Announcement No. 46: licences for exports of gallium, germanium and antimony items to the United States in principle not approved.
          <b>2025-11-09</b> Announcement No. 72 suspends that US-specific ban until 2026-11-27; the general licensing regime remains.</li>
      <li><b>2022-02/03</b> Ukraine's two semiconductor-grade neon producers (Cryoin, Ingas) stop production; Reuters estimated their share at 45-54% of chip-grade neon.</li></ul></div>
      <div class="card" style="flex:1"><h3>What the data shows</h3><ul>
      <li>EU gallium imports fell {GA_DROP:.0%} in the six months after licensing; the share from China dropped, then partly recovered as licences were granted.</li>
      <li>Germanium's EU unit value rose in steps after each measure, to ×{ge_x:.1f} its 2021 level.</li>
      <li>China's rare-gas export unit value jumped in 2022 as Ukrainian and Russian supply to the EU nearly disappeared.</li>
      <li>Polysilicon: from 2024 cheap Chinese solar-grade metal enters the EU under the same code as US electronic grade; the all-origin average falls mostly through <b>mix</b>.</li></ul></div></div>"""
    R.add(f"Export licensing cut EU gallium imports by {abs(GA_DROP):.0%} within six months; germanium now costs ×{ge_x:.1f} its 2021 level",
          "Events are dated from official or primary sources and described factually; charts show what EU and Chinese trade statistics recorded around them.",
          body, foot="Sources: Eurostat Comext DS-045409, UN Comtrade (HS 280429), MOFCOM announcements, Reuters via CNN (2022-03-11)")

    # ---------------------------------------------------------- 8 nowcast
    n1, n2 = chart_nowcast()
    sel = nowcast[(nowcast.selected == 1)]
    rows = []
    for mid, g in sel.groupby("material_id"):
        meth = g.method.iloc[0]
        b = backtest[(backtest.material_id == mid) & (backtest.method == meth)].set_index("horizon").mape
        nv = backtest[(backtest.material_id == mid) & (backtest.method == "naive")].set_index("horizon").mape
        h1 = g[g.horizon == 1].iloc[0]
        rows.append([mid, meth, f"{h1.nowcast_eur_kg:,.2f}", f"{h1.lo80_eur_kg:,.2f} - {h1.hi80_eur_kg:,.2f}",
                     f"{b[1]:.1%}", f"{b[2]:.1%}", f"{nv[2]:.1%}", (h1.hi80_eur_kg - h1.lo80_eur_kg) / h1.nowcast_eur_kg])
    rows.sort(key=lambda r: r[-1])
    rows = [r[:-1] for r in rows]
    nm = pd.Timestamp(sel.period.min())
    body = f"""<div class="row"><div class="card" style="flex:1.1"><img src="{n1}"></div><div class="card" style="flex:0.9"><img src="{n2}"></div>
      <div class="card" style="flex:1.25"><h3>Nowcast for {nm:%B %Y}, selected method per material (EUR/kg)</h3>
      {t(rows, [("ID", "b"), ("Method", "mut"), ("Nowcast", "num b"), ("80% interval", "num"), ("Error h1", "num"), ("Error h2", "num"), ("Naive h2", "num mut")])}</div></div>
    <div class="card" style="margin-top:12px"><h3>Method</h3><p>Comext arrives about two months after the month ends; exchange prices a few days after. Three explainable methods are back-tested on 24 rolling origins
      ('if I had estimated N months ago'): <b>naive</b> (last value), <b>ets</b> (damped-trend exponential smoothing, the Python twin of Excel's FORECAST.ETS),
      <b>signal</b> (regression on the World Bank price, metals only). The method with the lowest error at one and two months is kept, and its <b>80% interval is the
      10th-90th percentile of its own past errors</b>. The Excel tracker reproduces the nowcast with FORECAST.ETS and FORECAST.ETS.CONFINT.</p></div>"""
    R.add(f"For metals, the already-published LME price cuts the two-month nowcast error from {nb['naive']:.1%} to {nb['signal']:.1%}; thin markets get wide, honest intervals",
          "The months not yet published by Comext are estimated, tested on the past, and shown with an interval built from real past errors.",
          body, foot="Sources: Eurostat Comext, World Bank Pink Sheet (CC BY 4.0), ECB; data/marts/nowcast*.csv")

    # ---------------------------------------------------------- 9 survey
    sv, r = chart_survey()
    body = f"""<div class="row"><div class="card" style="flex:1"><h3>Design</h3><ul>
      <li><b>Population</b>: buyers and sellers of the defined product in the EU, stratified by role and volume; large firms always included.</li>
      <li><b>No anchoring</b>: no example price, no ranges to tick, no reference to last quarter; level asked before direction.</li>
      <li><b>Definitions on the question</b>: purity, form, period, unit, currency, Incoterm, contract vs spot.</li>
      <li><b>Two-sided</b>: buyers quote low, sellers high; both are kept apart until weighting.</li>
      <li><b>Processing</b>: standardise to EUR/kg delivered &rarr; plausible range &rarr; robust outliers (called back) &rarr; design weight × capped volume &rarr; bootstrap interval.</li></ul></div>
      <div class="card" style="flex:1.1"><img src="{sv}"><p class="mut">{r.n_invited} invited, {r.response_rate:.0%} response, {int(r.rejected)} answers rejected
      (a per-tonne price typed per kg, a typo, a decimal slip). Weighted mean {r.weighted_mean:.2f} EUR/kg, 90% interval {r.ci90_low:.2f}-{r.ci90_high:.2f};
      buyers {r.buyers_mean:.2f} vs sellers {r.sellers_mean:.2f}. The match with Comext is by construction of the simulation: the point is the method.</p></div>
      <div class="card" style="flex:0.9"><h3>Sample question (survey/questionnaire.md)</h3><p style="font-size:10.5px">
      <i>Product: anhydrous hydrogen fluoride, purity &ge; 99.9%, bulk. For deliveries during July-September 2026, what was the <b>average invoiced price</b>?</i><br>
      Price: ______ (no default) · Currency: EUR / USD · Unit: per kg / per tonne · Terms: delivered (DAP/DDP) / at plant or port (EXW/FOB) · Don't know</p>
      <h3 style="margin-top:10px">Consolidation</h3><p>The survey estimate is compared with the Comext unit value for the same quarter like any other source pair: inside the expected
      grade band it confirms both; outside it opens a discrepancy card.</p></div></div>
    <div class="card" style="margin-top:12px"><h3>Bias checklist (survey/METHOD.md)</h3>{t([
      ["Anchoring", "No numbers in questions; level before direction"], ["Strategic answers", "Both sides of the market; matched panel; confidentiality (cells of 5+)"],
      ["Non-response", "Reminders; response rate by stratum; weights recomputed on respondents"], ["Coverage", "Frame refreshed yearly from public registers and customer lists"],
      ["Definition drift", "Specification printed on each question; a new specification = a new series"], ["Unit errors", "Standardisation + robust outlier test, checked with the respondent"]],
      [("Bias", "b"), ("Counter-measure", "")], "tight")}</div>"""
    R.add("A two-sided, anchor-free survey can add the grade-specific prices that trade data cannot see",
          "Method, sample questionnaire and processing are real; the answers shown are SIMULATED (survey/process_survey.py, fixed seed) and are not TechInsights or market data.",
          body, tag="SIMULATED", foot="SIMULATED responses, calibrated on the public Comext unit value of hydrofluoric acid")

    # ---------------------------------------------------------- 10 methods
    src = [["Eurostat Comext DS-045409", "EU trade by CN8, monthly, value EUR, kg, supplementary units", "Eurostat reuse policy (CC BY 4.0)", "API, ~2-month lag"],
           ["UN Comtrade", "World trade by HS6, annual (public preview, no key)", "UN Comtrade terms: raw records not redistributed", "API"],
           ["USGS MCS 2025-2026", "Annual reference prices, US market", "Public domain (US government)", "ScienceBase"],
           ["World Bank Pink Sheet", "Monthly LME metal prices", "CC BY 4.0", "xlsx"],
           ["IMF, BLS via FRED", "Metal prices; producer price indexes", "IMF terms / public domain", "CSV"],
           ["ECB", "USD per EUR, monthly average", "ECB reuse with attribution", "API"]]
    body = f"""<div class="row"><div class="card" style="flex:1.3"><h3>Sources and licences (data/SOURCES.md)</h3>{t(src, [("Source", "b"), ("Content", ""), ("Licence", "mut"), ("Access", "mut")])}
      <h3 style="margin-top:10px">Reproduce</h3><p><code>python -m pipeline run</code> rebuilds raw &rarr; clean &rarr; marts, checks, reconciliation and nowcast (no key needed);
      <code>python src/build_excel.py</code> and <code>python src/build_report.py</code> rebuild the tracker and this report. Monthly procedure: docs/RUNBOOK.md.</p></div>
      <div class="card" style="flex:1"><h3>Limits</h3><ul>
      <li>A customs <b>unit value is not a transaction price</b>: it mixes grades, purities and contract terms; validated series reduce, not remove, the mix effect.</li>
      <li>Coverage is partial: EU border flows only; photoresists, NF<sub>3</sub>, precursors and electronic-grade chemicals have no public price.</li>
      <li>Recent months are revised by Eurostat; USGS last-year values are estimates.</li>
      <li>Plausible ranges and expected bands are judgement calls, documented in the seeds and open to review.</li>
      <li>No TechInsights or TECHCET figures are used or reproduced.</li></ul>
      <h3 style="margin-top:10px">AI note</h3><p>{AI_NOTE}</p></div></div>
    <div class="card" style="margin-top:12px"><h3>Pipeline (pipeline/, sql/)</h3><div class="row" style="align-items:stretch;gap:8px">{pipeline_boxes()}</div></div>"""
    R.add("Methods, limits and how to reproduce every number", "Public sources, open code, explicit limits.", body, tag=None,
          foot="All sources listed in data/SOURCES.md")
    return R


def pipeline_boxes() -> str:
    steps = [("1 Extract", "6 official APIs or files, polite rate, dated snapshots in data/raw"),
             ("2 Standardise", "parse, pivot, concordance; one schema in data/clean (DuckDB SQL)"),
             ("3 Check", "14 rules; implausible flows excluded; QUALITY_REPORT.md"),
             ("4 Marts", "monthly tracker, origins, annual, mirror flows, coverage"),
             ("5 Reconcile", "22 pairs, expected bands, DISCREPANCY_LOG.md"),
             ("6 Nowcast", "3 methods, 24-month back-test, 80% intervals")]
    out = []
    for i, (a, b) in enumerate(steps):
        out.append(f'<div style="flex:1;border:1px solid #E1E0D9;border-radius:6px;padding:7px 9px">'
                   f'<div class="b" style="font-size:11px">{a}</div><div class="mut" style="font-size:10px;line-height:1.35">{b}</div></div>')
        if i < len(steps) - 1:
            out.append('<div style="align-self:center;color:#898781">&rarr;</div>')
    return "".join(out)


def find_browser() -> str:
    for p in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"]:
        if Path(p).exists():
            return p
    raise FileNotFoundError("Edge or Chrome is needed to print the PDF")


def main():
    if BUILD.exists():
        shutil.rmtree(BUILD, ignore_errors=True)
    PDF.unlink(missing_ok=True)
    R = build()
    (BUILD / "report.html").write_text(R.html(), encoding="utf-8")
    profile = BUILD / "browser_profile"
    subprocess.run([find_browser(), "--headless", "--disable-gpu", "--no-pdf-header-footer", "--print-to-pdf-no-header",
                    f"--user-data-dir={profile}", f"--print-to-pdf={PDF}", (BUILD / "report.html").as_uri()],
                   check=True, capture_output=True, timeout=180)
    # Edge's launcher can return before the PDF is written: wait until the file exists and stops growing
    import time
    size, t0 = -1, time.time()
    while time.time() - t0 < 120:
        if PDF.exists() and PDF.stat().st_size == size and size > 0:
            break
        size = PDF.stat().st_size if PDF.exists() else -1
        time.sleep(2)
    from pypdf import PdfReader, PdfWriter
    rd = PdfReader(str(PDF))
    w = PdfWriter(clone_from=rd)
    w.add_metadata({"/Title": "TechInsights: tracking semiconductor materials prices from public sources", "/Author": "",
                    "/Creator": "", "/Producer": "", "/Subject": "Independent case study based on public data"})
    with open(PDF, "wb") as f:
        w.write(f)
    import pypdfium2 as pdfium
    IMG.mkdir(parents=True, exist_ok=True)
    names = ["00_overview", "01_techinsights", "02_materials_map", "03_standard", "04_quality", "05_discrepancies",
             "06_trends", "07_events", "08_nowcast", "09_survey_simulated", "10_methods"]
    doc = pdfium.PdfDocument(str(PDF))
    for i in range(len(doc)):
        doc[i].render(scale=1.6).to_pil().convert("RGB").save(IMG / f"{names[i] if i < len(names) else i}.png", optimize=True)
    print(f"  {PDF.relative_to(ROOT)}: {len(doc)} pages; images in docs/img")


if __name__ == "__main__":
    main()
