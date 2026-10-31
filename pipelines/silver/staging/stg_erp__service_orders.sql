-- Staging for bronze.erp__service_orders: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_erp__service_orders
COMMENT 'Service order lines'
AS
SELECT
    order_id,
    cast(line as int)                as line,
    item_number,
    customer_id,
    cast(order_date as date)         as order_date,
    cast(ship_date as date)          as ship_date,
    cast(qty as double)              as qty,
    cast(unit_price as double)       as unit_price
FROM bronze.erp__service_orders;
