# Data standards

One schema, one set of units and one set of conventions for every source. The standards are
data, not prose: they live in `seeds/` and the pipeline enforces them.

| Standard | File | Enforced by |
|---|---|---|
| Material dictionary (stage, codes, unit, grade, plausible price range) | `seeds/materials.csv` | `sql/02_observations.sql`, `sql/03_checks.sql` (QC14) |
| Customs-code concordance with validity dates | `seeds/code_concordance.csv` | `sql/01_staging.sql` (`stg_comext_cn8`), QC05, QC06 |
| Series catalogue (source, native unit, valuation, licence) | `seeds/series_catalog.csv` | `sql/02_observations.sql` |
| USGS series and unit conversion factors | `seeds/usgs_series.csv` | `pipeline/standardize.py`, `sql/02_observations.sql` |
| Source pairs and expected gap bands | `seeds/reconciliation_pairs.csv` | `pipeline/reconcile.py` |
| Discrepancy register (cause, correction, prevention) | `seeds/discrepancy_register.csv` | `pipeline/reconcile.py` -> `docs/DISCREPANCY_LOG.md` |
| Dated events | `seeds/events.csv` | report, Excel `data_events` |

## 1. Standard schema - `data/clean/observations.csv`

One row = one observation of one series.

| Column | Type | Rule |
|---|---|---|
| `period` | date | First day of the month (monthly) or of the year (annual) |
| `frequency` | text | `M` or `A` |
| `material_id` | text | Key of `seeds/materials.csv`; HS6 headings shared by several materials are written `GA+GE+IN` |
| `source` | text | `COMEXT`, `COMTRADE`, `USGS`, `WORLDBANK`, `IMF`, `BLS` |
| `series_id` | text | Stable code, e.g. `COMEXT_IMP_GA`, `WB_COPPER`, `COMTRADE_156_export_0_280461` (reporter_flow_partner_hs6) |
| `flow` | text | `import`, `export`, `price`, `index` |
| `reporter`, `partner` | text | Who reports, and the counterpart (`EU27_2020`, `EXTRA_EU`, M49 codes for Comtrade, `GLOBAL`, `US`) |
| `valuation` | text | `CIF`, `FOB`, `Spot (LME cash)`, `same_product`, `feedstock`, `content_basis`, `Producer price index` |
| `product_code`, `nomenclature` | text | CN8 codes summed (`76011010+76011090`) or HS6 |
| `value_native`, `currency` | number, text | As published |
| `quantity_kg` | number | Net mass in kg. Comext publishes 100 kg units: x 100 |
| `quantity_supp`, `supp_unit` | number, text | Supplementary unit when it exists (m3 for helium and rare gases) |
| `price_native`, `price_unit_native` | number, text | Price in the source's own unit |
| `usd_per_eur` | number | ECB monthly average; annual mean for annual data |
| `price_eur_kg`, `price_usd_kg` | number | **The standardised price.** Every comparison uses these two columns |
| `collected_on` | date | Collection date of the raw snapshot |

## 2. Units

| Native unit | To USD/kg | Used by |
|---|---|---|
| USD per metric ton | / 1,000 | World Bank, IMF, USGS sulfur and fluorspar |
| US cents per pound | x 0.01 / 0.45359237 = x 0.0220462 | USGS silicon, copper, aluminium |
| USD per short ton | / 907.18474 | USGS ammonia |
| USD per metric ton unit (mtu) of WO3 | / 10 (per kg of WO3 **content**) | USGS tungsten (not comparable with gross kg, see D05) |
| EUR per 100 kg (Comext) | value / (quantity x 100) | Comext |

- **Gases** are standardised on kg. The m3 supplementary quantity is kept only to check the kg
  (QC08: helium weighs about 0.18 kg/m3, neon 0.90 kg/m3 at 0 C and 1 atm).
- **Purity / grade** is a property of the material definition (`purity_or_grade`), not of a row.
  When a code mixes grades (polysilicon), the mix is tracked by origin, not hidden.

## 3. Currency
- Monthly series: ECB reference rate, monthly average (`EXR.M.USD.EUR.SP00.A`).
- Annual series: calendar-year mean of the monthly rates (`fx_annual`).
- EUR is the reporting currency of the tracker; USD is kept for comparison with USD sources.

## 4. Delivery terms (valuation)
- EU **imports** are valued **CIF** at the EU border (cost, insurance, freight); **exports FOB**.
- Exchange prices are LME cash (warehouse) prices; USGS prices are US market prices.
- A CIF value is expected to sit **above** a FOB or warehouse price. The expected gap is written
  as a band in `seeds/reconciliation_pairs.csv`, so a normal CIF premium never raises an alert.

## 5. Territory and partners
- **EU27_2020** for the whole history. The Comext `EU` reporter includes the United Kingdom until
  January 2020, which shifts extra-EU totals by up to 58% for polysilicon (card D13).
- Comext imports record the **country of origin**; UN Comtrade exports record the **country of
  destination**. Bilateral mirror comparisons must take this into account (card D08).
- Partner codes starting with `Q` are confidential / not specified. They stay in the totals and
  appear as `Confidential` in origin analyses (QC09, card D12).

## 6. Nomenclatures
- CN8 codes change on 1 January. The concordance lists every code with `valid_from` / `valid_to`.
  A code is used only inside its window (QC06) and split codes are **summed**, never chained.
- Real changes in the period: aluminium `76011000` -> `76011010 + 76011090` (2023-01-01);
  doped wafers `38180010` -> `38180011` (photovoltaic) + `38180019` (2026-01-01). QC05 measures
  the unit-value jump across each break.
- HS6 (Comtrade) is coarser than CN8: `811292` mixes gallium, germanium, indium, niobium, vanadium,
  hafnium and rhenium; `280429` mixes helium, neon, krypton and xenon.

## 7. Validated series
- The **published** extra-EU unit value is kept (`eu_import_uv_raw_eur_kg`).
- The **validated** unit value (`eu_import_uv_eur_kg`) sums partner flows that pass the plausible
  price range of the material (QC14). Months flagged as robust outliers (QC03) or thin trade (QC04)
  are blanked in `eu_import_uv_clean_eur_kg`, used by the nowcast.
- `eu_import_uv3_eur_kg` = 3-month weighted unit value (sum of values / sum of kg), used for trends.

## 8. Naming and files
- Layers: `data/raw` (as downloaded, dated) -> `data/clean` (standard schema + checks) -> `data/marts`.
- Snake case columns, explicit units in names (`_eur_kg`, `_kg`, `_usd`).
- Every published table is a CSV with a header; dates ISO 8601.
