# Runbook - monthly update and what to do when a check fails

Written so that a colleague can run and maintain the tracker without me.

## 1. Monthly update (about 20 minutes)

Eurostat publishes month *M* around the middle of month *M+2*; the World Bank Pink Sheet comes out
in the first days of each month; USGS once a year (late January / February).

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt     # first time only
.venv\Scripts\python -m pipeline run              # extract + rebuild everything (~3 min)
```

1. Read the last line of the run: number of error-level check rows and failed extractions.
2. Open `docs/QUALITY_REPORT.md`: freshness table first, then the checks table.
3. Open `docs/DISCREPANCY_LOG.md` and `data/marts/reconciliation_summary.csv`: any new `ALERT`?
4. Open `excel/Semiconductor_Materials_Price_Tracker.xlsx` and click **Data > Refresh All**.
5. Optional: rebuild the workbook and the report
   (`python src/build_excel.py`, `python src/check_excel.py`, `python src/build_report.py`).
6. Commit the refreshed `data/clean`, `data/marts` and `docs` with a message such as
   `data: refresh to Comext 2026-09`.

No key is needed. A free UN Comtrade key (`COMTRADE_KEY=...` in a local `.env`, never committed)
only lifts the preview limits.

## 2. When a check fails

| Check | What it means | What to do |
|---|---|---|
| QC01 Missing month | A material has no extra-EU import record for a month | Check the Comext release calendar. If the month is published for other codes, the trade may be zero or confidential: look at the HS6 total. Leave the month empty; the nowcast interpolates it. |
| QC02 Value without quantity | A partner flow has a value but no kg | Usually tiny flows. Excluded automatically from the validated series; no action unless the value is material. |
| QC03 Unit-value outlier | A month is > 3.5 robust z and > 25% away from its 13-month median | Look at the partner breakdown (`data/marts/origin_monthly.csv`) for that month. One partner with a strange price? Check its quantity. Real market move (event)? Keep it and add the event to `seeds/events.csv`. |
| QC04 Thin trade | Quantity below 10% of the usual monthly quantity | Read the unit value with care; the nowcast ignores the month. |
| QC05 Nomenclature change | A CN8 code was split or replaced | Check the new year's CN (Official Journal) and update `seeds/code_concordance.csv` (close `valid_to`, add new codes with `valid_from`). Then re-run. |
| QC06 Code outside validity | A code reports data outside its window | The concordance is wrong or Eurostat revised history: fix the dates in the concordance. |
| QC07 Duplicate | Same key twice in staging | An extraction ran twice into one file or the API changed format: delete `data/raw/comext/` and re-run. |
| QC08 kg vs m3 | Gas weight and volume disagree | Note it; kg stays the standard. Repeated in the same partner: report to Eurostat user support. |
| QC09 Confidential partner | > 10% of the value has no disclosed origin | Expected for helium (card D12). For a new material, report the share in origin charts. |
| QC10 Withheld value | A USGS cell is 'W' | Keep empty; use the previous edition only as a labelled fallback. |
| QC11 Stale source | A source is older than its normal lag | Check the publisher's site; if the URL changed (World Bank yearly folder), update the extractor constant. The run continues with the last snapshot. |
| QC12 Missing FX | No ECB rate for a month | The ECB monthly average is published at month end; re-run the next day. |
| QC13 Estimated quantity | Comtrade estimated the net weight | Treat Comtrade unit values for that year as indicative. |
| QC14 Implausible flow | A partner-month price is outside the plausible range of the material | Excluded from the validated series. If the same partner repeats, add a discrepancy card. If the market truly moved outside the range, widen the range in `seeds/materials.csv` and document why. |

## 3. When a source changes format

1. The run prints `!! <source> extraction failed` and continues on the last snapshot.
2. Open the extractor (`pipeline/extract_<source>.py`); every one is short and saves the raw answer.
3. Compare the new raw file with the last good snapshot (git diff on `data/raw/<source>`).
4. Adapt only the parser in `pipeline/standardize.py`; the standard schema does not change.
5. Re-run and compare `data/marts/monthly_prices.csv` with the previous version: values for past
   months should not move except for documented revisions.

## 4. When two sources disagree (new alert)

1. Find the pair in `data/marts/reconciliation_summary.csv` and its monthly detail in
   `reconciliation_detail.csv` (or the *Reconciliation* sheet, pair explorer).
2. Go through the usual causes in this order: valuation (CIF/FOB), market/territory, currency and
   timing, definition or edition change, product mix, partner definition, revision.
3. Write a card in `seeds/discrepancy_register.csv` (root cause, correction, prevention, status),
   add a pair or adjust the band in `seeds/reconciliation_pairs.csv` if justified, re-run.
   The evidence in `docs/DISCREPANCY_LOG.md` is recomputed automatically.

## 5. Yearly tasks
- January: new CN nomenclature -> concordance; new World Bank folder -> `extract_worldbank.py` constant.
- February: new USGS edition -> add the edition in `extract_usgs.py`; the revision table shows what changed.
- Review the plausible ranges and expected bands with the latest year of data.
