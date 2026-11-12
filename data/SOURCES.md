# Data sources

Every series used in this project is **public data**. The only simulated data are the survey
answers in `survey/`, labelled **SIMULATED**. No TechInsights or TECHCET figures are used.
Collection date of each source: `data/raw/<source>/_collected_on.txt` (this release: 2026-11-12).

| Source | Series | Unit (native) | Access | Licence / terms | Raw data in the repo |
|---|---|---|---|---|---|
| Eurostat Comext, dataset DS-045409 "EU trade since 1988 by HS2-4-6 and CN8" | Monthly imports and exports of EU27_2020 by CN8 product and partner: value, quantity, supplementary quantity, 2018-01 to 2026-08 | EUR, 100 kg, m3 | SDMX 2.1 API, `ec.europa.eu/eurostat/api/comext/dissemination` | Eurostat copyright / reuse policy: free reuse with acknowledgement (CC BY 4.0) | Not committed (about 50 MB); re-downloaded by `python -m pipeline run`. Aggregated tables are in `data/clean` and `data/marts` |
| UN Comtrade | Annual trade by HS6 (China, Japan, United States), 2018-2025 | USD, kg | Official API, public preview endpoint (no key) | UN Comtrade terms of use: raw records not redistributed | Not committed; only aggregates in `data/marts` |
| USGS Mineral Commodity Summaries 2026 data release (DOI 10.5066/P1WKQ63T) and MCS 2025 commodity data releases | Annual prices: silicon metal, gallium, germanium, indium, tungsten, copper, aluminium, ammonia, sulfur, fluorspar, 2020-2025 | as published (cents/lb, USD/kg, USD/short ton...) | ScienceBase catalogue API | Public domain (US government) | Committed (`data/raw/usgs`) |
| World Bank Commodity Price Data ("Pink Sheet"), monthly | Copper, tin, aluminium (LME cash) | USD/mt | Official xlsx | CC BY 4.0 | Committed |
| IMF Primary Commodity Prices, via FRED (`PCOPPUSDM`, `PTINUSDM`, `PALUMUSDM`) | Copper, tin, aluminium | USD/mt | FRED CSV download | IMF copyright and usage: free reuse with attribution | Committed |
| US BLS Producer Price Indexes, via FRED (`PCU334413334413`, `PCU325120325120`, `PCU325180325180`, `PCU331410331410`) | Semiconductors, industrial gases, other basic inorganic chemicals, non-ferrous metals | index | FRED CSV download | Public domain (US government) | Committed |
| European Central Bank, `EXR.M.USD.EUR.SP00.A` | USD per EUR, monthly average | rate | ECB Data Portal API | ECB reuse with source attribution | Committed |
| techinsights.com (public pages only) | Company facts | - | Read on 2026-11-12, `robots.txt` respected | Facts cited with their URL | `data/raw/techinsights_site/public_facts.md` |
| Events | MOFCOM announcements (No. 23/2023, No. 46/2024, No. 72/2025), White House proclamations on Section 232, US ITA notices, Reuters (via CNN) on neon | - | Public web pages | Cited, not reproduced | `seeds/events.csv` |

## Collection rules
- Official APIs or official download files only; a 1.5-second pause between calls and back-off on
  HTTP 429; dated snapshots; nothing behind a login or paywall.
- A free UN Comtrade key can be put in a local `.env` (`COMTRADE_KEY=...`); `.env` is git-ignored.

## Material codes
See `seeds/materials.csv` (dictionary) and `seeds/code_concordance.csv` (CN8 codes by validity
period). Definitions and units: `docs/DATA_STANDARDS.md`.

## Known source limits
- A customs unit value (value / kg) is not a transaction price: it mixes grades and contracts.
- Recent Comext months are revised; the latest USGS year is an estimate.
- Some flows are confidential (partner codes `Q*`), and some USGS cells are withheld (`W`).
