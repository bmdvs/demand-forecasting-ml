-- The plant calendar by week: every Monday from the first history week (2022-12-26) to the
-- end of the forward window (2026-06-30), its working days (weekdays inside the observation
-- window from 2023-01-01, none in a shutdown week), the shutdown flag, the fiscal quarter and
-- the weeks to quarter end. Grain: week (Monday).
CREATE OR REFRESH MATERIALIZED VIEW gold.dim_week
COMMENT 'The plant calendar by week'
AS
with digits as (
    select 0 as d union all select 1 union all select 2 union all select 3 union all select 4
    union all select 5 union all select 6 union all select 7 union all select 8 union all select 9
),
numbers as (
    select a.d + 10 * b.d + 100 * c.d as n
    from digits a cross join digits b cross join digits c
),
weeks as (
    select
        n                                     as week_index,
        date_add(date'2022-12-26', 7 * n)     as week
    from numbers
),
in_window as (
    select week_index, week
    from weeks
    where week <= date'2026-06-30'
),
days as (
    -- the five weekdays of each week, counted only inside the observation window
    select w.week, w.week_index,
           date_add(w.week, k.d) as day
    from in_window w
    cross join (select d from digits where d < 5) k
),
day_counts as (
    select week, count(*) as n_days
    from days
    where day >= date'2023-01-01' and day <= date'2026-06-30'
    group by 1
),
flagged as (
    select
        w.week_index,
        w.week,
        case when w.week in (date'2023-07-03', date'2023-12-25', date'2024-07-01', date'2024-12-23',
                             date'2025-06-30', date'2025-12-22', date'2026-06-29')
             then true else false end as is_shutdown
    from in_window w
)
select
    f.week_index,
    f.week,
    f.is_shutdown,
    case when f.is_shutdown then 0 else coalesce(dc.n_days, 0) end    as working_days,
    extract(year from f.week)                                          as fiscal_year,
    cast(floor((extract(month from f.week) - 1) / 3) + 1 as int)       as fiscal_quarter,
    cast(floor(datediff(date_add(add_months(trunc(f.week, 'QUARTER'), 3), -1), f.week) / 7) as int)
                                                                       as weeks_to_quarter_end
from flagged f
left join day_counts dc on dc.week = f.week;
