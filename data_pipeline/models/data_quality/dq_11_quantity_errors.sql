-- Error #11: quantity and unit errors. Quantities keyed at the wrong magnitude or in the
-- wrong unit, confirmed and corrected by the stockroom lead.

select
    t.txn_id,
    t.item_number,
    t.txn_date,
    t.txn_type,
    cast(c.corrected_from as double) as posted_qty,
    cast(c.corrected_to as double)   as correct_qty
from {{ ref('stg_remediation__posting_corrections') }} c
join {{ ref('stg_erp__inventory_transactions') }} t using (txn_id)
where c.correction = 'quantity corrected'
