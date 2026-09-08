-- Error #15: batched and backdated postings. Receipts are keyed in batches, so posting
-- dates pile up on one weekday instead of following actual arrivals, and every lead time
-- computed from them runs long. Grain: one row per weekday.

with receipts as (

    select dayofweek(txn_date) as dow, dayname(txn_date) as weekday
    from {{ ref('stg_erp__inventory_transactions') }}
    where txn_type = 'RECEIPT'

)

select
    dow,
    weekday,
    count(*)                                           as receipts,
    round(count(*) / sum(count(*)) over (), 3)         as share_of_receipts
from receipts
group by 1, 2
order by 1
