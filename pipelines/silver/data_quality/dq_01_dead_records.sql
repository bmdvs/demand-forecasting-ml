-- Error #1: dead records never deactivated. Item records flagged active with no more
-- than one movement and no purchase order in the two years before the history closed.
-- History end 2025-12-31, lookback 24 months.
CREATE OR REFRESH MATERIALIZED VIEW silver.dq_01_dead_records
COMMENT 'Error 1: dead records never deactivated'
AS
with window_txn as (
    select item_number, count(*) as movements_24m
    from silver.stg_erp__inventory_transactions
    where txn_date between add_months(date'2025-12-31', -24) and date'2025-12-31'
    group by 1
),
window_po as (
    select distinct item_number
    from silver.stg_erp__purchase_orders
    where order_date >= add_months(date'2025-12-31', -24)
)
select
    im.item_number,
    im.item_class,
    im.last_updated,
    coalesce(w.movements_24m, 0) as movements_24m
from silver.stg_erp__item_master im
left join window_txn w using (item_number)
where im.status = 'ACTIVE'
  and coalesce(w.movements_24m, 0) <= 1
  and im.item_number not in (select item_number from window_po);
