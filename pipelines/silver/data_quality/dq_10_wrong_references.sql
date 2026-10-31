-- Error #10: wrong references. Transactions posted against the wrong item, confirmed
-- and re-pointed by the stockroom lead.
CREATE OR REFRESH MATERIALIZED VIEW silver.dq_10_wrong_references
COMMENT 'Error 10: wrong references'
AS
select
    t.txn_id,
    t.txn_date,
    t.txn_type,
    t.qty,
    c.corrected_from as posted_item_number,
    c.corrected_to   as correct_item_number
from silver.stg_remediation__posting_corrections c
join silver.stg_erp__inventory_transactions t using (txn_id)
where c.correction = 're-pointed to correct item';
