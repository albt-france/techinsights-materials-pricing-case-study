"""Extract the ECB reference exchange rate USD per EUR (monthly average) from the ECB Data Portal API."""
from __future__ import annotations

from .config import fetch, snapshot_path, stamp


def run() -> None:
    r = fetch("https://data-api.ecb.europa.eu/service/data/EXR/M.USD.EUR.SP00.A",
              params={"format": "csvdata", "startPeriod": "2015-01"})
    snapshot_path("ecb", "EXR_M_USD_EUR").write_text(r.text, encoding="utf-8")
    print(f"  ecb USD/EUR monthly, {r.text.count(chr(10)) - 1} rows")
    stamp("ecb")


if __name__ == "__main__":
    run()
