-- Requirements of the jobs completed in 2025 reconcile to the year's recorded backflush:
-- the requirement may exceed the backflush by at most the unrecorded share (components
-- a bill omitted are consumed but not backflushed), and never fall short of it by more.
with req as (
    select sum(req_qty) as qty from {{ ref('int_job_requirements') }}
    where completed_date >= cast('2025-01-01' as date) and completed_date < cast('2026-01-01' as date)
),
bf as (
    select sum(abs(qty)) as qty from {{ ref('stg_erp__inventory_transactions') }}
    where txn_type = 'BACKFLUSH'
      and txn_date >= cast('2025-01-01' as date) and txn_date < cast('2026-01-01' as date)
)
select req.qty as requirements, bf.qty as backflush, (req.qty - bf.qty) / req.qty as gap
from req cross join bf
where abs(req.qty - bf.qty) / req.qty > {{ var('t1_unrecorded_share') }}
