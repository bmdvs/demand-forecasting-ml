-- The long-run ratio that scales a supplier pool's lead time to an item: the item's median
-- lead time over all its non-rush receipts dated before the week, against the pool's median
-- over the same span (pool receipts from the item's first receipt to the week). Below
-- 4 item receipts the ratio is the corrected master against the pool's median over its
-- whole history to the week. The pool is the canonical supplier x item class. Medians by
-- rank. Grain: item x week.
CREATE OR REFRESH MATERIALIZED VIEW silver.int_leadtime_longrun
COMMENT 'Long-run item to supplier-pool lead-time ratio by week'
AS
with receipts as (
    select
        coalesce(x.canonical_item_number, p.item_number)                                  as canonical_item_number,
        coalesce(s.canonical_supplier_id, p.supplier_id) || '|' || coalesce(im.item_class, 'MISC') as pool_key,
        p.received_date,
        p.actual_lead_days                                                                 as lead_days
    from silver.stg_erp__purchase_orders p
    left join silver.int_item_crosswalk x on x.item_number = p.item_number
    left join silver.stg_remediation__supplier_crosswalk s on s.alias_supplier_id = p.supplier_id
    left join silver.stg_erp__item_master im on im.item_number = coalesce(x.canonical_item_number, p.item_number)
    where p.received_date is not null and not p.is_rush and not p.is_generic_item
),
items as (
    select a.canonical_item_number, a.corrected_lead_days,
           coalesce(sx.canonical_supplier_id, im.primary_supplier_id) || '|' || coalesce(im.item_class, 'MISC') as pool_key
    from gold.mart_item_attributes a
    left join silver.stg_erp__item_master im on im.item_number = a.canonical_item_number
    left join silver.stg_remediation__supplier_crosswalk sx on sx.alias_supplier_id = im.primary_supplier_id
),
grid as (
    select i.canonical_item_number, i.pool_key, i.corrected_lead_days, w.week
    from items i cross join gold.dim_week w
),
item_hist as (
    select g.canonical_item_number, g.week, r.lead_days,
           min(r.received_date) over (partition by g.canonical_item_number, g.week) as first_receipt,
           row_number() over (partition by g.canonical_item_number, g.week order by r.lead_days nulls last) as pos,
           count(*) over (partition by g.canonical_item_number, g.week)                as cnt
    from grid g
    join receipts r on r.canonical_item_number = g.canonical_item_number and r.received_date < g.week
),
item_med as (
    select canonical_item_number, week, max(cnt) as item_receipts, min(first_receipt) as first_receipt,
           avg(case when pos in (cast(floor((cnt + 1) / 2.0D) as int),
                                 cast(ceil((cnt + 1) / 2.0D) as int)) then lead_days end) as item_median
    from item_hist
    group by 1, 2
),
pool_span as (
    -- pool receipts over the item's own span: from its first receipt to the week
    select m.canonical_item_number, m.week, r.lead_days,
           row_number() over (partition by m.canonical_item_number, m.week order by r.lead_days nulls last) as pos,
           count(*) over (partition by m.canonical_item_number, m.week)                as cnt
    from item_med m
    join grid g on g.canonical_item_number = m.canonical_item_number and g.week = m.week
    join receipts r on r.pool_key = g.pool_key and r.received_date >= m.first_receipt and r.received_date < m.week
    where m.item_receipts >= 4
),
pool_span_med as (
    select canonical_item_number, week,
           avg(case when pos in (cast(floor((cnt + 1) / 2.0D) as int),
                                 cast(ceil((cnt + 1) / 2.0D) as int)) then lead_days end) as pool_span_median
    from pool_span
    group by 1, 2
),
pool_all as (
    select g.pool_key, g.week, r.lead_days,
           row_number() over (partition by g.pool_key, g.week order by r.lead_days nulls last) as pos,
           count(*) over (partition by g.pool_key, g.week)                as cnt
    from (select distinct pool_key, week from grid) g
    join receipts r on r.pool_key = g.pool_key and r.received_date < g.week
),
pool_all_med as (
    select pool_key, week,
           avg(case when pos in (cast(floor((cnt + 1) / 2.0D) as int),
                                 cast(ceil((cnt + 1) / 2.0D) as int)) then lead_days end) as pool_hist_median
    from pool_all
    group by 1, 2
)
select
    g.canonical_item_number,
    g.week,
    coalesce(m.item_receipts, 0)                       as item_receipts,
    m.item_median,
    s.pool_span_median,
    a.pool_hist_median,
    -- bounded to [0.25, 4]: a thin pool can otherwise scale a part to an impossible lead time
    least(4.0D, greatest(0.25D,
        case when coalesce(m.item_receipts, 0) >= 4 and s.pool_span_median > 0
                  then m.item_median / s.pool_span_median
             when a.pool_hist_median > 0
                  then g.corrected_lead_days / a.pool_hist_median
        end))                                          as longrun_ratio
from grid g
left join item_med m on m.canonical_item_number = g.canonical_item_number and m.week = g.week
left join pool_span_med s on s.canonical_item_number = g.canonical_item_number and s.week = g.week
left join pool_all_med a on a.pool_key = g.pool_key and a.week = g.week;
