"""One command for the whole pipeline:

    python -m pipeline run                  # extract every source, then rebuild everything
    python -m pipeline run --skip-extract   # rebuild from the raw files already on disk

Layers: data/raw (as downloaded) -> data/clean (standard schema + checks) -> data/marts (tables
for Excel, the report and the reconciliation). Each extractor failure is reported and the run
continues with the last raw snapshot, so one source being down never blocks the monthly update.
"""
from __future__ import annotations

import argparse
import sys
import time

from . import (db, extract_comext, extract_comtrade, extract_ecb, extract_fred, extract_usgs,
               extract_worldbank, nowcast, quality_report, reconcile, standardize)
from .config import CLEAN, MARTS, RAW

EXTRACTORS = [("ecb", extract_ecb), ("worldbank", extract_worldbank), ("fred", extract_fred),
              ("usgs", extract_usgs), ("comext", extract_comext), ("comtrade", extract_comtrade)]

EXPORTS = [  # (table, file, order)
    ("observations", CLEAN / "observations.csv", "source, series_id, period"),
    ("quality_checks", CLEAN / "quality_checks.csv", "check_id, material_id, period"),
    ("quality_summary", CLEAN / "quality_summary.csv", "check_id"),
    ("mart_monthly_prices", MARTS / "monthly_prices.csv", "stage_order, material_id, period"),
    ("mart_fast_signals", MARTS / "fast_signals.csv", "series_id, period"),
    ("mart_origin_monthly", MARTS / "origin_monthly.csv", "material_id, period, origin"),
    ("mart_annual_prices", MARTS / "annual_prices.csv", "material_id, series_id, year"),
    ("mart_mirror", MARTS / "mirror_flows.csv", "material_id, year"),
    ("mart_usgs_revisions", MARTS / "usgs_revisions.csv", "series_id, year"),
    ("mart_coverage", MARTS / "coverage.csv", "stage_order, material_id"),
]


def run(skip_extract: bool) -> int:
    t0 = time.time()
    failures = []
    if not skip_extract:
        print("1/5 extract")
        for name, mod in EXTRACTORS:
            try:
                mod.run()
            except Exception as exc:          # keep the last snapshot and carry on
                failures.append(name)
                cached = any((RAW / name).glob("*.*")) if (RAW / name).exists() else False
                print(f"  !! {name} extraction failed ({exc}); using cached raw files: {cached}")
    print("2/5 standardize")
    standardize.run()
    con = db.connect()
    for f in ["01_staging.sql", "02_observations.sql"]:
        db.run_sql(con, f)
    print("3/5 quality checks")
    db.run_sql(con, "03_checks.sql")
    db.run_sql(con, "04_marts.sql")
    for table, path, order in EXPORTS:
        db.export(con, table, path, order)
    quality_report.write(con)
    print("4/5 reconciliation")
    reconcile.run(con)
    print("5/5 nowcast")
    nowcast.run(con)
    errors = con.execute("SELECT count(*) FROM quality_checks WHERE severity = 'error'").fetchall()[0][0]
    print(f"done in {time.time() - t0:.0f}s - {errors} error-level check rows"
          + (f" - extraction failed for: {', '.join(failures)}" if failures else ""))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m pipeline")
    p.add_argument("command", choices=["run"])
    p.add_argument("--skip-extract", action="store_true", help="rebuild from raw files already on disk")
    a = p.parse_args()
    return run(a.skip_extract)


if __name__ == "__main__":
    sys.exit(main())
