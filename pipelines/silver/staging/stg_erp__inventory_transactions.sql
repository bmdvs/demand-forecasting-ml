-- Staging for bronze.erp__inventory_transactions: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_erp__inventory_transactions (
  CONSTRAINT txn_type_accepted EXPECT (txn_type IN ('ISSUE', 'BACKFLUSH', 'RECEIPT', 'ADJUST'))
)
COMMENT 'The inventory ledger, one row per posting'
AS
SELECT
    txn_id,
    item_number,
    cast(txn_date as date)                          as txn_date,
    -- Time of day as HH:mm:ss text; Delta tables carry no time-of-day type.
    date_format(to_timestamp(txn_time, 'H:mm'), 'HH:mm:ss') as txn_time,
    date_trunc('WEEK', cast(txn_date as date))      as txn_week,
    type                                            as txn_type,
    cast(qty as double)                             as qty,
    uom,
    -- JOB- production orders, SO- service orders, WO- floor work orders, PO- receipts.
    job_id,
    reason_code,
    location,
    user_id
FROM bronze.erp__inventory_transactions;
