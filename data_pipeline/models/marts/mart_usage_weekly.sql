-- Cleaned weekly usage on a dense item-by-week grid, so weeks without usage are explicit
-- zeros. Usage is what the ledger records as issued or backflushed, after the confirmed
-- corrections. Grain: one row per live canonical item per Monday week.

with usage as (

    select canonical_item_number, txn_week as week, sum(abs(qty)) as units_used
    from {{ ref('int_transactions_corrected') }}
    where txn_type in ('ISSUE', 'BACKFLUSH')
    group by 1, 2

),

items as (

    select canonical_item_number
    from {{ ref('int_items_resolved') }}
    where is_survivor and not is_dead

),

weeks as (

    select cast(unnest(generate_series(
        date_trunc('week', cast('{{ var("start_date") }}' as date)),
        date_trunc('week', cast('{{ var("as_of_date") }}' as date)),
        interval '7 days')) as date) as week

)

select
    i.canonical_item_number,
    w.week,
    coalesce(u.units_used, 0) as units_used
from items i
cross join weeks w
left join usage u
    on u.canonical_item_number = i.canonical_item_number
   and u.week = w.week
