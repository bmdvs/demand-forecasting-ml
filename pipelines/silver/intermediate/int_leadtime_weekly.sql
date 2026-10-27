-- Point-in-time supplier performance by week, for canonical items, for suppliers, and for
-- supplier x item class (key_type supplier_class, key "SUP-001|Mechanical"): the
-- rolling lead-time statistics as of the last non-rush receipt dated before the week, the
-- on-time and partial-receipt rates over the 13 weeks before it, and the purchase-order
-- lines open at the start of the week. Nothing dated on or after the week enters a row.
-- Grain: key_type x key_id x week.
CREATE OR REFRESH MATERIALIZED VIEW silver.int_leadtime_weekly
COMMENT 'Point-in-time lead-time and delivery statistics by key and week'
AS
with weeks as (
    select week from gold.dim_week
),
lines as (
    select
        coalesce(x.canonical_item_number, p.item_number)   as canonical_item_number,
        coalesce(s.canonical_supplier_id, p.supplier_id)   as supplier_id,
        p.order_date, p.promised_date, p.received_date, p.is_rush,
        p.qty_ordered, p.qty_received,
        coalesce(im.item_class, 'MISC')                    as item_class
    from silver.stg_erp__purchase_orders p
    left join silver.int_item_crosswalk x on x.item_number = p.item_number
    left join silver.stg_remediation__supplier_crosswalk s on s.alias_supplier_id = p.supplier_id
    left join silver.stg_erp__item_master im on im.item_number = coalesce(x.canonical_item_number, p.item_number)
    where not p.is_generic_item
),
keyed as (
    select 'item' as key_type, canonical_item_number as key_id, order_date, promised_date, received_date,
           is_rush, qty_ordered, qty_received from lines
    union all
    select 'supplier', supplier_id, order_date, promised_date, received_date, is_rush, qty_ordered, qty_received from lines
    union all
    select 'supplier_class', supplier_id || '|' || item_class, order_date, promised_date, received_date,
           is_rush, qty_ordered, qty_received from lines
),
keys as (
    select distinct key_type, key_id from keyed
),
grid as (
    select k.key_type, k.key_id, w.week from keys k cross join weeks w
),
last_anchor as (
    select g.key_type, g.key_id, g.week, max(r.receipts_to_date) as receipts_to_date
    from grid g
    join silver.int_receipt_windows r
      on r.key_type = g.key_type and r.key_id = g.key_id and r.anchor_date < g.week
    group by 1, 2, 3
),
recent as (
    select g.key_type, g.key_id, g.week,
           count(*)                                                                    as receipts_13,
           avg(case when k.received_date <= k.promised_date then 1.0D else 0.0D end)  as ontime_13,
           avg(case when k.qty_received < k.qty_ordered then 1.0D else 0.0D end)      as partial_13
    from grid g
    join keyed k
      on k.key_type = g.key_type and k.key_id = g.key_id
     and not k.is_rush
     and k.received_date < g.week
     and k.received_date >= date_add(g.week, -91)
    group by 1, 2, 3
),
window26 as (
    -- non-rush receipts in the 26 weeks before the week, ranked for the median
    select g.key_type, g.key_id, g.week, k.received_date,
           datediff(k.received_date, k.order_date) as lead_days,
           row_number() over (partition by g.key_type, g.key_id, g.week
                              order by datediff(k.received_date, k.order_date) nulls last) as pos,
           count(*) over (partition by g.key_type, g.key_id, g.week) as cnt
    from grid g
    join keyed k
      on k.key_type = g.key_type and k.key_id = g.key_id
     and not k.is_rush
     and k.received_date < g.week
     and k.received_date >= date_add(g.week, -182)
),
stats26 as (
    select key_type, key_id, week,
           max(cnt)                                                                 as receipts_26w,
           max(received_date)                                                       as last_receipt_26w,
           avg(case when pos in (cast(floor((cnt + 1) / 2.0D) as int),
                                 cast(ceil((cnt + 1) / 2.0D) as int)) then lead_days end) as median_26w,
           stddev_samp(lead_days)                                                   as sd_26w
    from window26
    group by 1, 2, 3
),
open_lines as (
    select g.key_type, g.key_id, g.week,
           count(*)                                                                  as open_po_count,
           max(case when k.promised_date < g.week
                    then datediff(g.week, k.promised_date) else 0 end)                as po_past_promise
    from grid g
    join keyed k
      on k.key_type = g.key_type and k.key_id = g.key_id
     and k.order_date < g.week
     and (k.received_date is null or k.received_date >= g.week)
    group by 1, 2, 3
)
select
    g.key_type,
    g.key_id,
    g.week,
    coalesce(a.receipts_to_date, 0)        as receipts_to_date,
    r.anchor_date                          as last_receipt_date,
    r.lt_roll8,
    r.lt_sd,
    r.lt_trend,
    rc.ontime_13,
    rc.partial_13,
    coalesce(o.open_po_count, 0)           as open_po_count,
    coalesce(o.po_past_promise, 0)         as po_past_promise,
    coalesce(s26.receipts_26w, 0)          as receipts_26w,
    s26.last_receipt_26w,
    s26.median_26w,
    s26.sd_26w
from grid g
left join last_anchor a on a.key_type = g.key_type and a.key_id = g.key_id and a.week = g.week
left join silver.int_receipt_windows r
  on r.key_type = g.key_type and r.key_id = g.key_id and r.receipts_to_date = a.receipts_to_date
left join recent rc on rc.key_type = g.key_type and rc.key_id = g.key_id and rc.week = g.week
left join open_lines o on o.key_type = g.key_type and o.key_id = g.key_id and o.week = g.week
left join stats26 s26 on s26.key_type = g.key_type and s26.key_id = g.key_id and s26.week = g.week;
