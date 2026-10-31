-- Staging for bronze.truth__uom_mismatch_items: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_truth__uom_mismatch_items
COMMENT 'Items bought and stocked in different units'
AS
SELECT
    cast(item_id as int) as item_id
FROM bronze.truth__uom_mismatch_items;
