-- Staging for bronze.truth__batched_receipts: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_truth__batched_receipts
COMMENT 'Receipt lines posted in a batch after arrival'
AS
SELECT
    po_id,
    cast(line as int)    as line
FROM bronze.truth__batched_receipts;
