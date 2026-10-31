-- Integrity checks on the warehouse, one private materialized view per check (not published
-- to the catalog; results are in the pipeline's event log). Grain uniqueness and the
-- point-in-time rules fail the update; the other checks warn. The data-quality views in
-- silver are the audit's findings and are never checks.

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_stg_erp__item_master (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE,
  CONSTRAINT key_not_null EXPECT (null_keys = 0)
)
COMMENT 'Grain of silver.stg_erp__item_master: item_number'
AS
SELECT
    (SELECT count(*) FROM (SELECT item_number FROM silver.stg_erp__item_master WHERE item_number IS NOT NULL GROUP BY item_number HAVING count(*) > 1)) AS duplicate_keys,
    (SELECT count(*) FROM silver.stg_erp__item_master WHERE item_number IS NULL) AS null_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_stg_erp__supplier_master (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE,
  CONSTRAINT key_not_null EXPECT (null_keys = 0)
)
COMMENT 'Grain of silver.stg_erp__supplier_master: supplier_id'
AS
SELECT
    (SELECT count(*) FROM (SELECT supplier_id FROM silver.stg_erp__supplier_master WHERE supplier_id IS NOT NULL GROUP BY supplier_id HAVING count(*) > 1)) AS duplicate_keys,
    (SELECT count(*) FROM silver.stg_erp__supplier_master WHERE supplier_id IS NULL) AS null_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_stg_erp__inventory_transactions (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE,
  CONSTRAINT key_not_null EXPECT (null_keys = 0)
)
COMMENT 'Grain of silver.stg_erp__inventory_transactions: txn_id'
AS
SELECT
    (SELECT count(*) FROM (SELECT txn_id FROM silver.stg_erp__inventory_transactions WHERE txn_id IS NOT NULL GROUP BY txn_id HAVING count(*) > 1)) AS duplicate_keys,
    (SELECT count(*) FROM silver.stg_erp__inventory_transactions WHERE txn_id IS NULL) AS null_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_stg_erp__production_orders (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE,
  CONSTRAINT key_not_null EXPECT (null_keys = 0)
)
COMMENT 'Grain of silver.stg_erp__production_orders: order_id'
AS
SELECT
    (SELECT count(*) FROM (SELECT order_id FROM silver.stg_erp__production_orders WHERE order_id IS NOT NULL GROUP BY order_id HAVING count(*) > 1)) AS duplicate_keys,
    (SELECT count(*) FROM silver.stg_erp__production_orders WHERE order_id IS NULL) AS null_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_stg_wms__cycle_counts (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE,
  CONSTRAINT key_not_null EXPECT (null_keys = 0)
)
COMMENT 'Grain of silver.stg_wms__cycle_counts: count_id'
AS
SELECT
    (SELECT count(*) FROM (SELECT count_id FROM silver.stg_wms__cycle_counts WHERE count_id IS NOT NULL GROUP BY count_id HAVING count(*) > 1)) AS duplicate_keys,
    (SELECT count(*) FROM silver.stg_wms__cycle_counts WHERE count_id IS NULL) AS null_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_int_item_family (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE,
  CONSTRAINT key_not_null EXPECT (null_keys = 0)
)
COMMENT 'Grain of silver.int_item_family: canonical_item_number'
AS
SELECT
    (SELECT count(*) FROM (SELECT canonical_item_number FROM silver.int_item_family WHERE canonical_item_number IS NOT NULL GROUP BY canonical_item_number HAVING count(*) > 1)) AS duplicate_keys,
    (SELECT count(*) FROM silver.int_item_family WHERE canonical_item_number IS NULL) AS null_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_int_bom_resolved (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Grain of silver.int_bom_resolved: parent, component_item, valid_from, row_source'
AS
SELECT
    (SELECT count(*) FROM (SELECT parent, component_item, valid_from, row_source FROM silver.int_bom_resolved GROUP BY parent, component_item, valid_from, row_source HAVING count(*) > 1)) AS duplicate_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_int_job_requirements (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Grain of silver.int_job_requirements: order_id, canonical_item_number'
AS
SELECT
    (SELECT count(*) FROM (SELECT order_id, canonical_item_number FROM silver.int_job_requirements GROUP BY order_id, canonical_item_number HAVING count(*) > 1)) AS duplicate_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_int_receipt_windows (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Grain of silver.int_receipt_windows: key_type, key_id, receipts_to_date'
AS
SELECT
    (SELECT count(*) FROM (SELECT key_type, key_id, receipts_to_date FROM silver.int_receipt_windows GROUP BY key_type, key_id, receipts_to_date HAVING count(*) > 1)) AS duplicate_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_int_leadtime_weekly (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Grain of silver.int_leadtime_weekly: key_type, key_id, week'
AS
SELECT
    (SELECT count(*) FROM (SELECT key_type, key_id, week FROM silver.int_leadtime_weekly GROUP BY key_type, key_id, week HAVING count(*) > 1)) AS duplicate_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_int_firm_contributions (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Grain of silver.int_firm_contributions: origin, canonical_item_number, order_id'
AS
SELECT
    (SELECT count(*) FROM (SELECT origin, canonical_item_number, order_id FROM silver.int_firm_contributions GROUP BY origin, canonical_item_number, order_id HAVING count(*) > 1)) AS duplicate_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_int_product_installed_base (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Grain of silver.int_product_installed_base: product_number, month'
AS
SELECT
    (SELECT count(*) FROM (SELECT product_number, month FROM silver.int_product_installed_base GROUP BY product_number, month HAVING count(*) > 1)) AS duplicate_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_dim_week (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE,
  CONSTRAINT key_not_null EXPECT (null_keys = 0)
)
COMMENT 'Grain of gold.dim_week: week'
AS
SELECT
    (SELECT count(*) FROM (SELECT week FROM gold.dim_week WHERE week IS NOT NULL GROUP BY week HAVING count(*) > 1)) AS duplicate_keys,
    (SELECT count(*) FROM gold.dim_week WHERE week IS NULL) AS null_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_mart_item_attributes (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE,
  CONSTRAINT key_not_null EXPECT (null_keys = 0)
)
COMMENT 'Grain of gold.mart_item_attributes: canonical_item_number'
AS
SELECT
    (SELECT count(*) FROM (SELECT canonical_item_number FROM gold.mart_item_attributes WHERE canonical_item_number IS NOT NULL GROUP BY canonical_item_number HAVING count(*) > 1)) AS duplicate_keys,
    (SELECT count(*) FROM gold.mart_item_attributes WHERE canonical_item_number IS NULL) AS null_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_mart_inventory_position (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE,
  CONSTRAINT key_not_null EXPECT (null_keys = 0)
)
COMMENT 'Grain of gold.mart_inventory_position: canonical_item_number'
AS
SELECT
    (SELECT count(*) FROM (SELECT canonical_item_number FROM gold.mart_inventory_position WHERE canonical_item_number IS NOT NULL GROUP BY canonical_item_number HAVING count(*) > 1)) AS duplicate_keys,
    (SELECT count(*) FROM gold.mart_inventory_position WHERE canonical_item_number IS NULL) AS null_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_mart_supplier_performance (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE,
  CONSTRAINT key_not_null EXPECT (null_keys = 0)
)
COMMENT 'Grain of gold.mart_supplier_performance: supplier_id'
AS
SELECT
    (SELECT count(*) FROM (SELECT supplier_id FROM gold.mart_supplier_performance WHERE supplier_id IS NOT NULL GROUP BY supplier_id HAVING count(*) > 1)) AS duplicate_keys,
    (SELECT count(*) FROM gold.mart_supplier_performance WHERE supplier_id IS NULL) AS null_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_mart_item_leadtime_weekly (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Grain of gold.mart_item_leadtime_weekly: canonical_item_number, week'
AS
SELECT
    (SELECT count(*) FROM (SELECT canonical_item_number, week FROM gold.mart_item_leadtime_weekly GROUP BY canonical_item_number, week HAVING count(*) > 1)) AS duplicate_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_mart_supplier_leadtime_weekly (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Grain of gold.mart_supplier_leadtime_weekly: supplier_id, week'
AS
SELECT
    (SELECT count(*) FROM (SELECT supplier_id, week FROM gold.mart_supplier_leadtime_weekly GROUP BY supplier_id, week HAVING count(*) > 1)) AS duplicate_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_mart_firm_requirements_weekly (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Grain of gold.mart_firm_requirements_weekly: canonical_item_number, origin'
AS
SELECT
    (SELECT count(*) FROM (SELECT canonical_item_number, origin FROM gold.mart_firm_requirements_weekly GROUP BY canonical_item_number, origin HAVING count(*) > 1)) AS duplicate_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_mart_family_usage_weekly (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Grain of gold.mart_family_usage_weekly: family, week'
AS
SELECT
    (SELECT count(*) FROM (SELECT family, week FROM gold.mart_family_usage_weekly GROUP BY family, week HAVING count(*) > 1)) AS duplicate_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_mart_product_family_weekly (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Grain of gold.mart_product_family_weekly: product_family, week'
AS
SELECT
    (SELECT count(*) FROM (SELECT product_family, week FROM gold.mart_product_family_weekly GROUP BY product_family, week HAVING count(*) > 1)) AS duplicate_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_mart_shortage_weekly (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Grain of gold.mart_shortage_weekly: canonical_item_number, week'
AS
SELECT
    (SELECT count(*) FROM (SELECT canonical_item_number, week FROM gold.mart_shortage_weekly GROUP BY canonical_item_number, week HAVING count(*) > 1)) AS duplicate_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_mart_installed_base (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Grain of gold.mart_installed_base: product_family, month'
AS
SELECT
    (SELECT count(*) FROM (SELECT product_family, month FROM gold.mart_installed_base GROUP BY product_family, month HAVING count(*) > 1)) AS duplicate_keys;

CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_grain_mart_item_installed_base (
  CONSTRAINT grain_unique EXPECT (duplicate_keys = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Grain of gold.mart_item_installed_base: canonical_item_number, month'
AS
SELECT
    (SELECT count(*) FROM (SELECT canonical_item_number, month FROM gold.mart_item_installed_base GROUP BY canonical_item_number, month HAVING count(*) > 1)) AS duplicate_keys;

-- No job enters an origin's order book before it was booked, or after it was completed.
CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_firm_requirements_point_in_time (
  CONSTRAINT point_in_time EXPECT (violations = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Point-in-time rule of silver.int_firm_contributions'
AS
SELECT count(*) AS violations
FROM silver.int_firm_contributions
WHERE booked_date > origin
   OR (completed_date IS NOT NULL AND completed_date < origin);

-- No receipt dated on or after the week enters that week's lead-time statistics.
CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_leadtime_point_in_time (
  CONSTRAINT point_in_time EXPECT (violations = 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Point-in-time rule of silver.int_leadtime_weekly'
AS
SELECT count(*) AS violations
FROM silver.int_leadtime_weekly
WHERE last_receipt_date >= week;

-- Every item in the weekly usage series is a canonical item with attributes.
CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_consumption_weekly_items (
  CONSTRAINT items_have_attributes EXPECT (orphan_rows = 0)
)
COMMENT 'gold.mart_consumption_weekly items against gold.mart_item_attributes'
AS
SELECT count(*) AS orphan_rows
FROM gold.mart_consumption_weekly c
LEFT ANTI JOIN gold.mart_item_attributes a ON a.canonical_item_number = c.canonical_item_number
WHERE c.canonical_item_number IS NOT NULL;

-- Firm requirements appear only on items that some bill carries or that go out on
-- service orders.
CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_firm_only_on_bill_items (
  CONSTRAINT firm_only_on_bill_items EXPECT (violations = 0)
)
COMMENT 'Firm requirements only on carried or serviced items'
AS
WITH carried AS (
    SELECT DISTINCT component AS canonical_item_number
    FROM silver.int_bom_resolved WHERE component_type = 'purchased'
),
serviced AS (
    SELECT DISTINCT coalesce(x.canonical_item_number, s.item_number) AS canonical_item_number
    FROM silver.stg_erp__service_orders s
    LEFT JOIN silver.int_item_crosswalk x ON x.item_number = s.item_number
)
SELECT count(*) AS violations
FROM gold.mart_firm_requirements_weekly
WHERE firm_h > 0
  AND canonical_item_number NOT IN (SELECT canonical_item_number FROM carried)
  AND canonical_item_number NOT IN (SELECT canonical_item_number FROM serviced);

-- replaces_item is set only on USE_UP rows (a successor's replacement row), and every
-- other USE_UP row is the old part's row that some replacement row names.
CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_replaces_item_on_use_up_rows (
  CONSTRAINT replaces_item_on_use_up_rows EXPECT (violations = 0)
)
COMMENT 'Supersession rows of silver.stg_erp__bill_of_materials'
AS
SELECT count(*) AS violations
FROM silver.stg_erp__bill_of_materials b
WHERE (b.replaces_item IS NOT NULL AND b.effectivity <> 'USE_UP')
   OR (b.effectivity = 'USE_UP' AND b.replaces_item IS NULL
       AND b.component_item NOT IN (
           SELECT replaces_item FROM silver.stg_erp__bill_of_materials WHERE replaces_item IS NOT NULL));

-- Requirements of the jobs completed in 2025 reconcile to the year's recorded backflush:
-- the requirement may exceed the backflush by at most the unrecorded share (0.14;
-- components a bill omitted are consumed but not backflushed), and never fall short of it
-- by more.
CREATE OR REFRESH PRIVATE MATERIALIZED VIEW check_requirements_reconcile_to_backflush (
  CONSTRAINT requirements_reconcile EXPECT (abs(gap) <= 0.14D)
)
COMMENT '2025 requirements against recorded backflush'
AS
WITH req AS (
    SELECT sum(req_qty) AS qty FROM silver.int_job_requirements
    WHERE completed_date >= date'2025-01-01' AND completed_date < date'2026-01-01'
),
bf AS (
    SELECT sum(abs(qty)) AS qty FROM silver.stg_erp__inventory_transactions
    WHERE txn_type = 'BACKFLUSH'
      AND txn_date >= date'2025-01-01' AND txn_date < date'2026-01-01'
)
SELECT req.qty AS requirements, bf.qty AS backflush, (req.qty - bf.qty) / req.qty AS gap
FROM req CROSS JOIN bf;
