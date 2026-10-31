-- Staging for bronze.truth__unrecorded_usage: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_truth__unrecorded_usage
COMMENT 'Usage sources that escape the ledger'
AS
SELECT
    cast(source_no as int)              as source_no,
    item_number,
    cast(annual_unrecorded as double)   as annual_unrecorded
FROM bronze.truth__unrecorded_usage;
