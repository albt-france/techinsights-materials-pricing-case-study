"""Extract EU trade by CN8 product from Eurostat Comext (dataset DS-045409, monthly).

API: Eurostat Comext SDMX 2.1 dissemination API, SDMX-CSV format (no key needed).
Key layout: FREQ.REPORTER.PARTNER.PRODUCT.FLOW.INDICATORS
  - reporter EU27_2020 = the 27 current member states for the whole history (no Brexit break)
  - flow 1 = import (valued CIF at the EU border), 2 = export (valued FOB)
  - indicators: VALUE_IN_EUROS, QUANTITY_IN_100KG, SUPPLEMENTARY_QUANTITY (e.g. m3 for gases)
"""
from __future__ import annotations

import pandas as pd

from .config import START_MONTH, fetch, snapshot_path, stamp, SEEDS

BASE = "https://ec.europa.eu/eurostat/api/comext/dissemination/sdmx/2.1/data/DS-045409/"
INDICATORS = "VALUE_IN_EUROS+QUANTITY_IN_100KG+SUPPLEMENTARY_QUANTITY"


def _download(key: str, start: str, end: str | None) -> str:
    params = {"startPeriod": start, "format": "SDMX-CSV"}
    if end:
        params["endPeriod"] = end
    text = fetch(BASE + key, params=params).text
    # Very large extractions are not answered synchronously: the API returns a SOAP
    # "SUBMITTED" envelope instead of CSV. Fail loudly so the caller can split the request.
    if text.lstrip().startswith("<"):
        raise ValueError("asynchronous answer (request too large)")
    return text


def _get(key: str, name: str, start: str = START_MONTH, end: str | None = None) -> int:
    text = _download(key, start, end)
    snapshot_path("comext", name).write_text(text, encoding="utf-8")
    return max(text.count("\n") - 1, 0)


def run() -> None:
    conc = pd.read_csv(SEEDS / "code_concordance.csv", dtype=str)
    mats = pd.read_csv(SEEDS / "materials.csv", dtype=str)
    for m in mats.itertuples():
        # every CN8 code ever used for this material (old and new nomenclature) + its HS6 heading.
        # One request per code keeps every answer small enough to come back synchronously.
        codes = sorted(set(conc.loc[conc.material_id == m.material_id, "cn8_code"]) | {m.hs6})
        parts = []
        for code in codes:
            text = _download(f"M.EU27_2020..{code}.1+2.{INDICATORS}", START_MONTH, None)  # empty partner = all
            parts.append(text if not parts else text.split("\n", 1)[1])                 # keep one header
        text = "".join(p if p.endswith("\n") else p + "\n" for p in parts)
        snapshot_path("comext", f"eu27_{m.material_id}").write_text(text, encoding="utf-8")
        print(f"  comext {m.material_id:7s} {len(codes)} codes, {text.count(chr(10)) - 1} rows")

    # Mirror-statistics pairs (Germany as reporter, HS6 level) for the reconciliation step
    n = _get(f"M.DE.CN+JP+US.280461+811292+381800+280429.1+2.{INDICATORS}", "de_mirror_hs6")
    print(f"  comext DE mirror pairs, {n} rows")

    # Coverage check: the 'EU' reporter changes composition (UK left on 2020-02-01)
    n = _get(f"M.EU+EU27_2020.EXT_EU+EXT_EU27_2020.28046100+74031100.1.VALUE_IN_EUROS",
             "brexit_composition_check", start="2018-01", end="2020-12")
    print(f"  comext composition check, {n} rows")
    stamp("comext")


if __name__ == "__main__":
    run()
