-- Supplier delivery performance and spend from received purchase-order lines, with
-- fragmented supplier records consolidated to one supplier (error #8).
-- Grain: one row per canonical supplier.

with po as (

    select
        coalesce(x.canonical_supplier_id, p.supplier_id) as supplier_id,
        p.actual_lead_days,
        p.received_date <= p.promised_date               as on_time,
        p.is_rush,
        p.qty_received * p.unit_price                    as spend
    from {{ ref('stg_erp__purchase_orders') }} p
    left join {{ ref('stg_remediation__supplier_crosswalk') }} x
        on x.alias_supplier_id = p.supplier_id
    where p.received_date is not null

)

select
    po.supplier_id,
    s.supplier_name,
    s.supplier_type,
    count(*)                                         as received_lines,
    median(po.actual_lead_days)                      as median_lead_days,
    quantile_cont(po.actual_lead_days, 0.9)          as p90_lead_days,
    round(avg(case when po.on_time then 1 else 0 end), 3) as on_time_share,
    round(avg(case when po.is_rush then 1 else 0 end), 3) as rush_share,
    round(sum(po.spend), 2)                          as spend
from po
left join {{ ref('stg_erp__supplier_master') }} s using (supplier_id)
group by 1, 2, 3
