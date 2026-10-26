{{ config(materialized="table") }}

-- Each job requirement as the order book showed it on an origin Monday: booked on or
-- before the origin, not completed before it (or still open), and required within the
-- item's horizon from the origin or the four weeks after. The horizon h comes from the
-- item's point-in-time lead time at the origin. Grain: origin x canonical item x order.

with origins as (

    select week as origin
    from {{ ref('dim_week') }}
    where week_index >= {{ var('first_origin_week') - 1 }}

),

h as (

    select canonical_item_number, week as origin, h_weeks
    from {{ ref('mart_item_leadtime_weekly') }}

)

select
    o.origin,
    r.canonical_item_number,
    r.order_id,
    h.h_weeks,
    r.req_qty,
    r.booked_date,
    r.release_date,
    r.required_date,
    r.completed_date,
    case when r.required_date < cast({{ dbt.dateadd('day', '7 * h.h_weeks', 'o.origin') }} as date)
         then 'horizon' else 'next4' end                          as bucket
from {{ ref('int_job_requirements') }} r
join origins o
  on r.booked_date <= o.origin
 and (r.completed_date is null or r.completed_date >= o.origin)
 and r.required_date >= o.origin
join h
  on h.canonical_item_number = r.canonical_item_number and h.origin = o.origin
where r.required_date < cast({{ dbt.dateadd('day', '7 * (h.h_weeks + 4)', 'o.origin') }} as date)
