-- 01_staging.sql ------------------------------------------------------------
-- Load the seeds (data standards) and the staging CSVs written by pipeline/standardize.py
-- into typed DuckDB tables. Paths are relative to the project root.

CREATE OR REPLACE TABLE materials AS
SELECT * FROM read_csv('seeds/materials.csv', header = true, all_varchar = true);

CREATE OR REPLACE TABLE concordance AS
SELECT * FROM read_csv('seeds/code_concordance.csv', header = true, all_varchar = true);

CREATE OR REPLACE TABLE series_catalog AS
SELECT * FROM read_csv('seeds/series_catalog.csv', header = true, all_varchar = true);

CREATE OR REPLACE TABLE usgs_series AS
SELECT * FROM read_csv('seeds/usgs_series.csv', header = true, all_varchar = true);

CREATE OR REPLACE TABLE collected AS
SELECT * FROM read_csv('data/clean/stg_collected_on.csv', header = true, all_varchar = true);

-- ECB monthly average USD per EUR, plus a calendar-year average for annual sources
CREATE OR REPLACE TABLE fx AS
SELECT CAST(period AS DATE) AS period, CAST(usd_per_eur AS DOUBLE) AS usd_per_eur
FROM read_csv_auto('data/clean/stg_fx.csv');

CREATE OR REPLACE TABLE fx_annual AS
SELECT year(period) AS year, avg(usd_per_eur) AS usd_per_eur, count(*) AS months
FROM fx GROUP BY 1;

-- Comext: every row of every requested product, all partners, both flows
CREATE OR REPLACE TABLE stg_comext AS
SELECT CAST(period AS DATE) AS period, material_id, reporter, partner, product_code, product_level, flow,
       CAST(value_eur AS DOUBLE) AS value_eur, CAST(quantity_kg AS DOUBLE) AS quantity_kg,
       CAST(quantity_supp AS DOUBLE) AS quantity_supp
FROM read_csv('data/clean/stg_comext.csv', header = true,
              types = {'product_code': 'VARCHAR', 'partner': 'VARCHAR', 'reporter': 'VARCHAR'})
WHERE CAST(period AS DATE) >= DATE '2018-01-01';

-- CN8 rows kept only inside the validity window of the code (concordance = data standard)
CREATE OR REPLACE TABLE stg_comext_cn8 AS
SELECT c.*
FROM stg_comext c
JOIN concordance k
  ON k.material_id = c.material_id AND k.cn8_code = c.product_code
WHERE c.product_level = 'CN8'
  AND strftime(c.period, '%Y-%m') >= k.valid_from
  AND (k.valid_to IS NULL OR strftime(c.period, '%Y-%m') <= k.valid_to);

CREATE OR REPLACE TABLE stg_comext_de_mirror AS
SELECT CAST(period AS DATE) AS period, reporter, partner, product_code, flow,
       CAST(value_eur AS DOUBLE) AS value_eur, CAST(quantity_kg AS DOUBLE) AS quantity_kg
FROM read_csv('data/clean/stg_comext_de_mirror.csv', header = true,
              types = {'product_code': 'VARCHAR', 'partner': 'VARCHAR', 'reporter': 'VARCHAR'});

CREATE OR REPLACE TABLE stg_comext_composition AS
SELECT CAST(period AS DATE) AS period, reporter, partner, product_code, flow, CAST(value_eur AS DOUBLE) AS value_eur
FROM read_csv('data/clean/stg_comext_composition.csv', header = true,
              types = {'product_code': 'VARCHAR', 'partner': 'VARCHAR', 'reporter': 'VARCHAR'});

CREATE OR REPLACE TABLE stg_worldbank AS
SELECT CAST(period AS DATE) AS period, series_id, CAST(value AS DOUBLE) AS value
FROM read_csv_auto('data/clean/stg_worldbank.csv');

CREATE OR REPLACE TABLE stg_fred AS
SELECT CAST(period AS DATE) AS period, series_id, CAST(value AS DOUBLE) AS value
FROM read_csv_auto('data/clean/stg_fred.csv');

CREATE OR REPLACE TABLE stg_usgs AS
SELECT series_id, edition, CAST(year AS INTEGER) AS year, CAST(raw_value AS VARCHAR) AS raw_value,
       CAST(value_native AS DOUBLE) AS value_native
FROM read_csv('data/clean/stg_usgs.csv', header = true, all_varchar = true);

CREATE OR REPLACE TABLE stg_comtrade AS
SELECT CAST(year AS INTEGER) AS year, CAST(reporter AS VARCHAR) AS reporter, flow, CAST(partner AS VARCHAR) AS partner,
       CAST(hs6 AS VARCHAR) AS hs6, TRY_CAST(value_usd AS DOUBLE) AS value_usd, TRY_CAST(cif_usd AS DOUBLE) AS cif_usd,
       TRY_CAST(fob_usd AS DOUBLE) AS fob_usd, TRY_CAST(net_kg AS DOUBLE) AS net_kg,
       CAST(kg_estimated AS VARCHAR) AS kg_estimated
FROM read_csv('data/clean/stg_comtrade.csv', header = true, all_varchar = true);
