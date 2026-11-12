-- 04_marts.sql ---------------------------------------------------------------
-- Final tables read by the Excel tracker, the report and the reconciliation step.

-- 1. Monthly tracker: one row per material and month ------------------------
CREATE OR REPLACE TABLE mart_monthly_prices AS
WITH imp AS (SELECT v.period, v.material_id, v.value_eur AS value_native, v.quantity_kg,
                    v.uv AS price_eur_kg, v.uv * f.usd_per_eur AS price_usd_kg, f.usd_per_eur,
                    o.price_eur_kg AS raw_price_eur_kg
             FROM comext_validated v LEFT JOIN fx f USING (period)
             LEFT JOIN observations o ON o.source = 'COMEXT' AND o.flow = 'import'
                                     AND o.material_id = v.material_id AND o.period = v.period
             WHERE v.flow = 'import'),
     exp AS (SELECT period, material_id, uv AS price_eur_kg FROM comext_validated WHERE flow = 'export'),
     wb  AS (SELECT * FROM observations WHERE source = 'WORLDBANK'),
     imf AS (SELECT * FROM observations WHERE source = 'IMF'),
     idx AS (SELECT period, series_id, price_native AS index_value FROM observations WHERE source = 'BLS'),
     flags AS (SELECT material_id, period,
                      bool_or(check_id = 'QC03') AS is_outlier, bool_or(check_id = 'QC04') AS is_thin
               FROM quality_checks WHERE check_id IN ('QC03', 'QC04') GROUP BY ALL)
SELECT i.period, m.material_id, m.material, m.chain_stage, CAST(m.stage_order AS INTEGER) AS stage_order,
       i.value_native AS eu_import_value_eur, i.quantity_kg AS eu_import_kg,
       i.raw_price_eur_kg AS eu_import_uv_raw_eur_kg,           -- as published (extra-EU aggregate)
       i.price_eur_kg AS eu_import_uv_eur_kg, i.price_usd_kg AS eu_import_uv_usd_kg,   -- validated (QC14)
       -- 3-month weighted unit value: sum of values / sum of kg, damps the product-mix noise
       sum(i.value_native) OVER w3 / nullif(sum(i.quantity_kg) OVER w3, 0) AS eu_import_uv3_eur_kg,
       e.price_eur_kg AS eu_export_uv_eur_kg,
       coalesce(f.is_outlier, false) AS is_outlier, coalesce(f.is_thin, false) AS is_thin,
       CASE WHEN coalesce(f.is_outlier, false) OR coalesce(f.is_thin, false) THEN NULL ELSE i.price_eur_kg END AS eu_import_uv_clean_eur_kg,
       wb.price_usd_kg AS wb_price_usd_kg, wb.price_eur_kg AS wb_price_eur_kg,
       imf.price_usd_kg AS imf_price_usd_kg,
       m.index_series, x.index_value,
       i.usd_per_eur
FROM imp i
JOIN materials m USING (material_id)
LEFT JOIN exp e ON e.material_id = i.material_id AND e.period = i.period
LEFT JOIN wb ON wb.material_id = i.material_id AND wb.period = i.period
LEFT JOIN imf ON imf.material_id = i.material_id AND imf.period = i.period
LEFT JOIN idx x ON x.series_id = m.index_series AND x.period = i.period
LEFT JOIN flags f ON f.material_id = i.material_id AND f.period = i.period
WINDOW w3 AS (PARTITION BY i.material_id ORDER BY i.period ROWS BETWEEN 2 PRECEDING AND CURRENT ROW);

-- Fast monthly signals (benchmarks and indexes) that run ahead of Comext: used by the nowcast
CREATE OR REPLACE TABLE mart_fast_signals AS
SELECT period, series_id, source, material_id, coalesce(price_usd_kg, price_native) AS value
FROM observations WHERE source IN ('WORLDBANK', 'IMF', 'BLS') AND period >= DATE '2018-01-01';

-- 2. Where EU imports come from (origin mix), monthly ------------------------
CREATE OR REPLACE TABLE mart_origin_monthly AS
SELECT period, material_id,
       CASE WHEN partner LIKE 'Q%' THEN 'Confidential'
            WHEN partner IN ('CN', 'US', 'UA', 'RU', 'JP', 'KR', 'TW', 'NO', 'GB', 'CH', 'QA', 'DZ', 'CA', 'BR', 'IN', 'TR', 'ZA', 'KZ', 'AU', 'MY', 'SG', 'VN', 'IL', 'BY')
                 THEN partner ELSE 'Other' END AS origin,
       sum(value_eur) AS value_eur, sum(quantity_kg) AS quantity_kg
FROM stg_comext_cn8
WHERE flow = 'import' AND length(partner) = 2
  AND partner NOT IN ('AT','BE','BG','CY','CZ','DE','DK','EE','ES','FI','FR','GR','HR','HU','IE','IT','LT','LU','LV','MT','NL','PL','PT','RO','SE','SI','SK')
GROUP BY ALL;

-- 3. Annual comparison table: one row per material, year and source series --
CREATE OR REPLACE TABLE mart_annual_prices AS
-- Comext validated series: annual unit value = sum of values / sum of kg (weighted by kg)
SELECT year(v.period) AS year, v.material_id, 'COMEXT' AS source,
       'COMEXT_' || CASE v.flow WHEN 'import' THEN 'IMP' ELSE 'EXP' END || '_' || v.material_id AS series_id,
       CASE v.flow WHEN 'import' THEN 'CIF' ELSE 'FOB' END AS valuation,
       sum(v.value_eur) / nullif(sum(v.quantity_kg), 0) AS uv_eur_kg,
       sum(v.value_eur * f.usd_per_eur) / nullif(sum(v.quantity_kg), 0) AS uv_usd_kg,
       NULL AS avg_price_usd_kg, sum(v.quantity_kg) AS quantity_kg, count(*) AS months
