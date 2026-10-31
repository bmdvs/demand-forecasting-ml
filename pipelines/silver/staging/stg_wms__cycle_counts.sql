-- Staging for bronze.wms__cycle_counts: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_wms__cycle_counts
COMMENT 'Warehouse cycle and annual counts'
AS
SELECT
    count_id,
    item_number,
    cast(count_date as date)         as count_date,
    cast(system_qty as double)       as system_qty,
    cast(counted_qty as double)      as counted_qty,
    cast(counted_qty as double) - cast(system_qty as double) as count_variance,
    counter_id,
    program
FROM bronze.wms__cycle_counts;
