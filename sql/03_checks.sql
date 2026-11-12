-- 03_checks.sql --------------------------------------------------------------
-- Data quality checks. Each check writes rows to quality_checks:
--   check_id, check_name, severity (error / warn / info), material_id, series_id, period, value, detail
-- A row means "something to look at"; docs/RUNBOOK.md says what to do for each check_id.

CREATE OR REPLACE TABLE quality_checks (
    check_id VARCHAR, check_name VARCHAR, severity VARCHAR, material_id VARCHAR,
    series_id VARCHAR, period DATE, value DOUBLE, detail VARCHAR);

-- QC14 Implausible partner flow: a partner-month whose unit value is outside the plausible
-- range of the material (seeds/materials.csv). Typical cause: wrong CN code or wrong quantity
-- in the customs declaration. These rows are EXCLUDED from the validated series below.
CREATE OR REPLACE TABLE partner_rows AS
SELECT c.period, c.material_id, c.flow, c.partner, sum(c.value_eur) AS value_eur, sum(c.quantity_kg) AS quantity_kg,
       sum(c.value_eur) / nullif(sum(c.quantity_kg), 0) AS uv,
       any_value(CAST(m.plausible_min_eur_kg AS DOUBLE)) AS lo, any_value(CAST(m.plausible_max_eur_kg AS DOUBLE)) AS hi
FROM stg_comext_cn8 c JOIN materials m USING (material_id)
WHERE length(c.partner) = 2
  AND c.partner NOT IN ('AT','BE','BG','CY','CZ','DE','DK','EE','ES','FI','FR','GR','HR','HU','IE','IT','LT','LU','LV','MT','NL','PL','PT','RO','SE','SI','SK')
GROUP BY c.period, c.material_id, c.flow, c.partner;

INSERT INTO quality_checks
SELECT 'QC14', 'Implausible partner flow (excluded)', 'warn', material_id, 'COMEXT_' || upper(left(flow, 3)) || '_' || material_id,
       period, round(uv, 2),
       'partner ' || partner || ': ' || round(quantity_kg) || ' kg at ' || round(uv, 2) || ' EUR/kg, outside ' || lo || '-' || hi || ' EUR/kg'
FROM partner_rows WHERE quantity_kg > 0 AND (uv < lo OR uv > hi);

-- Validated monthly series = partner rows that passed QC14 (rows without kg are dropped too,
-- because they would add value without quantity)
CREATE OR REPLACE TABLE comext_validated AS
SELECT period, material_id, flow, sum(value_eur) AS value_eur, sum(quantity_kg) AS quantity_kg,
       sum(value_eur) / nullif(sum(quantity_kg), 0) AS uv
FROM partner_rows WHERE quantity_kg > 0 AND uv BETWEEN lo AND hi
GROUP BY ALL;

-- Monthly Comext import series used by the checks below (validated version)
CREATE OR REPLACE TEMP TABLE imp AS
SELECT period, material_id, 'COMEXT_IMP_' || material_id AS series_id, uv, quantity_kg, value_eur
FROM comext_validated WHERE flow = 'import';

-- QC01 Missing months: every month between 2018-01 and the latest Comext month must exist
INSERT INTO quality_checks
SELECT 'QC01', 'Missing month', 'error', m.material_id, 'COMEXT_IMP_' || m.material_id, g.period, NULL,
       'No extra-EU import record for this month'
FROM materials m
CROSS JOIN (SELECT CAST(range AS DATE) AS period
            FROM range(DATE '2018-01-01', (SELECT max(period) FROM imp) + INTERVAL 1 MONTH, INTERVAL 1 MONTH)) g
LEFT JOIN imp i ON i.material_id = m.material_id AND i.period = g.period
WHERE i.period IS NULL;

-- QC02 Positive value with zero or missing quantity (unit value impossible)
INSERT INTO quality_checks
SELECT 'QC02', 'Value without quantity', 'warn', material_id, product_code, period, value_eur,
       'partner ' || partner || ', flow ' || flow || ': value > 0 but quantity = 0 or missing'
FROM stg_comext
WHERE value_eur > 0 AND coalesce(quantity_kg, 0) = 0 AND product_level = 'CN8';

-- QC03 Unit-value outliers, robust method: distance to a centred 13-month rolling median of
-- log(unit value), scaled by the median absolute deviation (MAD) of the material.
-- Modified z-score = 0.6745 * deviation / MAD, flagged when |z| > 3.5 (Iglewicz & Hoaglin).
CREATE OR REPLACE TABLE uv_robust AS
WITH r AS (
    SELECT *, ln(uv) - median(ln(uv)) OVER (PARTITION BY material_id ORDER BY period
                                           ROWS BETWEEN 6 PRECEDING AND 6 FOLLOWING) AS dev
    FROM imp WHERE uv > 0
), m AS (
    SELECT material_id, median(abs(dev)) AS mad FROM r GROUP BY 1
)
SELECT r.*, m.mad, 0.6745 * r.dev / nullif(m.mad, 0) AS robust_z FROM r JOIN m USING (material_id);

