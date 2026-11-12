"""Extract monthly metal prices from the World Bank Commodity Price Data ("Pink Sheet"), CC BY 4.0.

The workbook link is read from the official Pink Sheet page, because the file path changes
when the World Bank rolls the folder over each year.
"""
from __future__ import annotations

import re

from .config import fetch, snapshot_path, stamp

PAGE = ("https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/"
        "world-bank-commodities-price-data-the-pink-sheet")
FALLBACK = ("https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/"
            "related/CMO-Historical-Data-Monthly.xlsx")


def run() -> None:
    html = fetch(PAGE).text
    links = re.findall(r'https?://[^"\'\s]*CMO-Historical-Data-Monthly\.xlsx', html)
    url = links[0] if links else FALLBACK
    snapshot_path("worldbank", "CMO-Historical-Data-Monthly", "xlsx").write_bytes(fetch(url).content)
    print(f"  worldbank {url.rsplit('/', 1)[-1]}")
    stamp("worldbank")


if __name__ == "__main__":
    run()
