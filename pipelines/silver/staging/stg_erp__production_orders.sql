-- Staging for bronze.erp__production_orders: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_erp__production_orders (
  CONSTRAINT required_date_not_null EXPECT (required_date IS NOT NULL)
)
COMMENT 'Production orders, one row per job'
AS
SELECT
    order_id,
    product_number,
    configuration_code,
    cast(qty_ordered as int)         as qty_ordered,
    cast(qty_completed as int)       as qty_completed,
    customer_id,
    cast(booked_date as date)        as booked_date,
    cast(release_date as date)       as release_date,
    cast(due_date as date)           as due_date,
    -- The Monday of the due week: when the job's material is required, known at booking.
    cast(required_date as date)      as required_date,
    cast(completed_date as date)     as completed_date,
    status,
    hold_reason,
    cast(delay_days as int)          as delay_days
FROM bronze.erp__production_orders;