-- A materiality threshold (25%) is added: for smooth exchange-traded metals the MAD is so
-- small that an ordinary 8% monthly move would otherwise be flagged.
INSERT INTO quality_checks
SELECT 'QC03', 'Unit-value outlier', 'warn', material_id, series_id, period, round(robust_z, 1),
       'unit value ' || round(uv, 2) || ' EUR/kg is ' || round(100 * (exp(dev) - 1)) || '% away from its 13-month median'
FROM uv_robust WHERE abs(robust_z) > 3.5 AND abs(exp(dev) - 1) > 0.25;

-- QC04 Thin trade: quantity below 10% of the material's median monthly quantity
-- (a few small shipments make the unit value unreliable)
INSERT INTO quality_checks
SELECT 'QC04', 'Thin trade month', 'info', i.material_id, i.series_id, i.period, i.quantity_kg,
       'quantity ' || round(i.quantity_kg) || ' kg vs median ' || round(q.med) || ' kg'
FROM imp i JOIN (SELECT material_id, median(quantity_kg) AS med FROM imp GROUP BY 1) q USING (material_id)
WHERE i.quantity_kg < 0.10 * q.med;

-- QC05 Nomenclature break: a CN8 code is split or replaced (concordance valid_to / valid_from).
-- The level shift of the unit value across the break is measured (6 months before vs after).
INSERT INTO quality_checks
SELECT 'QC05', 'Nomenclature change', 'info', k.material_id, 'COMEXT_IMP_' || k.material_id,
       CAST(k.valid_from || '-01' AS DATE),
       round(100 * (after.uv / before.uv - 1), 1),
       'new code ' || k.cn8_code || ' from ' || k.valid_from || '; unit value change across the break (%) in value column'
FROM concordance k
JOIN LATERAL (SELECT sum(value_eur) / sum(quantity_kg) AS uv FROM imp
              WHERE imp.material_id = k.material_id
                AND imp.period >= CAST(k.valid_from || '-01' AS DATE) - INTERVAL 6 MONTH
                AND imp.period <  CAST(k.valid_from || '-01' AS DATE)) before ON true
JOIN LATERAL (SELECT sum(value_eur) / sum(quantity_kg) AS uv FROM imp
              WHERE imp.material_id = k.material_id
                AND imp.period >= CAST(k.valid_from || '-01' AS DATE)
                AND imp.period <  CAST(k.valid_from || '-01' AS DATE) + INTERVAL 6 MONTH) after ON true
WHERE k.valid_from > '2018-01';

-- QC06 Code used outside its validity window (would double count or mix scopes)
INSERT INTO quality_checks
SELECT 'QC06', 'Code outside validity window', 'error', c.material_id, c.product_code, c.period, c.value_eur,
       'CN8 ' || c.product_code || ' reported outside ' || k.valid_from || ' .. ' || coalesce(k.valid_to, 'open')
FROM stg_comext c JOIN concordance k ON k.material_id = c.material_id AND k.cn8_code = c.product_code
WHERE c.partner = 'EXT_EU27_2020'
  AND (strftime(c.period, '%Y-%m') < k.valid_from OR strftime(c.period, '%Y-%m') > coalesce(k.valid_to, '9999-12'));

-- QC07 Duplicate keys in staging
INSERT INTO quality_checks
SELECT 'QC07', 'Duplicate record', 'error', material_id, product_code, period, count(*),
       'same period/reporter/partner/product/flow appears ' || count(*) || ' times'
FROM stg_comext GROUP BY material_id, product_code, period, reporter, partner, flow HAVING count(*) > 1;

-- QC08 Unit consistency for gases: kg per m3 implied by the two quantity columns.
-- Helium weighs ~0.18 kg/m3 and neon ~0.90 kg/m3 at standard conditions; a ratio far
-- from the material's own median means one of the two quantities is wrong or mixed.
CREATE OR REPLACE TABLE gas_density AS
SELECT period, material_id, quantity_kg / nullif(quantity_supp, 0) AS kg_per_m3
FROM observations WHERE source = 'COMEXT' AND flow = 'import' AND material_id IN ('HE', 'NE');

