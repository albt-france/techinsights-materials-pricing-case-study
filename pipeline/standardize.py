"""Step 2 - parse every raw file into a tidy staging CSV, then build the standard table with SQL.

Python is used only where the raw format needs it (SDMX pivot, Excel sheet, USGS wide tables).
All joins, unit conversions and the standard schema itself live in sql/ (DuckDB), so they can
be read and reviewed as plain SQL.
"""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

from .config import CLEAN, RAW, SEEDS, START_MONTH, collected_on

FLOW = {1: "import", 2: "export"}


def _stg(df: pd.DataFrame, name: str) -> None:
    CLEAN.mkdir(parents=True, exist_ok=True)
    df.to_csv(CLEAN / f"stg_{name}.csv", index=False)
    print(f"  staging {name:18s} {len(df):>8,} rows")


def _pivot_sdmx(path: str) -> pd.DataFrame:
    """SDMX-CSV has one row per indicator; put value, kg and supplementary quantity side by side."""
    df = pd.read_csv(path, dtype={"product": str, "partner": str, "reporter": str})
    wide = df.pivot_table(index=["TIME_PERIOD", "reporter", "partner", "product", "flow"],
                          columns="indicators", values="OBS_VALUE", aggfunc="sum").reset_index()
    wide.columns.name = None
    for c in ["VALUE_IN_EUROS", "QUANTITY_IN_100KG", "SUPPLEMENTARY_QUANTITY"]:
        if c not in wide:
            wide[c] = np.nan
    return pd.DataFrame({
        "period": wide.TIME_PERIOD + "-01",
        "reporter": wide.reporter,
        "partner": wide.partner,
        "product_code": wide["product"],
        "flow": wide.flow.map(FLOW),
        "value_eur": wide.VALUE_IN_EUROS,
        "quantity_kg": wide.QUANTITY_IN_100KG * 100,       # Comext publishes quantity in 100 kg
        "quantity_supp": wide.SUPPLEMENTARY_QUANTITY,
    })


def comext() -> None:
    parts = []
    for path in sorted(glob.glob(str(RAW / "comext" / "eu27_*.csv"))):
        material = path.rsplit("eu27_", 1)[1][:-4]
        d = _pivot_sdmx(path)
        d.insert(1, "material_id", material)
        parts.append(d)
    df = pd.concat(parts)
    df["product_level"] = np.where(df.product_code.str.len() == 8, "CN8", "HS6")
    _stg(df, "comext")
    _stg(_pivot_sdmx(str(RAW / "comext" / "de_mirror_hs6.csv")), "comext_de_mirror")
    _stg(_pivot_sdmx(str(RAW / "comext" / "brexit_composition_check.csv")), "comext_composition")


def worldbank() -> None:
    xl = pd.read_excel(RAW / "worldbank" / "CMO-Historical-Data-Monthly.xlsx", sheet_name="Monthly Prices", header=None)
    names = xl.iloc[4].astype(str).str.strip()
    cat = pd.read_csv(SEEDS / "series_catalog.csv")
    rows = []
    for s in cat[cat.source == "WORLDBANK"].itertuples():
        col = names[names == s.native_id].index[0]
        d = xl.iloc[6:, [0, col]].copy()
        d.columns = ["period", "value"]
        d["series_id"] = s.series_id
        rows.append(d)
    df = pd.concat(rows)
    df["period"] = df.period.str.replace("M", "-") + "-01"
    df["value"] = pd.to_numeric(df.value, errors="coerce")       # '..' and blanks become NaN
    _stg(df[df.period >= "2015-01-01"], "worldbank")


def fred() -> None:
    cat = pd.read_csv(SEEDS / "series_catalog.csv")
    rows = []
    for s in cat[cat.source.isin(["BLS", "IMF"])].itertuples():
        d = pd.read_csv(RAW / "fred" / f"{s.native_id}.csv")
        d.columns = ["period", "value"]
        d["value"] = pd.to_numeric(d.value, errors="coerce")      # FRED marks missing as '.'
        d["series_id"] = s.series_id
        rows.append(d[d.period >= "2015-01-01"])
    _stg(pd.concat(rows), "fred")


def ecb() -> None:
    d = pd.read_csv(RAW / "ecb" / "EXR_M_USD_EUR.csv", usecols=["TIME_PERIOD", "OBS_VALUE"])
    _stg(pd.DataFrame({"period": d.TIME_PERIOD + "-01", "usd_per_eur": d.OBS_VALUE}), "fx")


def _usgs_number(x) -> float:
    """USGS cells can hold '1,070', 'W' (withheld for confidentiality), 'NA', or '>50'."""
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return np.nan


def usgs() -> None:
    seed = pd.read_csv(SEEDS / "usgs_series.csv")
    mcs26 = pd.read_csv(RAW / "usgs" / "MCS2026_Commodities_Data.csv", encoding="latin1", low_memory=False)
    mcs26 = mcs26[mcs26.Statistics.astype(str).str.strip() == "Price"]
    rows = []
    for s in seed.itertuples():
        d = mcs26[mcs26["MCS chapter"].astype(str).str.upper().str.startswith(s.mcs2026_chapter)
                  & mcs26.Statistics_detail.astype(str).str.contains(s.mcs2026_detail_contains, regex=False)]
        for r in d.itertuples():
            rows.append({"series_id": s.series_id, "edition": "MCS2026", "year": int(r.Year),
                         "raw_value": r.Value, "value_native": _usgs_number(r.Value)})
        f = RAW / "usgs" / f"{s.mcs2025_file}.csv"
        if f.exists():
            d25 = pd.read_csv(f, encoding="utf-8-sig", dtype=str)
            for rec in d25.to_dict("records"):
                raw = rec[s.mcs2025_column]
                rows.append({"series_id": s.series_id, "edition": "MCS2025", "year": int(rec["Year"]),
                             "raw_value": raw, "value_native": _usgs_number(raw)})
    _stg(pd.DataFrame(rows), "usgs")


def comtrade() -> None:
    f = RAW / "comtrade" / "comtrade_annual.csv"
    if not f.exists() or f.stat().st_size < 10:
        print("  staging comtrade: no raw file (source skipped, flagged by the checks)")
        pd.DataFrame(columns=["year", "reporter", "flow", "partner", "hs6", "value_usd",
                              "cif_usd", "fob_usd", "net_kg", "kg_estimated"]).to_csv(CLEAN / "stg_comtrade.csv", index=False)
        return
    d = pd.read_csv(f, dtype={"cmdCode": str})
    _stg(pd.DataFrame({"year": d.refYear, "reporter": d.reporterCode, "flow": d.flowCode.map({"M": "import", "X": "export"}),
                       "partner": d.partnerCode, "hs6": d.cmdCode, "value_usd": d.primaryValue,
                       "cif_usd": d.cifvalue, "fob_usd": d.fobvalue, "net_kg": d.netWgt,
                       "kg_estimated": d.isNetWgtEstimated}), "comtrade")


def collection_dates() -> None:
    _stg(pd.DataFrame({"source": ["COMEXT", "COMTRADE", "USGS", "WORLDBANK", "IMF", "BLS", "ECB"],
                       "collected_on": [collected_on("comext"), collected_on("comtrade"), collected_on("usgs"),
                                        collected_on("worldbank"), collected_on("fred"), collected_on("fred"),
                                        collected_on("ecb")]}), "collected_on")


def run() -> None:
    comext(); worldbank(); fred(); ecb(); usgs(); comtrade(); collection_dates()


if __name__ == "__main__":
    run()
