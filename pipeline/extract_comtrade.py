"""Extract annual trade by HS6 product from UN Comtrade (official API).

Without a key the public 'preview' endpoint is used: one period per call, max 500 rows, rate
limited, so the project keeps this source small and annual. With a free key in .env
(COMTRADE_KEY=...) the same calls go through the authenticated endpoint.

UN Comtrade terms do not allow bulk redistribution of raw records, so data/raw/comtrade/ is
git-ignored; only aggregated results appear in data/marts/.
"""
from __future__ import annotations

import os

import pandas as pd

from .config import fetch, load_env, snapshot_path, stamp

YEARS = range(2018, 2026)
# (reporter M49 code, flow, HS6 codes, partner codes): partner 0 = World, 276 = Germany
REQUESTS = [
    ("156", "X", "280461,280469,811292,280429", "0,276"),   # China exports: world + Germany (mirror)
    ("156", "M", "280461", "0,276"),                        # China imports of polysilicon (mirror of DE exports)
    ("392", "X", "381800", "0,276"),                        # Japan exports of doped wafers
    ("842", "M", "811292,280429,381800", "0"),              # United States imports
]
KEEP = ["refYear", "reporterCode", "flowCode", "partnerCode", "cmdCode", "primaryValue",
        "cifvalue", "fobvalue", "netWgt", "isNetWgtEstimated", "qty", "qtyUnitCode",
        "customsCode", "motCode", "partner2Code", "mosCode"]


def run() -> None:
    load_env()
    key = os.environ.get("COMTRADE_KEY")
    base = ("https://comtradeapi.un.org/data/v1/get/C/A/HS" if key
            else "https://comtradeapi.un.org/public/v1/preview/C/A/HS")
    headers = {"Ocp-Apim-Subscription-Key": key} if key else {}
    rows = []
    for reporter, flow, cmds, partners in REQUESTS:
        for year in YEARS:
            params = {"reporterCode": reporter, "period": str(year), "cmdCode": cmds,
                      "flowCode": flow, "partnerCode": partners,
                      "partner2Code": "0", "customsCode": "C00", "motCode": "0"}
            try:
                data = fetch(base, params=params, headers=headers).json().get("data") or []
            except Exception as exc:  # keep going: one missing year is reported by the checks
                print(f"  comtrade {reporter} {flow} {year}: FAILED ({exc})")
                continue
            rows += [{k: d.get(k) for k in KEEP} for d in data]
            print(f"  comtrade {reporter} {flow} {year}: {len(data)} rows")
    pd.DataFrame(rows).to_csv(snapshot_path("comtrade", "comtrade_annual"), index=False)
    stamp("comtrade")


if __name__ == "__main__":
    run()
