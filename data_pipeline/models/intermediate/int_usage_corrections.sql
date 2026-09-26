-- The confirmed corrections to recorded usage, from the remediation records: keying
-- errors deflated to the true quantity and duplicate postings removed. One row per
-- corrected posting on a live item, carrying the change to usage (negative) and
-- whether the posting was an issue or backflush (weekly usage only corrects those).

with corrections as (

    select * from {{ ref('stg_remediation__posting_corrections') }}

),

ledger as (

    select t.txn_id, t.txn_type, t.qty, t.txn_week, date_trunc('month', t.txn_date) as month,
           x.canonical_item_number
    from {{ ref('stg_erp__inventory_transactions') }} t
    join {{ ref('int_item_crosswalk') }} x using (item_number)

)

select
    l.txn_id,
    l.canonical_item_number,
    l.month,
    l.txn_week                                      as week,
    l.txn_type in ('ISSUE', 'BACKFLUSH')            as is_usage_posting,
    'keying'                                        as correction,
    -(cast(c.corrected_from as double) - cast(c.corrected_to as double)) as delta
from corrections c
join ledger l using (txn_id)
where c.correction = 'quantity corrected'

union all

select
    l.txn_id,
    l.canonical_item_number,
    l.month,
    l.txn_week,
    true,
    'duplicate',
    -abs(l.qty)
from corrections c
join ledger l using (txn_id)
where c.correction = 'duplicate posting reversed'
  and l.txn_type in ('ISSUE', 'BACKFLUSH')