FROM comext_validated v LEFT JOIN fx f USING (period)
GROUP BY ALL
UNION ALL
-- exchange benchmarks: simple average of monthly prices
SELECT year(period), material_id, source, series_id, valuation,
       avg(price_eur_kg), avg(price_usd_kg), avg(price_usd_kg), NULL, count(*)
FROM observations WHERE source IN ('WORLDBANK', 'IMF')
GROUP BY ALL
UNION ALL
SELECT year(period), material_id, source, series_id, valuation, price_eur_kg, price_usd_kg, price_usd_kg, quantity_kg, 12
FROM observations WHERE source IN ('USGS', 'COMTRADE');

-- 4. Mirror statistics: the same flow seen by the exporter and by the importer ----
--    Comext (Germany, EUR, CIF for imports / FOB for exports) vs UN Comtrade (partner, USD)
CREATE OR REPLACE TABLE mart_mirror AS
WITH de AS (
    SELECT year(period) AS year, partner, product_code AS hs6, flow,
           sum(value_eur) AS de_value_eur, sum(quantity_kg) AS de_kg
    FROM stg_comext_de_mirror WHERE year(period) BETWEEN 2018 AND 2025 GROUP BY ALL
), pairs AS (
    -- Germany's flow  <->  partner's opposite flow towards Germany (276)
    SELECT 'POLYSI' AS material_id, '280461' AS hs6, 'CN' AS partner, 'export' AS de_flow, '156' AS reporter, 'import' AS partner_flow
    UNION ALL SELECT 'GA+GE+IN', '811292', 'CN', 'import', '156', 'export'
    UNION ALL SELECT 'SI_MET', '280469', 'CN', 'import', '156', 'export'
    UNION ALL SELECT 'HE+NE', '280429', 'CN', 'import', '156', 'export'
    UNION ALL SELECT 'WAFER', '381800', 'JP', 'import', '392', 'export'
)
SELECT p.material_id, p.hs6, de.year, 'DE ' || p.de_flow || 's ' || p.partner AS de_view,
       de.de_value_eur * fa.usd_per_eur AS de_value_usd, de.de_kg,
       t.value_usd AS partner_value_usd, t.net_kg AS partner_kg,
       de.de_value_eur * fa.usd_per_eur / nullif(t.value_usd, 0) - 1 AS value_gap,
       de.de_kg / nullif(t.net_kg, 0) - 1 AS kg_gap,
       CASE p.de_flow WHEN 'import' THEN 'DE import CIF vs partner export FOB' ELSE 'DE export FOB vs partner import CIF' END AS valuation_note
FROM pairs p
JOIN de ON de.hs6 = p.hs6 AND de.partner = p.partner AND de.flow = p.de_flow
JOIN fx_annual fa ON fa.year = de.year
LEFT JOIN stg_comtrade t ON t.reporter = p.reporter AND t.flow = p.partner_flow AND t.partner = '276'
                         AND t.hs6 = p.hs6 AND t.year = de.year;

-- 5. USGS revisions: the same year published in two editions -----------------
CREATE OR REPLACE TABLE mart_usgs_revisions AS
SELECT s.material_id, a.series_id, a.year, a.value_native AS mcs2025, b.value_native AS mcs2026,
       b.value_native / nullif(a.value_native, 0) - 1 AS revision, s.native_unit
FROM stg_usgs a JOIN stg_usgs b ON a.series_id = b.series_id AND a.year = b.year
JOIN usgs_series s ON s.series_id = a.series_id
WHERE a.edition = 'MCS2025' AND b.edition = 'MCS2026';

-- 6. Coverage: EU (changing composition) vs EU27_2020 (fixed) in 2018-2020 -----
CREATE OR REPLACE TABLE mart_composition AS
SELECT period, product_code,
       sum(value_eur) FILTER (WHERE reporter = 'EU' AND partner = 'EXT_EU') AS eu_changing_extra,
       sum(value_eur) FILTER (WHERE reporter = 'EU27_2020' AND partner = 'EXT_EU27_2020') AS eu27_2020_extra
FROM stg_comext_composition GROUP BY ALL;

-- 7. Coverage matrix: which sources exist for which material ---------------------
CREATE OR REPLACE TABLE mart_coverage AS
SELECT m.material_id, m.material, m.chain_stage, CAST(m.stage_order AS INTEGER) AS stage_order,
       'yes' AS comext_monthly,
       CASE WHEN m.hs6 IN (SELECT hs6 FROM stg_comtrade) THEN 'yes (HS6' ||
            CASE WHEN (SELECT count(*) FROM materials m2 WHERE m2.hs6 = m.hs6) > 1 THEN ', shared heading)' ELSE ')' END
            ELSE 'no' END AS comtrade_annual,
       CASE WHEN m.usgs_series IS NOT NULL THEN
            CASE (SELECT comparison_basis FROM usgs_series u WHERE u.series_id = m.usgs_series)
                 WHEN 'feedstock' THEN 'feedstock only' WHEN 'content_basis' THEN 'content basis' ELSE 'yes' END
            ELSE 'no' END AS usgs_annual,
       CASE WHEN m.benchmark_series IS NOT NULL THEN 'yes' ELSE 'no' END AS exchange_benchmark_monthly,
       coalesce(m.index_series, 'none') AS price_index
FROM materials m ORDER BY stage_order, material_id;
