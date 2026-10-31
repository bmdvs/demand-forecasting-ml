-- Parent product activity by week: units completed in the week, and units booked on or
-- before the week's Monday and not completed before it (the open order book), by product
-- family. Feeds pf_builds_13 and pf_backlog. Grain: product family x week.
CREATE OR REFRESH MATERIALIZED VIEW gold.mart_product_family_weekly
COMMENT 'Product family activity by week'
AS
with jobs as (
    select
        case split_part(product_number, '-', 2)
            when 'CO' then 'Conveyor' when 'MI' then 'Mixer' when 'EN' then 'Enclosure'
        end as product_family,
        qty_ordered, qty_completed, booked_date, completed_date
    from silver.stg_erp__production_orders
),
grid as (
    select f.product_family, w.week
    from (select distinct product_family from jobs) f
    cross join gold.dim_week w
),
completed as (
    select g.product_family, g.week, sum(j.qty_completed) as units_completed
    from grid g
    join jobs j
      on j.product_family = g.product_family
     and j.completed_date >= g.week
     and j.completed_date < date_add(g.week, 7)
    group by 1, 2
),
open_book as (
    select g.product_family, g.week, sum(j.qty_ordered) as units_booked_open
    from grid g
    join jobs j
      on j.product_family = g.product_family
     and j.booked_date <= g.week
     and (j.completed_date is null or j.completed_date >= g.week)
    group by 1, 2
)
select
    g.product_family,
    g.week,
    coalesce(c.units_completed, 0)     as units_completed,
    coalesce(o.units_booked_open, 0)   as units_booked_open
from grid g
left join completed c on c.product_family = g.product_family and c.week = g.week
left join open_book o on o.product_family = g.product_family and o.week = g.week;
