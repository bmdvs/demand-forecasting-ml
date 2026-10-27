-- Fielded units of each product by month, from completed production orders, and the
-- age-weighted base that service demand follows: each unit weighted by its age (0.25
-- under 12 months, 0.65 under 24, 1.00 after). The ERP sees only units built since
-- the history opened; age_weighted_base_est adds an estimate of the units already in the
-- field then (8 years at the product's 2023 build rate, all past the ramp).
-- Months run from 2023-01-01 to the end of the forward window (2026-06-30).
-- Grain: product x month.
CREATE OR REFRESH MATERIALIZED VIEW silver.int_product_installed_base
COMMENT 'Installed base by product and month'
AS
with digits as (
    select 0 as d union all select 1 union all select 2 union all select 3 union all select 4
    union all select 5 union all select 6 union all select 7 union all select 8 union all select 9
),
months as (
    select a.d + 10 * b.d as month_index,
           add_months(date'2023-01-01', a.d + 10 * b.d) as month
    from digits a cross join digits b
),
months_in as (
    select month_index, month from months where month <= date'2026-06-30'
),
products as (
    select distinct product_number,
           case split_part(product_number, '-', 2)
               when 'CO' then 'Conveyor' when 'MI' then 'Mixer' when 'EN' then 'Enclosure'
           end as product_family
    from silver.stg_erp__production_orders
),
built as (
    select product_number, trunc(completed_date, 'MM') as month, sum(qty_completed) as units
    from silver.stg_erp__production_orders
    where completed_date is not null and qty_completed > 0
    group by 1, 2
),
grid as (
    select p.product_number, p.product_family, m.month_index, m.month
    from products p cross join months_in m
),
cohorts as (
    -- every month's units, aged at each later month
    select g.product_number, g.month,
           b.units,
           g.month_index - bm.month_index as age_months
    from grid g
    join built b on b.product_number = g.product_number
    join months_in bm on bm.month = b.month
    where bm.month_index <= g.month_index
),
observed as (
    select product_number, month,
           sum(units) as units_fielded,
           sum(units * case when age_months < 12 then 0.25
                            when age_months < 24 then 0.65
                            else 1.00 end) as age_weighted_base
    from cohorts
    group by 1, 2
),
rate_2023 as (
    select product_number, sum(units) / 12.0D as monthly_units
    from built
    where extract(year from month) = 2023
    group by 1
)
select
    g.product_number,
    g.product_family,
    g.month,
    coalesce(b.units, 0)                                       as units_completed,
    coalesce(o.units_fielded, 0)                               as units_fielded,
    coalesce(o.age_weighted_base, 0)                           as age_weighted_base,
    coalesce(o.age_weighted_base, 0)
      + 8 * 12 * coalesce(r.monthly_units, 0) * 1.00           as age_weighted_base_est
from grid g
left join built b on b.product_number = g.product_number and b.month = g.month
left join observed o on o.product_number = g.product_number and o.month = g.month
left join rate_2023 r on r.product_number = g.product_number;
