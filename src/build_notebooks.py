"""Create and execute the five notebooks in notebooks/ (short, readable walk-throughs of the marts).

    python src/build_notebooks.py

Notebook metadata is reduced to the kernel name so no local path or user name is stored.
"""
from __future__ import annotations

from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
NB = ROOT / "notebooks"

SETUP = """import pandas as pd, duckdb
from pathlib import Path
ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
M, C = ROOT / "data" / "marts", ROOT / "data" / "clean"
pd.set_option("display.width", 160); pd.set_option("display.max_columns", 20)"""

BOOKS = {
    "01_sources.ipynb": [
        ("md", "# 01 - Sources and coverage\nWhich public sources exist for each material, and what the standard table looks like. All data are PUBLIC."),
        ("code", SETUP),
        ("code", "pd.read_csv(M / 'coverage.csv')"),
        ("code", "obs = pd.read_csv(C / 'observations.csv')\nobs.groupby(['source', 'frequency']).agg(series=('series_id', 'nunique'), rows=('series_id', 'size'), first=('period', 'min'), last=('period', 'max'))"),
        ("code", "obs.sample(5, random_state=1)"),
    ],
    "02_quality.ipynb": [
        ("md", "# 02 - Quality checks\nResults of the 14 rules in `sql/03_checks.sql`, and the effect of the plausibility filter (QC14)."),
        ("code", SETUP),
        ("code", "pd.read_csv(C / 'quality_summary.csv')"),
        ("code", "qc = pd.read_csv(C / 'quality_checks.csv')\nqc[qc.check_id == 'QC03'].sort_values('value', key=abs, ascending=False).head(10)[['material_id', 'period', 'value', 'detail']]"),
        ("code", "m = pd.read_csv(M / 'monthly_prices.csv')\nne = m[m.material_id == 'NE'][['period', 'eu_import_uv_raw_eur_kg', 'eu_import_uv_eur_kg']]\nne.tail(12).round(1)"),
    ],
    "03_reconciliation.ipynb": [
        ("md", "# 03 - Reconciliation\nEach source pair has an expected band; gaps outside it are alerts with a discrepancy card (`docs/DISCREPANCY_LOG.md`)."),
        ("code", SETUP),
        ("code", "r = pd.read_csv(M / 'reconciliation_summary.csv')\nr[['pair_id', 'material_id', 'comparison', 'median_gap', 'expected_low', 'expected_high', 'alerts', 'latest_status', 'discrepancy_id']].round(3)"),
        ("code", "pd.read_csv(M / 'mirror_flows.csv').round(2)"),
        ("code", "pd.read_csv(M / 'usgs_revisions.csv').query('revision != 0').round(3)"),
    ],
    "04_trends_events.ipynb": [
        ("md", "# 04 - Trends and events\nEU import unit values (validated, 3-month weighted) and the origin mix around dated events (`seeds/events.csv`)."),
        ("code", SETUP),
        ("code", "m = pd.read_csv(M / 'monthly_prices.csv', parse_dates=['period'])\nlvl = m.assign(year=m.period.dt.year).groupby(['material_id', 'year']).apply(lambda g: g.eu_import_value_eur.sum() / g.eu_import_kg.sum(), include_groups=False).unstack().round(2)\nlvl"),
        ("code", "o = pd.read_csv(M / 'origin_monthly.csv', parse_dates=['period'])\nga = o[(o.material_id == 'GA') & (o.period >= '2022-07-01') & (o.period <= '2024-06-01')]\nga.assign(cn=ga.origin.eq('CN')).groupby([pd.Grouper(key='period', freq='QS'), 'cn']).quantity_kg.sum().unstack().div(1000).round(1)"),
        ("code", "pd.read_csv(ROOT / 'seeds' / 'events.csv')[['event_date', 'material_id', 'event']]"),
    ],
    "05_nowcast.ipynb": [
        ("md", "# 05 - Nowcast and back-test\nThree methods, 24 rolling origins, horizons 1-6 months; 80% intervals from past errors."),
        ("code", SETUP),
        ("code", "bt = pd.read_csv(M / 'nowcast_backtest.csv')\nbt[bt.horizon <= 2].pivot_table(index='material_id', columns=['method', 'horizon'], values='mape').round(3)"),
        ("code", "nc = pd.read_csv(M / 'nowcast.csv')\nnc[nc.selected == 1].round(2)"),
    ],
}


def main():
    NB.mkdir(exist_ok=True)
    for name, cells in BOOKS.items():
        nb = nbformat.v4.new_notebook()
        nb.cells = [nbformat.v4.new_markdown_cell(c) if k == "md" else nbformat.v4.new_code_cell(c) for k, c in cells]
        nb.metadata = {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                       "language_info": {"name": "python"}}
        NotebookClient(nb, timeout=120, kernel_name="python3", resources={"metadata": {"path": str(NB)}}).execute()
        nb.metadata = {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                       "language_info": {"name": "python"}}
        for c in nb.cells:
            c.metadata = {}
            if c.cell_type == "code":
                c.outputs = [o for o in c.outputs if o.get("name") != "stderr"]
        nbformat.write(nb, NB / name)
        print("  notebook", name)


if __name__ == "__main__":
    main()
