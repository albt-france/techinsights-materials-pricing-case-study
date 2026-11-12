# Discrepancy log

Every gap between sources that matters, written as: **finding -> root cause -> evidence -> correction -> prevention**.
Evidence numbers are recomputed by `python -m pipeline run` (see `pipeline/reconcile.py`); the narrative lives in `seeds/discrepancy_register.csv`.
Pair-level gaps and alerts: `data/marts/reconciliation_summary.csv` and the *Reconciliation* sheet of the Excel tracker.

| ID | Discrepancy | Materials | Status |
|---|---|---|---|
| [D01](#d01) | EU import unit values sit above the LME cash price | CU; SN; AL | Explained |
| [D02](#d02) | US market prices are well above EU and LME prices | AL; SI_MET | Explained |
| [D03](#d03) | Gallium 'price' fell 56% between two USGS editions for the same year | GA | Explained |
| [D04](#d04) | EU germanium unit value lags the quoted metal price | GE | Explained |
| [D05](#d05) | Tungsten concentrate cannot be compared per kg | W | Not comparable |
| [D06](#d06) | One customs code holds two different products (polysilicon) | POLYSI | Explained |
| [D07](#d07) | Germany's polysilicon exports to China vs China's imports from Germany | POLYSI | Partly explained |
| [D08](#d08) | Germany imports far more Chinese gallium/germanium/indium than China says it exports to Germany | GA; GE; IN | Explained |
| [D09](#d09) | Germany reports twice the wafer weight that Japan reports | WAFER | Open |
| [D10](#d10) | Latest-year USGS values are revised in the next edition | ALL | Explained |
| [D11](#d11) | Published neon/krypton/xenon unit value is polluted by implausible flows | NE | Corrected |
| [D12](#d12) | A third of EU helium imports have a confidential origin | HE | Explained |
| [D13](#d13) | 'EU' totals before 2020 do not match EU27 totals | POLYSI; CU | Corrected |
| [D14](#d14) | Helium weight and volume do not match physics | HE | Partly explained |

## D01
**EU import unit values sit above the LME cash price** (CU; SN; AL) - status: *Explained*

- **Root cause:** Valuation basis. Comext imports are valued CIF at the EU border (freight, insurance and the regional physical premium are included). LME cash is an exchange price for metal in LME warehouses. Aluminium carries the largest premium (EU duty-unpaid premium). Contracts are often priced on the previous month's average, which adds a timing gap in fast markets.
- **Evidence:** Copper: median gap +1% (band -3% to +6%), 8 alert months out of 104; Tin: median gap +0% (band -6% to +8%), 26 alert months out of 104; Aluminium: median gap +9% (band +0% to +20%), 20 alert months out of 104. Control: World Bank vs IMF copper median gap +0%, so the benchmarks agree and the gap is in the EU valuation.
- **Correction:** Compare against the benchmark with the expected premium band, not against zero. Use the 3-month weighted unit value in fast markets.
- **Prevention:** Expected band per pair in seeds/reconciliation_pairs.csv; an alert is raised only when the gap leaves the band.

## D02
**US market prices are well above EU and LME prices** (AL; SI_MET) - status: *Explained*

- **Root cause:** Market scope. USGS prices for aluminium and silicon metal are US market prices. They include US-specific trade measures: the Section 232 tariff on aluminium (25% from 2025-03-12, 50% from 2025-06-04) and anti-dumping / countervailing duty orders on silicon metal from several origins.
- **Evidence:** US aluminium spot vs LME: gap +18% to +51%, latest year +51%. EU silicon metal import unit value vs US market price: median -33%.
- **Correction:** Never mix a US market price with an EU border or LME price in one series. Keep the US series as a separate, labelled market.
- **Prevention:** 'valuation' and 'reporter' (market) are mandatory columns of the standard schema; pairs across markets carry a wide band.

## D03
**Gallium 'price' fell 56% between two USGS editions for the same year** (GA) - status: *Explained*

- **Root cause:** Definition change, not a market move. MCS2025 published a high-purity gallium price; MCS2026 publishes the average unit value of US imports for the same years.
- **Evidence:** Same years, two editions: 2021: 625 -> 277 USD/kg (-56%); 2022: 560 -> 432 USD/kg (-23%); 2023: 450 -> 365 USD/kg (-19%); 2024: 500 -> 439 USD/kg (-12%). After aligning definitions, EU vs US import unit value median gap is -25%.
- **Correction:** Treat the two editions as two different series; reconcile Comext against the MCS2026 import unit value (same concept).
- **Prevention:** Store the full definition text with every series and edition; a changed definition text opens a new series instead of overwriting the old one.

## D04
**EU germanium unit value lags the quoted metal price** (GE) - status: *Explained*

- **Root cause:** Timing and mix. Customs values follow contract prices agreed earlier, while the quoted price reacts at once; EU imports also mix powders and lower purities. USGS 2025 is an estimate made before year end.
- **Evidence:** EU import unit value vs USGS metal price (USD/kg): 2023: 1,260 vs 1,392; 2024: 1,593 vs 1,991; 2025: 2,265 vs 4,100.
- **Correction:** Read the gap with a lag; flag the latest USGS year as provisional.
- **Prevention:** QC10 / provisional flag on estimated values; nowcast uses the validated EU series only.

## D05
**Tungsten concentrate cannot be compared per kg** (W) - status: *Not comparable*

- **Root cause:** Content basis. USGS quotes per metric ton unit of WO3 content (10 kg of WO3); Comext records the gross weight of ores and concentrates of very different grades. The ratio of the two implies a WO3 content that swings from a few percent to more than half.
- **Evidence:** EU unit value per kg of concentrate divided by the USGS price per kg of WO3 ranges from 4% to 68% (implied WO3 content), far outside a physical 50-75% range for a single concentrate grade.
- **Correction:** Do not use the EU unit value as a tungsten price; keep it for volumes only.
- **Prevention:** comparison_basis = 'content_basis' in the data standard: such pairs never raise a price alert.

## D06
**One customs code holds two different products (polysilicon)** (POLYSI) - status: *Explained*

- **Root cause:** Product mix. CN 28046100 covers every silicon >= 99.99%, from solar-grade to electronic-grade. EU imports from the United States are priced like electronic grade while imports from China are priced like solar grade; the average moves with the origin mix, not with prices.
- **Evidence:** EU import unit value by origin (EUR/kg, tonnes): 2022 CN: 35.6 EUR/kg on 237 t; 2022 US: 32.2 EUR/kg on 4,775 t; 2025 CN: 2.4 EUR/kg on 7,272 t; 2025 US: 41.9 EUR/kg on 2,190 t.
- **Correction:** Track an origin-stratified unit value (US-origin as an electronic-grade proxy) next to the all-origin average.
- **Prevention:** Mix check: compare the all-origin unit value with a fixed-origin-weight version every month.

## D07
**Germany's polysilicon exports to China vs China's imports from Germany** (POLYSI) - status: *Partly explained*

- **Root cause:** Mirror statistics. Germany values exports FOB, China values imports CIF, so China's figure should be a few percent higher. Larger gaps come from timing (shipments recorded in different years) during the 2023 price collapse.
- **Evidence:** Value gap (DE exports FOB / CN imports CIF - 1): median -7%, range -34% to +14%, 3 alert years.
- **Correction:** Use a CIF/FOB band for mirror pairs; investigate only gaps outside it.
- **Prevention:** Mirror check with an expected band, run on every annual refresh.

## D08
**Germany imports far more Chinese gallium/germanium/indium than China says it exports to Germany** (GA; GE; IN) - status: *Explained*

- **Root cause:** Partner definition. The EU records imports by country of ORIGIN; China records exports by country of DESTINATION. Chinese-origin metal bought through traders and shipped from third countries counts as 'China' in Germany's data but not as 'Germany' in China's data.
- **Evidence:** Germany's reported value is 1.7x to 30.3x China's mirror figure (median 3.9x).
- **Correction:** Do not reconcile small high-value metals on bilateral mirror flows; reconcile on world totals and unit values.
- **Prevention:** Partner definition documented per source in DATA_STANDARDS.md.

## D09
**Germany reports twice the wafer weight that Japan reports** (WAFER) - status: *Open*

- **Root cause:** Open. Values agree within the CIF/FOB band but the net weights do not. Hypotheses: different quantity basis (carriers or packaging counted in one source), or weight estimated by one declarant.
- **Evidence:** Net kg reported by Germany vs Japan: 2.1x to 2.7x, while the value gap stays between +15% and +53%.
- **Correction:** Reconcile wafers on value, not on kg; do not publish a per-kg wafer price from mirror data.
- **Prevention:** Value gap and kg gap are checked separately; escalate kg gaps above 25% to the source (Destatis / Japan Customs).

## D10
**Latest-year USGS values are revised in the next edition** (ALL) - status: *Explained*

- **Root cause:** Revisions. The latest year of each edition is an estimate and is revised one year later (several percent for silicon, sulfur, germanium and indium).
- **Evidence:** 2024 values, MCS2026 vs MCS2025: SULFUR -7.2%; SI_METAL -5.4%; GE_METAL -5.2%; FLUORSPAR_ACID -1.3%; CU_LME -1.3%; AL_SPOT -0.4%; W_CONC +0.8%; IN_ROTTERDAM +3.7%.
- **Correction:** Always load the latest edition; flag the last year as provisional.
- **Prevention:** Keep every edition as a dated snapshot and recompute the revision table at each refresh.

## D11
**Published neon/krypton/xenon unit value is polluted by implausible flows** (NE) - status: *Corrected*

- **Root cause:** Misclassification or wrong quantity in customs declarations: hundreds of tonnes declared under CN 28042990 at about EUR 2/kg, a value impossible for neon, krypton or xenon.
- **Evidence:** Largest excluded flows: 2024 CH: 2,473 t at 1.36 EUR/kg; 2022 CH: 814 t at 1.77 EUR/kg; 2021 CH: 769 t at 0.90 EUR/kg. Published vs validated unit value: median gap -75%, 70 months outside +/-25%.
- **Correction:** Exclude partner flows outside the plausible price range (QC14) and publish the validated series.
- **Prevention:** Plausible price range per material in seeds/materials.csv; QC14 runs on every refresh.

## D12
**A third of EU helium imports have a confidential origin** (HE) - status: *Explained*

- **Root cause:** Confidentiality. Comext books the trade of some declarants under 'secret' or 'not specified' partner codes.
- **Evidence:** Confidential partner share of EU helium imports, 2018-latest: 31% of value; 100 months above 10%.
- **Correction:** Report 'Confidential' as its own origin instead of spreading it over named countries.
- **Prevention:** QC09 alerts when the confidential share is above 10%.

## D13
**'EU' totals before 2020 do not match EU27 totals** (POLYSI; CU) - status: *Corrected*

- **Root cause:** Coverage. The Comext 'EU' reporter includes the United Kingdom until January 2020; flows between the UK and non-EU countries are counted as extra-EU before Brexit and UK-EU flows as intra-EU.
- **Evidence:** Polysilicon extra-EU imports, 'EU' vs EU27_2020 before February 2020: median gap +25% (range +12% to +58%).
- **Correction:** Use the fixed composition EU27_2020 for the whole history.
- **Prevention:** Reporter code fixed in the data standard; composition check kept in the pipeline.

## D14
**Helium weight and volume do not match physics** (HE) - status: *Partly explained*

- **Root cause:** Units. The kg reported per m3 is about 60% above the density of helium gas at standard conditions: m3 may be declared at other conditions, or part of the declared mass may not be helium.
- **Evidence:** Median implied density of EU helium imports: 0.286 kg/m3 vs 0.179 kg/m3 for helium at 0 C and 1 atm (+60%).
- **Correction:** Use kg as the standard unit; keep m3 only as a check.
- **Prevention:** QC08 compares the two quantities every month.
