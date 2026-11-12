-- 02_observations.sql --------------------------------------------------------
-- The STANDARD SCHEMA: one row = one observation of one series, whatever the source.
-- Every price is also expressed in EUR/kg and USD/kg so that sources can be compared.
-- See docs/DATA_STANDARDS.md for the definition of each column.

CREATE OR REPLACE TABLE observations AS

-- 1. Comext extra-EU imports (CIF) and exports (FOB), CN8 codes summed per material
WITH comext AS (
    SELECT period, material_id, flow,
           string_agg(DISTINCT product_code, '+' ORDER BY product_code) AS product_code,
           sum(value_eur) AS value_eur, sum(quantity_kg) AS quantity_kg, sum(quantity_supp) AS quantity_supp
    FROM stg_comext_cn8
    WHERE partner = 'EXT_EU27_2020'
    GROUP BY ALL
)
SELECT c.period, 'M' AS frequency, c.material_id, 'COMEXT' AS source,
       'COMEXT_' || CASE c.flow WHEN 'import' THEN 'IMP' ELSE 'EXP' END || '_' || c.material_id AS series_id,
       c.flow, 'EU27_2020' AS reporter, 'EXTRA_EU' AS partner,
       CASE c.flow WHEN 'import' THEN 'CIF' ELSE 'FOB' END AS valuation,
       c.product_code, 'CN8' AS nomenclature,
       c.value_eur AS value_native, 'EUR' AS currency, c.quantity_kg, c.quantity_supp,
       CASE WHEN c.material_id IN ('HE', 'NE') THEN 'm3' END AS supp_unit,
       c.value_eur / nullif(c.quantity_kg, 0) AS price_native, 'EUR/kg' AS price_unit_native,
       f.usd_per_eur,
       c.value_eur / nullif(c.quantity_kg, 0) AS price_eur_kg,
       c.value_eur / nullif(c.quantity_kg, 0) * f.usd_per_eur AS price_usd_kg
FROM comext c LEFT JOIN fx f USING (period)

UNION ALL
-- 2. World Bank Pink Sheet and IMF benchmark prices (USD per metric ton, monthly averages)
SELECT b.period, 'M', s.material_id, s.source, b.series_id, 'price', 'GLOBAL', NULL, s.valuation,
       NULL, NULL, NULL, 'USD', NULL, NULL, NULL,
       b.value, s.native_unit, f.usd_per_eur,
       b.value / 1000 / f.usd_per_eur, b.value / 1000
FROM (SELECT * FROM stg_worldbank UNION ALL SELECT * FROM stg_fred) b
JOIN series_catalog s ON s.series_id = b.series_id AND s.source IN ('WORLDBANK', 'IMF')
LEFT JOIN fx f USING (period)
WHERE b.period >= DATE '2018-01-01'

UNION ALL
-- 3. BLS producer price indexes (no unit price: index level only)
SELECT b.period, 'M', NULL, 'BLS', b.series_id, 'index', 'US', NULL, 'Producer price index',
       NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       b.value, 'index', NULL, NULL, NULL
FROM stg_fred b JOIN series_catalog s ON s.series_id = b.series_id AND s.source = 'BLS'
WHERE b.period >= DATE '2018-01-01'

UNION ALL
-- 4. USGS annual reference prices, latest edition (MCS2026). Converted with the yearly average FX.
SELECT make_date(u.year, 1, 1), 'A', s.material_id, 'USGS', u.series_id, 'price', 'US', NULL, s.comparison_basis,
       NULL, NULL, NULL, 'USD', NULL, NULL, NULL,
       u.value_native, s.native_unit, fa.usd_per_eur,
       u.value_native * CAST(s.usd_per_kg_factor AS DOUBLE) / fa.usd_per_eur,
       u.value_native * CAST(s.usd_per_kg_factor AS DOUBLE)
FROM stg_usgs u JOIN usgs_series s USING (series_id)
LEFT JOIN fx_annual fa ON fa.year = u.year
WHERE u.edition = 'MCS2026'

UNION ALL
-- 5. UN Comtrade annual unit values (HS6: several materials can share one heading)
SELECT make_date(t.year, 1, 1), 'A',
       (SELECT string_agg(material_id, '+' ORDER BY material_id) FROM materials m WHERE m.hs6 = t.hs6),
       'COMTRADE', 'COMTRADE_' || t.reporter || '_' || t.flow || '_' || t.partner || '_' || t.hs6,
       t.flow, t.reporter, t.partner, CASE t.flow WHEN 'import' THEN 'CIF' ELSE 'FOB' END,
       t.hs6, 'HS6', t.value_usd, 'USD', t.net_kg, NULL, NULL,
       t.value_usd / nullif(t.net_kg, 0), 'USD/kg', fa.usd_per_eur,
       t.value_usd / nullif(t.net_kg, 0) / fa.usd_per_eur, t.value_usd / nullif(t.net_kg, 0)
FROM stg_comtrade t LEFT JOIN fx_annual fa ON fa.year = t.year;

-- collection date of each observation (one per source and refresh)
ALTER TABLE observations ADD COLUMN collected_on VARCHAR;
UPDATE observations o SET collected_on = c.collected_on FROM collected c WHERE c.source = o.source;