INSERT INTO quality_checks
SELECT 'QC08', 'Inconsistent units (kg vs m3)', 'warn', g.material_id, 'COMEXT_IMP_' || g.material_id, g.period,
       round(g.kg_per_m3, 3),
       'implied ' || round(g.kg_per_m3, 3) || ' kg/m3 vs median ' || round(d.med, 3)
FROM gas_density g JOIN (SELECT material_id, median(kg_per_m3) AS med FROM gas_density GROUP BY 1) d USING (material_id)
WHERE g.kg_per_m3 > 3 * d.med OR g.kg_per_m3 < d.med / 3 OR g.kg_per_m3 IS NULL;

-- QC09 Confidential partner: Comext books trade whose country is secret or not specified
-- under partner codes starting with 'Q' (e.g. QY 'secret countries', QZ 'not specified').
-- Share of the extra-EU value that has no disclosed partner country, per material and month.
CREATE OR REPLACE TABLE confidential_share AS
WITH t AS (SELECT period, material_id, flow, sum(value_eur) AS extra_value FROM stg_comext_cn8
           WHERE partner = 'EXT_EU27_2020' GROUP BY ALL),
     q AS (SELECT period, material_id, flow, sum(value_eur) AS hidden_value FROM stg_comext_cn8
           WHERE partner LIKE 'Q%' GROUP BY ALL)
SELECT t.*, coalesce(q.hidden_value, 0) AS hidden_value,
       coalesce(q.hidden_value, 0) / nullif(t.extra_value, 0) AS hidden_share
FROM t LEFT JOIN q USING (period, material_id, flow);

INSERT INTO quality_checks
SELECT 'QC09', 'Partner country not disclosed', 'info', material_id, 'COMEXT_' || upper(left(flow, 3)) || '_' || material_id,
       period, round(100 * hidden_share, 1), round(100 * hidden_share, 1) || '% of the extra-EU value has a confidential partner'
FROM confidential_share WHERE hidden_share > 0.10;

-- QC10 Withheld values in USGS tables ('W' = withheld to avoid disclosing company data)
INSERT INTO quality_checks
SELECT 'QC10', 'Withheld or missing reference value', 'info', s.material_id, u.series_id, make_date(u.year, 1, 1), NULL,
       u.edition || ' ' || u.year || ': raw cell = ' || coalesce(u.raw_value, 'empty')
FROM stg_usgs u JOIN usgs_series s USING (series_id)
WHERE u.value_native IS NULL;

-- QC11 Freshness: months between the latest observation and the collection date,
-- compared with the normal publication lag of the source.
CREATE OR REPLACE TABLE freshness AS
SELECT source, max(period) AS latest_period, any_value(collected_on) AS collected_on,
       date_diff('month', max(period), CAST(any_value(collected_on) AS DATE)) AS lag_months,
       CASE source WHEN 'COMEXT' THEN 3 WHEN 'WORLDBANK' THEN 2 WHEN 'IMF' THEN 3
                   WHEN 'BLS' THEN 3 WHEN 'USGS' THEN 23 WHEN 'COMTRADE' THEN 23 END AS expected_max_lag
FROM observations WHERE collected_on <> 'unknown' GROUP BY source;

INSERT INTO quality_checks
SELECT 'QC11', 'Stale source', CASE WHEN lag_months > expected_max_lag THEN 'warn' ELSE 'info' END, NULL, source,
       latest_period, lag_months,
       source || ': latest ' || strftime(latest_period, '%Y-%m') || ', ' || lag_months || ' months before collection (normal <= ' || expected_max_lag || ')'
FROM freshness;

-- QC12 Every monthly observation needs an exchange rate
INSERT INTO quality_checks
SELECT 'QC12', 'Missing FX rate', 'error', material_id, series_id, period, NULL, 'no ECB USD/EUR rate for this month'
FROM observations WHERE frequency = 'M' AND usd_per_eur IS NULL AND source <> 'BLS';

-- QC13 Comtrade net weight estimated by the UN (not reported by the country)
INSERT INTO quality_checks
SELECT 'QC13', 'Estimated quantity (Comtrade)', 'info', NULL, 'COMTRADE_' || reporter || '_' || flow || '_' || partner || '_' || hs6,
       make_date(year, 1, 1), net_kg, 'net weight estimated by UN Comtrade, unit value less reliable'
FROM stg_comtrade WHERE lower(kg_estimated) = 'true';

-- Summary used by the report and the Excel 'Quality checks' sheet
CREATE OR REPLACE TABLE quality_summary AS
SELECT check_id, check_name, severity, count(*) AS rows_flagged,
       count(DISTINCT material_id) AS materials_affected
FROM quality_checks GROUP BY ALL ORDER BY check_id;
