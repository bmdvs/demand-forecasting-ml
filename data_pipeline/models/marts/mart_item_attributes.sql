-- One row per canonical item, the attributes the forecast and reorder policy read: cost,
-- class, demand pattern (classified from true monthly demand by average inter-demand
-- interval and squared coefficient of variation), planned ABC class, corrected lead
-- time and the last twelve months of demand.

with items as (

    select distinct x.canonical_item_number, x.item_id
    from {{ ref('int_item_crosswalk') }} x
    where x.item_number = x.canonical_item_number

),

months as (

    select distinct month from {{ ref('mart_true_demand') }}

),

grid as (

    select i.canonical_item_number, m.month, coalesce(d.consumption, 0) as consumption
    from items i
    cross join months m
    left join {{ ref('mart_true_demand') }} d
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

    select canonical_item_number, sum(consumption) as annual_consumption
    from grid
    where month > (select max(month) from months) - interval '12 months'
    group by 1

),

lead as (

    select item_number, recommended_lead_days
    from {{ ref('stg_remediation__lead_time_computation') }}

)

select
    i.canonical_item_number,
    coalesce(im.standard_cost, 1.0)                        as standard_cost,
    coalesce(im.item_class, 'MISC')                        as item_class,
    case
        when coalesce(p.n_nonzero, 0) < 2 then 'intermittent'
        when p.adi < 1.32 then case when p.cv2 < 0.49 then 'smooth' else 'erratic' end
        else case when p.cv2 < 0.49 then 'intermittent' else 'lumpy' end
    end                                                    as segment,
    coalesce(a.abc, 'C')                                   as abc,
    cast(coalesce(l.recommended_lead_days, im.master_lead_time_days, 21) as double) as corrected_lead_days,
    cast(coalesce(y.annual_consumption, 0) as double)      as annual_consumption
from items i
left join {{ ref('stg_erp__item_master') }} im on im.item_number = i.canonical_item_number
left join pattern p using (canonical_item_number)
left join {{ ref('stg_truth__abc_by_item') }} a using (item_id)
left join lead l on l.item_number = i.canonical_item_number
left join last_12 y using (canonical_item_number)
