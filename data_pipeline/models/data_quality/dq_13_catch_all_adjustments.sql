-- Error #13: adjustments used as a catch-all. Inventory adjustments with no reason code
-- or a vague one, so the correction says that the number changed but not why.

select
    txn_id,
    item_number,
    txn_date,
    qty,
    reason_code,
    user_id
from {{ ref('stg_erp__inventory_transactions') }}
where txn_type = 'ADJUST'
  and (reason_code is null or reason_code in ('ADJ', 'VAR', 'MISC', 'COUNT'))
