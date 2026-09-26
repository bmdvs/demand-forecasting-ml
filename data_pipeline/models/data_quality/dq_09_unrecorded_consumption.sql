-- Error #9: unrecorded consumption. Material used on the floor but never issued, so it
-- surfaces as recurring negative write-offs outside the count programs, on items whose
-- chronic adjustments trace to a component missing from the BOM.

with omitted as (

    select item_number
    from {{ ref('stg_remediation__chronic_adjustment_list') }}
    where root_cause = 'BOM omission'

)

select
    t.txn_id,
    t.item_number,
    t.txn_date,
    t.qty,
    t.reason_code
from {{ ref('stg_erp__inventory_transactions') }} t
join omitted o using (item_number)
where t.txn_type = 'ADJUST'
  and t.qty < 0
  and coalesce(t.reason_code, '') not in ('COUNT', 'CYCLE')
