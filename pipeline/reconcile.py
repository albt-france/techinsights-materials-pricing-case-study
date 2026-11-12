"""Step 4 - compare sources pair by pair, raise alerts, and write the discrepancy log.

Each pair in seeds/reconciliation_pairs.csv has an EXPECTED band (e.g. CIF import value should
sit 0-6% above the LME price). A gap inside the band is normal; outside it is an alert.
The narrative of each discrepancy (root cause, correction, prevention) lives in
seeds/discrepancy_register.csv; the evidence numbers are recomputed here at every run, so
docs/DISCREPANCY_LOG.md never drifts away from the data.
"""
from __future__ import annotations

import pandas as pd

from .config import MARTS, ROOT, SEEDS


def _series(con) -> pd.DataFrame:
    """All comparable values in one long table: series_id, period, value (USD/kg or a ratio)."""
    q = """
    SELECT 'COMEXT_IMP_' || material_id AS series_id, 'M' AS freq, period, eu_import_uv_usd_kg AS value
      FROM mart_monthly_prices
    UNION ALL SELECT 'COMEXT_IMP_' || material_id || '_RAW', 'M', period, eu_import_uv_raw_eur_kg * usd_per_eur
      FROM mart_monthly_prices
    UNION ALL SELECT series_id, 'M', period, price_usd_kg FROM observations WHERE source IN ('WORLDBANK', 'IMF')
    UNION ALL SELECT series_id, 'A', make_date(year, 1, 1), uv_usd_kg FROM mart_annual_prices WHERE source = 'COMEXT'
    UNION ALL SELECT series_id, 'A', make_date(year, 1, 1), avg_price_usd_kg FROM mart_annual_prices WHERE source IN ('WORLDBANK', 'IMF')
    UNION ALL SELECT series_id, 'A', period, price_usd_kg FROM observations WHERE source IN ('USGS', 'COMTRADE')
    """
    return con.sql(q).df()


def _ratio_pairs(con) -> dict[str, pd.DataFrame]:
    """Pairs whose 'gap' is computed directly in SQL (mirror flows, revisions, shares)."""
    return {
        "MIRROR_POLYSI_VALUE": con.sql("SELECT make_date(year,1,1) AS period, de_value_usd AS a, partner_value_usd AS b, value_gap AS gap FROM mart_mirror WHERE material_id='POLYSI'").df(),
        "MIRROR_GA+GE+IN_VALUE": con.sql("SELECT make_date(year,1,1) AS period, de_value_usd AS a, partner_value_usd AS b, value_gap AS gap FROM mart_mirror WHERE material_id='GA+GE+IN'").df(),
        "MIRROR_WAFER_KG": con.sql("SELECT make_date(year,1,1) AS period, de_kg AS a, partner_kg AS b, kg_gap AS gap FROM mart_mirror WHERE material_id='WAFER'").df(),
        "USGS_REVISIONS": con.sql("SELECT make_date(year,1,1) AS period, mcs2026 AS a, mcs2025 AS b, revision AS gap, series_id AS detail FROM mart_usgs_revisions").df(),
        "HE_CONFIDENTIAL_SHARE": con.sql("SELECT period, hidden_value AS a, extra_value AS b, hidden_share AS gap FROM confidential_share WHERE material_id='HE' AND flow='import'").df(),
        "EU_VS_EU27_POLYSI": con.sql("SELECT period, eu_changing_extra AS a, eu27_2020_extra AS b, eu_changing_extra/eu27_2020_extra-1 AS gap FROM mart_composition WHERE product_code='28046100' AND period < DATE '2020-02-01'").df(),
    }


def build(con) -> tuple[pd.DataFrame, pd.DataFrame]:
    pairs = pd.read_csv(SEEDS / "reconciliation_pairs.csv")
    s = _series(con)
    ratio = _ratio_pairs(con)
    rows = []
    for p in pairs.itertuples():
        if p.series_a in ratio:
            d = ratio[p.series_a].copy()
        else:
            f = s[s.freq == p.frequency]            # monthly and annual versions share a series_id
            a = f[f.series_id == p.series_a][["period", "value"]].rename(columns={"value": "a"})
            b = f[f.series_id == p.series_b][["period", "value"]].rename(columns={"value": "b"})
            d = a.merge(b, on="period").dropna()
            d["gap"] = d.a / d.b - 1
        if "detail" not in d:
            d["detail"] = ""
        d = d.dropna(subset=["gap"])
        for r in d.itertuples():
            inside = (pd.isna(p.expected_low) or r.gap >= p.expected_low) and (pd.isna(p.expected_high) or r.gap <= p.expected_high)
            rows.append({"pair_id": p.pair_id, "material_id": p.material_id, "frequency": p.frequency,
                         "period": pd.Timestamp(r.period).date(), "series_a": p.series_a, "series_b": p.series_b,
                         "value_a": r.a, "value_b": r.b, "gap": r.gap, "expected_low": p.expected_low,
                         "expected_high": p.expected_high,
                         "status": "not comparable" if pd.isna(p.expected_low) else ("ok" if inside else "ALERT"),
                         "discrepancy_id": p.discrepancy_id, "comparison": p.comparison, "detail": r.detail})
    detail = pd.DataFrame(rows)
    g = detail.groupby(["pair_id", "material_id", "comparison", "discrepancy_id"], dropna=False)
    summary = g.agg(observations=("gap", "size"), median_gap=("gap", "median"), min_gap=("gap", "min"),
                    max_gap=("gap", "max"), alerts=("status", lambda x: int((x == "ALERT").sum())),
                    first_period=("period", "min"), last_period=("period", "max")).reset_index()
    last = detail.sort_values("period").groupby("pair_id").tail(1)[["pair_id", "gap", "status"]]
    summary = summary.merge(last.rename(columns={"gap": "latest_gap", "status": "latest_status"}), on="pair_id")
    bands = pairs[["pair_id", "expected_low", "expected_high"]]
    summary = summary.merge(bands, on="pair_id").sort_values("pair_id")
    # "|GA|GE|IN|": lets Excel count alerts per material with a wildcard that cannot mix AL and ALL
    summary["material_key"] = "|" + summary.material_id.str.replace("+", "|", regex=False) + "|"
    return detail, summary


