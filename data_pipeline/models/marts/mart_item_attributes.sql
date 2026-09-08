-- One row per live canonical item: its class, cost, stale and corrected lead times,
-- reorder parameters, 2025 usage and value, ABC class by cumulative usage value, and
-- demand pattern (classified on monthly usage from average inter-demand interval and
-- squared coefficient of variation, the Syntetos-Boylan scheme).

with items as (

    select *
    from {{ ref('int_items_resolved') }}
    where is_survivor and not is_dead

),

monthly as (

    select canonical_item_number, date_trunc('month', week) as month, sum(units_used) as units_used
    from {{ ref('mart_usage_weekly') }}
    where week <= cast('{{ var("history_end") }}' as date)
    group by 1, 2

),

pattern_stats as (

    select
        canonical_item_number,
        count(*)                                                   as n_months,
        count(*) filter (where units_used > 0)                     as n_nonzero,
        avg(units_used) filter (where units_used > 0)              as mean_nonzero,
        stddev_pop(units_used) filter (where units_used > 0)       as sd_nonzero
    from monthly
    group by 1

),

pattern as (

    select
        canonical_item_number,
        case
            when n_nonzero < 2 then 'intermittent'
            when n_months::double / n_nonzero < 1.32 then
                case when pow(sd_nonzero / nullif(mean_nonzero, 0), 2) < 0.49 then 'smooth' else 'erratic' end
            else
                case when pow(sd_nonzero / nullif(mean_nonzero, 0), 2) < 0.49 then 'intermittent' else 'lumpy' end
        end as demand_pattern
    from pattern_stats

),

usage_2025 as (

    select canonical_item_number, sum(units_used) as annual_usage
    from monthly
    where month >= cast('{{ var("history_end") }}' as date) - interval '11 months'
    group by 1

),

params as (

    select * from {{ ref('stg_remediation__parameter_recommendations') }}

),

valued as (

    select
        i.canonical_item_number,
        i.description,
        i.item_class,
        i.stock_uom,
        i.standard_cost,
        i.primary_supplier_id,
        l.master_lead_time_days,
        l.corrected_lead_days,
        i.reorder_point                         as reorder_point_on_file,
        p.new_reorder_point                     as reorder_point_recomputed,
        p.new_safety_stock                      as safety_stock_recomputed,
        coalesce(u.annual_usage, 0)             as annual_usage,
        coalesce(u.annual_usage, 0) * coalesce(i.standard_cost, 0) as annual_usage_value,
        coalesce(pt.demand_pattern, 'intermittent') as demand_pattern
    from items i
    left join {{ ref('int_lead_times') }} l using (canonical_item_number)
    left join usage_2025 u using (canonical_item_number)
    left join params p on p.item_number = i.item_number
    left join pattern pt using (canonical_item_number)

),

ranked as (

    select
        *,
        sum(annual_usage_value) over (order by annual_usage_value desc, canonical_item_number
                                      rows between unbounded preceding and current row)
            / nullif(sum(annual_usage_value) over (), 0) as cum_value_share
    from valued

)

select
    * exclude (cum_value_share),
    case
        when cum_value_share <= {{ var('abc_a_cum') }} then 'A'
        when cum_value_share <= {{ var('abc_b_cum') }} then 'B'
        else 'C'
    end as abc_class
from ranked
