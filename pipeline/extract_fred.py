"""Extract monthly series from FRED (Federal Reserve Bank of St. Louis) as plain CSV, no key needed.

- BLS Producer Price Indexes (public domain, US government): fast monthly signals used for
  context and as nowcast drivers.
- IMF Primary Commodity Prices (as redistributed by FRED): a second benchmark for metals,
  to reconcile against the World Bank Pink Sheet.
"""
from __future__ import annotations

import pandas as pd

from .config import fetch, snapshot_path, stamp, SEEDS


def run() -> None:
    series = pd.read_csv(SEEDS / "series_catalog.csv")
    for s in series[series.source.isin(["BLS", "IMF"])].itertuples():
        r = fetch("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": s.native_id})
        snapshot_path("fred", s.native_id).write_text(r.text, encoding="utf-8")
        print(f"  fred {s.native_id:18s} {r.text.count(chr(10)) - 1} rows")
    stamp("fred")


if __name__ == "__main__":
    run()
