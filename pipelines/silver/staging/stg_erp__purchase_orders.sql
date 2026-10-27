-- Staging for bronze.erp__purchase_orders: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_erp__purchase_orders (
  CONSTRAINT po_id_not_null EXPECT (po_id IS NOT NULL),
  CONSTRAINT status_accepted EXPECT (status IN ('OPEN', 'CLOSED'))
)
COMMENT 'Purchase order lines'
AS
SELECT
    po_id,
    cast(line as int)                         as line,
    item_number,
    -- Typed description on generic-code lines (error #14).
    description_text,
    item_number in ('NONSTOCK', 'MISC', 'SHOPSUPPLY') as is_generic_item,
    supplier_id,
    cast(order_date as date)                  as order_date,
    cast(promised_date as date)               as promised_date,
    -- Null until the line is received.
    cast(received_date as date)               as received_date,
    cast(qty_ordered as double)               as qty_ordered,
    cast(qty_received as double)              as qty_received,
    cast(unit_price as double)                as unit_price,
    status,
    cast(rush as boolean)                     as is_rush,
    cast(freight as double)                   as freight,
    case when received_date is not null
         then datediff(cast(received_date as date), cast(order_date as date))
    end                                       as actual_lead_days
FROM bronze.erp__purchase_orders;