def _pct(x: float) -> str:
    return "n/a" if pd.isna(x) else f"{x:+.0%}"


def evidence(con, summary: pd.DataFrame) -> dict[str, str]:
    """One evidence paragraph per discrepancy, built from the latest data."""
    sm = summary.set_index("pair_id")
    ev = {}
    ev["D01"] = "; ".join(f"{m}: median gap {_pct(sm.loc[p, 'median_gap'])} (band {_pct(sm.loc[p, 'expected_low'])} to {_pct(sm.loc[p, 'expected_high'])}), {sm.loc[p, 'alerts']} alert months out of {sm.loc[p, 'observations']}"
                          for p, m in [("R01", "Copper"), ("R02", "Tin"), ("R03", "Aluminium")])
    ev["D01"] += f". Control: World Bank vs IMF copper median gap {_pct(sm.loc['R04', 'median_gap'])}, so the benchmarks agree and the gap is in the EU valuation."
    ev["D02"] = (f"US aluminium spot vs LME: gap {_pct(sm.loc['R07', 'min_gap'])} to {_pct(sm.loc['R07', 'max_gap'])}, latest year {_pct(sm.loc['R07', 'latest_gap'])}. "
                 f"EU silicon metal import unit value vs US market price: median {_pct(sm.loc['R11', 'median_gap'])}.")
    rev = con.sql("SELECT year, mcs2025, mcs2026, revision FROM mart_usgs_revisions WHERE series_id='USGS_GA' ORDER BY year").df()
    ev["D03"] = "Same years, two editions: " + "; ".join(f"{int(r.year)}: {r.mcs2025:.0f} -> {r.mcs2026:.0f} USD/kg ({r.revision:+.0%})" for r in rev.itertuples()) + \
                f". After aligning definitions, EU vs US import unit value median gap is {_pct(sm.loc['R08', 'median_gap'])}."
    ge = con.sql("SELECT year AS yr, round(uv_usd_kg) AS eu FROM mart_annual_prices WHERE series_id='COMEXT_IMP_GE' AND year BETWEEN 2023 AND 2025 ORDER BY year").df()
    us = con.sql("SELECT year(period) AS yr, round(price_usd_kg) AS us FROM observations WHERE series_id='USGS_GE_METAL' AND year(period) BETWEEN 2023 AND 2025").df()
    j = ge.merge(us, on="yr")
    ev["D04"] = "EU import unit value vs USGS metal price (USD/kg): " + "; ".join(f"{int(r.yr)}: {r.eu:,.0f} vs {r.us:,.0f}" for r in j.itertuples()) + "."
    ev["D05"] = f"EU unit value per kg of concentrate divided by the USGS price per kg of WO3 ranges from {sm.loc['R14', 'min_gap'] + 1:.0%} to {sm.loc['R14', 'max_gap'] + 1:.0%} (implied WO3 content), far outside a physical 50-75% range for a single concentrate grade."
    pol = con.sql("""SELECT year(period) y, origin, sum(value_eur)/sum(quantity_kg) uv, sum(quantity_kg)/1000 t
                     FROM mart_origin_monthly WHERE material_id='POLYSI' AND origin IN ('US','CN') AND year(period) IN (2022, 2025)
                     GROUP BY ALL ORDER BY y, origin""").df()
    ev["D06"] = "EU import unit value by origin (EUR/kg, tonnes): " + "; ".join(f"{int(r.y)} {r.origin}: {r.uv:.1f} EUR/kg on {r.t:,.0f} t" for r in pol.itertuples()) + "."
    ev["D07"] = f"Value gap (DE exports FOB / CN imports CIF - 1): median {_pct(sm.loc['R16', 'median_gap'])}, range {_pct(sm.loc['R16', 'min_gap'])} to {_pct(sm.loc['R16', 'max_gap'])}, {sm.loc['R16', 'alerts']} alert years."
    ev["D08"] = f"Germany's reported value is {sm.loc['R17', 'min_gap'] + 1:.1f}x to {sm.loc['R17', 'max_gap'] + 1:.1f}x China's mirror figure (median {sm.loc['R17', 'median_gap'] + 1:.1f}x)."
    vg = con.execute("SELECT min(value_gap), max(value_gap) FROM mart_mirror WHERE material_id='WAFER'").fetchall()[0]
    ev["D09"] = (f"Net kg reported by Germany vs Japan: {sm.loc['R18', 'min_gap'] + 1:.1f}x to {sm.loc['R18', 'max_gap'] + 1:.1f}x, "
                 f"while the value gap stays between {vg[0]:+.0%} and {vg[1]:+.0%}.")
    rv = con.sql("SELECT series_id, revision FROM mart_usgs_revisions WHERE year=2024 AND series_id<>'USGS_GA' AND revision<>0 ORDER BY revision").df()
    ev["D10"] = "2024 values, MCS2026 vs MCS2025: " + "; ".join(f"{r.series_id.replace('USGS_', '')} {r.revision:+.1%}" for r in rv.itertuples()) + "."
    ch = con.sql("""SELECT year(period) y, partner, sum(quantity_kg)/1000 t, sum(value_eur)/sum(quantity_kg) uv FROM partner_rows
                    WHERE material_id='NE' AND flow='import' AND quantity_kg>0 AND (uv<lo OR uv>hi) GROUP BY ALL ORDER BY t DESC LIMIT 3""").df()
    ev["D11"] = "Largest excluded flows: " + "; ".join(f"{int(r.y)} {r.partner}: {r.t:,.0f} t at {r.uv:.2f} EUR/kg" for r in ch.itertuples()) + \
                f". Published vs validated unit value: median gap {_pct(sm.loc['R20', 'median_gap'])}, {sm.loc['R20', 'alerts']} months outside +/-25%."
    hs = con.execute("SELECT sum(hidden_value)/sum(extra_value) s FROM confidential_share WHERE material_id='HE' AND flow='import'").fetchall()[0][0]
    ev["D12"] = f"Confidential partner share of EU helium imports, 2018-latest: {hs:.0%} of value; {sm.loc['R21', 'alerts']} months above 10%."
    ev["D13"] = f"Polysilicon extra-EU imports, 'EU' vs EU27_2020 before February 2020: median gap {_pct(sm.loc['R22', 'median_gap'])} (range {_pct(sm.loc['R22', 'min_gap'])} to {_pct(sm.loc['R22', 'max_gap'])})."
    dens = con.execute("SELECT median(kg_per_m3) FROM gas_density WHERE material_id='HE'").fetchall()[0][0]
    ev["D14"] = f"Median implied density of EU helium imports: {dens:.3f} kg/m3 vs 0.179 kg/m3 for helium at 0 C and 1 atm ({dens / 0.1786 - 1:+.0%})."
    return ev


