-- Weeks in which recorded consumption may understate demand, per canonical item:
--   short_week               the corrected ledger's balance is at or below zero on some day
--                            of the week (or carried into it at or below zero); receipts
--                            posted in a purchase unit are converted to the stock unit with
--                            the conversions confirmed in the remediation
--   short_active_week        a short week in which the part had usage, a held job or a
--                            service backorder
--   held_jobs                jobs drawing the item that were held for material during the
--                            week (the hold runs from the planned completion to the actual)
--   service_backorder_lines  service lines ordered in the week and shipped more than
--   service_backorder_qty    {{ var('service_backorder_days') }} days after order
-- Grain: canonical item x week.

with weeks as (

    select week from {{ ref('dim_week') }}

),

items as (

    select canonical_item_number from {{ ref('mart_item_attributes') }}

),

ledger as (

    select
        c.canonical_item_number,
        c.txn_date,
        c.txn_id,
        case c.txn_type
            when 'RECEIPT' then c.qty * coalesce(u.conversion, 1)
            when 'ADJUST' then c.qty
            else -abs(c.qty) end as signed_qty
    from {{ ref('int_transactions_corrected') }} c
    join {{ ref('stg_erp__inventory_transactions') }} t on t.txn_id = c.txn_id
    left join {{ ref('stg_remediation__uom_conversions') }} u
      on u.item_number = c.item_number and u.purchase_uom = t.uom and u.stock_uom <> t.uom

),

running as (

    select
        canonical_item_number,
        txn_date,
        cast(date_trunc('week', txn_date) as date) as week,
        sum(signed_qty) over (partition by canonical_item_number order by txn_date, txn_id
                              rows between unbounded preceding and current row) as balance
    from ledger

),

week_min as (

    select canonical_item_number, week, min(balance) as min_balance
    from running
    group by 1, 2

),

week_close as (

    select canonical_item_number, week, balance as close_balance
    from (
        select r.*, row_number() over (partition by canonical_item_number, week order by txn_date desc, balance) as rk
        from running r
    ) z
    where rk = 1

),

grid as (

    select i.canonical_item_number, w.week from items i cross join weeks w

),

carried as (

    -- the balance carried into each week: the close of the last week with postings before it
    select g.canonical_item_number, g.week, c.close_balance as carry_in
    from (
        select g.canonical_item_number, g.week, max(c.week) as last_week
        from grid g
        join week_close c on c.canonical_item_number = g.canonical_item_number and c.week < g.week
        group by 1, 2
    ) g
    join week_close c on c.canonical_item_number = g.canonical_item_number and c.week = g.last_week

),

holds as (

    select g.canonical_item_number, g.week, count(distinct r.order_id) as held_jobs
    from grid g
    join {{ ref('int_job_requirements') }} r
      on r.canonical_item_number = g.canonical_item_number
     and r.delay_days > 0
     and r.completed_date is not null
     and cast({{ dbt.dateadd('day', '-r.delay_days', 'r.completed_date') }} as date) < cast({{ dbt.dateadd('day', 7, 'g.week') }} as date)
     and r.completed_date > g.week
    group by 1, 2

),

backorders as (

    select
        coalesce(x.canonical_item_number, s.item_number)    as canonical_item_number,
        cast(date_trunc('week', s.order_date) as date)      as week,
        count(*)                                            as service_backorder_lines,
        sum(s.qty)                                          as service_backorder_qty
    from {{ ref('stg_erp__service_orders') }} s
    left join {{ ref('int_item_crosswalk') }} x on x.item_number = s.item_number
    where {{ dbt.datediff('s.order_date', 's.ship_date', 'day') }} > {{ var('service_backorder_days') }}
    group by 1, 2

),

usage as (

    select canonical_item_number, week, consumption from {{ ref('mart_consumption_weekly') }}

),

flags as (

    select g.canonical_item_number, g.week,
           case when least(coalesce(m.min_balance, c.carry_in), coalesce(c.carry_in, m.min_balance)) <= 0
                then true else false end as short_week
    from grid g
    left join week_min m on m.canonical_item_number = g.canonical_item_number and m.week = g.week
    left join carried c on c.canonical_item_number = g.canonical_item_number and c.week = g.week

)

select
    g.canonical_item_number,
    g.week,
    f.short_week,
    case when f.short_week and (coalesce(us.consumption, 0) > 0 or coalesce(h.held_jobs, 0) > 0
                                or coalesce(b.service_backorder_lines, 0) > 0)
         then true else false end                       as short_active_week,
    coalesce(h.held_jobs, 0)                            as held_jobs,
    coalesce(b.service_backorder_lines, 0)              as service_backorder_lines,
    coalesce(b.service_backorder_qty, 0)                as service_backorder_qty
from grid g
join flags f on f.canonical_item_number = g.canonical_item_number and f.week = g.week
left join usage us on us.canonical_item_number = g.canonical_item_number and us.week = g.week
left join holds h on h.canonical_item_number = g.canonical_item_number and h.week = g.week
left join backorders b on b.canonical_item_number = g.canonical_item_number and b.week = g.week
