-- Firm dependent demand the order book shows on each origin Monday, point in time, for
-- every canonical item, from week 13 of the history to the end of the forward window:
--   firm_h       required in [origin, origin + h): booked on or before the origin and not
--                completed before it
--   firm_rel_h   the part of firm_h already released to the floor on the origin (what the
--                ERP's MRP sees without the order book)
--   firm_next4   required in the four weeks after the horizon
--   open_jobs    jobs contributing to firm_h
-- h is the item's lead time in whole weeks at the origin (mart_item_leadtime_weekly).
-- Grain: canonical item x origin week.
CREATE OR REFRESH MATERIALIZED VIEW gold.mart_firm_requirements_weekly
COMMENT 'Firm requirements in the order book by item and origin week'
AS
with grid as (
    select l.canonical_item_number, l.week as origin, l.h_weeks
    from gold.mart_item_leadtime_weekly l
    join gold.dim_week w on w.week = l.week
    where w.week_index >= 12
),
agg as (
    select
        canonical_item_number,
        origin,
        sum(case when bucket = 'horizon' then req_qty else 0 end)                           as firm_h,
        sum(case when bucket = 'horizon' and release_date <= origin then req_qty else 0 end) as firm_rel_h,
        sum(case when bucket = 'next4' then req_qty else 0 end)                             as firm_next4,
        count(distinct case when bucket = 'horizon' then order_id end)                      as open_jobs
    from silver.int_firm_contributions
    group by 1, 2
)
select
    g.canonical_item_number,
    g.origin,
    g.h_weeks,
    coalesce(a.firm_h, 0)       as firm_h,
    coalesce(a.firm_rel_h, 0)   as firm_rel_h,
    coalesce(a.firm_next4, 0)   as firm_next4,
    coalesce(a.open_jobs, 0)    as open_jobs
from grid g
left join agg a on a.canonical_item_number = g.canonical_item_number and a.origin = g.origin;
