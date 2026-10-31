-- Staging for bronze.truth__true_backflush: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_truth__true_backflush
COMMENT 'True backflush by item and month'
AS
SELECT
    cast(item_id as int) as item_id,
    cast(month as date)  as month,
    cast(qty as bigint)  as qty
FROM bronze.truth__true_backflush;
