-- One row per canonical item, the attributes the forecast and reorder policy read: cost,
-- class, demand pattern (classified from true monthly demand by average inter-demand
-- interval and squared coefficient of variation), planned ABC class, corrected lead
-- time and the last twelve months of demand.
CREATE OR REFRESH MATERIALIZED VIEW gold.mart_item_attributes (
  CONSTRAINT abc_accepted EXPECT (abc IN ('A', 'B', 'C')),
  CONSTRAINT segment_accepted EXPECT (segment IN ('smooth', 'erratic', 'lumpy', 'intermittent'))
)
COMMENT 'Item attributes for the forecast and reorder policy'
AS
with items as (
    select distinct x.canonical_item_number, x.item_id
    from silver.int_item_crosswalk x
    where x.item_number = x.canonical_item_number
),
months as (
    select distinct month from gold.mart_true_demand
),
grid as (
    select i.canonical_item_number, m.month, coalesce(d.consumption, 0) as consumption
    from items i
    cross join months m
    left join gold.mart_true_demand d
        on d.canonical_item_number = i.canonical_item_number and d.month = m.month
),
nonzero as (
    select canonical_item_number, cast(consumption as double) as x
    from grid
    where consumption > 0
),
moments as (
    select canonical_item_number, count(*) as n_nonzero, avg(x) as mean_nonzero
    from nonzero
    group by 1
),
pattern as (
    select
        m.canonical_item_number,
        m.n_nonzero,
        (select count(*) from months) / m.n_nonzero as adi,
        pow(sqrt(avg(pow(n.x - m.mean_nonzero, 2))) / m.mean_nonzero, 2) as cv2
    from moments m
    join nonzero n using (canonical_item_number)
    group by m.canonical_item_number, m.n_nonzero, m.mean_nonzero
),
last_12 as (
    -- the twelve months to the latest month of true demand
    select canonical_item_number, sum(consumption) as annual_consumption
    from grid
    where month > add_months((select max(month) from months), -12)
    group by 1
),
lead as (
    select item_number, recommended_lead_days
    from silver.stg_remediation__lead_time_computation
),
-- lifecycle: first recorded use, set-up date, and part supersession from the bill
first_use as (
    select canonical_item_number, min(cast(week as date)) as first_use_date
    from silver.int_recorded_usage
    group by 1
),
supersession as (
    -- the old part's bill rows carry the planned date and, once used up, the switch date
    select b.component_item as item_number,
           min(b.planned_date) as supersede_planned_date,
           min(b.expiry_date)  as supersede_switch_date
    from silver.stg_erp__bill_of_materials b
    where b.effectivity = 'USE_UP' and b.replaces_item is null
    group by 1
)
select
    i.canonical_item_number,
    coalesce(im.standard_cost, 1.0D)                       as standard_cost,
    coalesce(im.item_class, 'MISC')                        as item_class,
    case
        when coalesce(p.n_nonzero, 0) < 2 then 'intermittent'
        when p.adi < 1.32 then case when p.cv2 < 0.49 then 'smooth' else 'erratic' end
        else case when p.cv2 < 0.49 then 'intermittent' else 'lumpy' end
    end                                                    as segment,
    coalesce(a.abc, 'C')                                   as abc,
    cast(coalesce(l.recommended_lead_days, im.master_lead_time_days, 21) as double) as corrected_lead_days,
    cast(coalesce(y.annual_consumption, 0) as double)      as annual_consumption,
    fu.first_use_date,
    im.created_date,
    im.superseded_by,
    ss.supersede_planned_date,
    ss.supersede_switch_date,
    sc.created_date                                        as successor_created_date,
    pr.item_number                                         as supersedes
from items i
left join silver.stg_erp__item_master im on im.item_number = i.canonical_item_number
left join first_use fu using (canonical_item_number)
left join supersession ss on ss.item_number = i.canonical_item_number
left join silver.stg_erp__item_master sc on sc.item_number = im.superseded_by
left join silver.stg_erp__item_master pr on pr.superseded_by = i.canonical_item_number
left join pattern p using (canonical_item_number)
left join silver.stg_truth__abc_by_item a using (item_id)
left join lead l on l.item_number = i.canonical_item_number
left join last_12 y using (canonical_item_number);
