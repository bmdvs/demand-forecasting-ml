-- Recorded usage: every issue and backflush posting on a live item record, with its
-- canonical item, month and Monday week. Quantities are posted as negatives in the
-- ledger, so usage is the absolute quantity.

select
    t.txn_id,
    t.item_number,
    x.canonical_item_number,
    t.txn_type,
    date_trunc('month', t.txn_date)  as month,
    t.txn_week                       as week,
    abs(t.qty)                       as units
from {{ ref('stg_erp__inventory_transactions') }} t
join {{ ref('int_item_crosswalk') }} x using (item_number)
where t.txn_type in ('ISSUE', 'BACKFLUSH')
