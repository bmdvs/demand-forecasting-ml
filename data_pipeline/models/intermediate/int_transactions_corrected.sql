-- The inventory ledger with the confirmed remediation corrections applied: duplicate
-- postings reversed, wrong-item postings re-pointed, keying errors corrected, and every
-- line mapped to its canonical item. The source ledger is not modified.

with tx as (

    select * from {{ ref('stg_erp__inventory_transactions') }}

),

corrections as (

    select * from {{ ref('stg_remediation__posting_corrections') }}

),

crosswalk as (

    select * from {{ ref('item_crosswalk') }}

),

corrected as (

    select
        tx.txn_id,
        tx.txn_date,
        tx.txn_week,
        tx.txn_type,
        tx.job_id,
        tx.reason_code,
        coalesce(rp.corrected_to, tx.item_number)                 as item_number,
        coalesce(sign(tx.qty) * try_cast(qc.corrected_to as double), tx.qty) as qty
    from tx
    left join corrections rp
        on rp.txn_id = tx.txn_id and rp.correction = 're-pointed to correct item'
    left join corrections qc
        on qc.txn_id = tx.txn_id and qc.correction = 'quantity corrected'
    where tx.txn_id not in (
        select txn_id from corrections where correction = 'duplicate posting reversed')

)

select
    c.*,
    coalesce(x.canonical_item_number, c.item_number) as canonical_item_number
from corrected c
left join crosswalk x using (item_number)