def write_log(con, summary: pd.DataFrame) -> None:
    reg = pd.read_csv(SEEDS / "discrepancy_register.csv")
    ev = evidence(con, summary)
    reg["evidence"] = reg.discrepancy_id.map(ev)
    reg.to_csv(MARTS / "discrepancy_log.csv", index=False)
    lines = ["# Discrepancy log", "",
             "Every gap between sources that matters, written as: **finding -> root cause -> evidence -> correction -> prevention**.",
             "Evidence numbers are recomputed by `python -m pipeline run` (see `pipeline/reconcile.py`); the narrative lives in `seeds/discrepancy_register.csv`.",
             "Pair-level gaps and alerts: `data/marts/reconciliation_summary.csv` and the *Reconciliation* sheet of the Excel tracker.", "",
             "| ID | Discrepancy | Materials | Status |", "|---|---|---|---|"]
    lines += [f"| [{r.discrepancy_id}](#{r.discrepancy_id.lower()}) | {r.title} | {r.materials} | {r.status} |" for r in reg.itertuples()]
    for r in reg.itertuples():
        lines += ["", f"## {r.discrepancy_id}", f"**{r.title}** ({r.materials}) - status: *{r.status}*", "",
                  f"- **Root cause:** {r.root_cause}", f"- **Evidence:** {r.evidence}",
                  f"- **Correction:** {r.correction}", f"- **Prevention:** {r.prevention}"]
    (ROOT / "docs" / "DISCREPANCY_LOG.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("  docs/DISCREPANCY_LOG.md written")


def run(con) -> None:
    detail, summary = build(con)
    detail.to_csv(MARTS / "reconciliation_detail.csv", index=False)
    summary.to_csv(MARTS / "reconciliation_summary.csv", index=False)
    print(f"  reconciliation: {len(summary)} pairs, {len(detail)} comparisons, {int((detail.status == 'ALERT').sum())} alerts")
    write_log(con, summary)
