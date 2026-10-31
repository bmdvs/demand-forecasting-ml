-- Staging for bronze.truth__true_direct_demand: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_truth__true_direct_demand
COMMENT 'True direct demand by item and month'
AS
SELECT
    cast(item_id as int)            as item_id,
    cast(month as date)             as month,
    cast(bround(qty, 0) as bigint)  as qty
FROM bronze.truth__true_direct_demand;
