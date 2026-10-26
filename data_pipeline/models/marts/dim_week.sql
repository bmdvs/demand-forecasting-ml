-- The plant calendar by week: every Monday from the first history week to the end of the
-- forward window, its working days (weekdays inside the observation window, none in a
-- shutdown week), the shutdown flag, the fiscal quarter and the weeks to quarter end.
-- Grain: week (Monday).

{% set shutdowns = var('shutdown_weeks') %}

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
        n                                                             as week_index,
        cast({{ dbt.dateadd('day', '7 * n', "cast('" ~ var('first_monday') ~ "' as date)") }} as date) as week
    from numbers

),

in_window as (

    select week_index, week
    from weeks
    where week <= cast('{{ var("forward_end") }}' as date)

),

days as (

    -- the five weekdays of each week, counted only inside the observation window
    select w.week, w.week_index,
           cast({{ dbt.dateadd('day', 'k.d', 'w.week') }} as date) as day
    from in_window w
    cross join (select d from digits where d < 5) k

),

flagged as (

    select
        w.week_index,
        w.week,
        case when w.week in (
            {%- for s in shutdowns %}cast('{{ s }}' as date){% if not loop.last %}, {% endif %}{% endfor -%}
        ) then true else false end as is_shutdown
    from in_window w

)

select
    f.week_index,
    f.week,
    f.is_shutdown,
    case when f.is_shutdown then 0 else (
        select count(*) from days d
        where d.week = f.week
          and d.day >= cast('{{ var("start_date") }}' as date)
          and d.day <= cast('{{ var("forward_end") }}' as date)
    ) end                                                              as working_days,
    extract(year from f.week)                                          as fiscal_year,
    cast(floor((extract(month from f.week) - 1) / 3) + 1 as integer)   as fiscal_quarter,
    cast(floor({{ dbt.datediff('f.week', dbt.dateadd('day', -1, dbt.dateadd('month', 3, dbt.date_trunc('quarter', 'f.week'))), 'day') }} / 7) as integer) as weeks_to_quarter_end
from flagged f
