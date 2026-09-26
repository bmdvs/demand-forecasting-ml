-- Error #12: duplicate postings. A movement posted a second time with the same item,
-- type, quantity, job, location and user within a day of the first. Candidates are
-- flagged by rule; the confirmed flag marks those reversed in remediation.

with lines as (

    select
        txn_id, item_number, txn_type, qty, txn_date, job_id, location, user_id,
        lag(txn_date) over (
            partition by item_number, txn_type, qty, coalesce(job_id, 'NA'),
                         coalesce(location, 'NA'), coalesce(user_id, 'NA')
            order by txn_date, txn_time, txn_id) as prior_date
    from {{ ref('stg_erp__inventory_transactions') }}
    where txn_type in ('ISSUE', 'BACKFLUSH', 'RECEIPT')

),

confirmed as (

    select txn_id
    from {{ ref('stg_remediation__posting_corrections') }}
    where correction = 'duplicate posting reversed'

)

select
    l.txn_id,
    l.item_number,
    l.txn_type,
    l.qty,
    l.txn_date,
    date_diff('day', l.prior_date, l.txn_date)    as gap_days,
    l.txn_id in (select txn_id from confirmed)    as is_confirmed
from lines l
where l.prior_date is not null
  and date_diff('day', l.prior_date, l.txn_date) <= {{ var('duplicate_gap_days') }}
