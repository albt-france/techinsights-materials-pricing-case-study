"""Extract annual reference prices from the USGS Mineral Commodity Summaries (public domain).

- MCS 2026 data release (one CSV for all commodities, years 2021-2025), DOI 10.5066/P1WKQ63T.
- MCS 2025 per-commodity data releases (years 2020-2024): used only to measure revisions
  between two editions for the same year.
Files are found through the ScienceBase catalogue API (the official USGS repository).
"""
from __future__ import annotations

from .config import fetch, snapshot_path, stamp

SB = "https://www.sciencebase.gov/catalog"
MCS2026_ITEM = "69837e43b66b01367d7ec7c7"   # "MCS 2026 Data Release - Commodity Salient U.S. and World Statistics"
MCS2025_COMMODITIES = ["GALLIUM", "GERMANIUM", "INDIUM", "SILICON", "TUNGSTEN", "COPPER",
                       "ALUMINUM", "NITROGEN (FIXED)-AMMONIA", "SULFUR", "FLUORSPAR"]


def _item_files(item_id: str) -> list[dict]:
    return fetch(f"{SB}/item/{item_id}", params={"format": "json"}).json().get("files", [])


def run() -> None:
    for f in _item_files(MCS2026_ITEM):
        if f["name"] == "MCS2026_Commodities_Data.csv":
            snapshot_path("usgs", "MCS2026_Commodities_Data").write_bytes(fetch(f["url"]).content)
            print("  usgs MCS2026_Commodities_Data.csv")

    for name in MCS2025_COMMODITIES:
        title = f"Mineral Commodity Summaries 2025 - {name} Data Release"
        items = fetch(f"{SB}/items", params={"q": f'"{title}"', "format": "json", "max": 5}).json().get("items", [])
        item = next((i for i in items if i.get("title", "").upper() == title.upper()), None)
        if item is None:
            print(f"  usgs MCS2025 {name}: not found, skipped")
            continue
        for f in _item_files(item["id"]):
            # the salient-statistics table holds the price line
            if f["name"].lower().endswith(".csv") and "salient" in f["name"].lower():
                tag = name.split()[0].split("(")[0].lower()
                snapshot_path("usgs", f"MCS2025_{tag}_salient").write_bytes(fetch(f["url"]).content)
                print(f"  usgs MCS2025 {name}: {f['name']}")
    stamp("usgs")


if __name__ == "__main__":
    run()
