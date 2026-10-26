{{ config(materialized="table") }}

-- Rolling lead-time statistics at each receipt, from non-rush received purchase-order
-- lines on stocked items. For each receipt (the anchor) the window is that receipt and
-- the previous {{ var('lt_window') - 1 }} of the same key: the median and standard
-- deviation of the lead time over it, and the median over the window before it (for the
-- trend). Built three times, keyed by canonical item, by canonical supplier, and by
-- canonical supplier x item class (supplier_class, "SUP-001|Mechanical"). Medians are
-- taken by rank, not with list functions, so the model runs on any SQL engine.

{% set n = var('lt_window') %}

with receipts as (

    select
        coalesce(x.canonical_item_number, p.item_number)   as canonical_item_number,
        coalesce(s.canonical_supplier_id, p.supplier_id)   as supplier_id,
        p.po_id, p.line,
        p.received_date,
        p.actual_lead_days                                  as lead_days,
        coalesce(im.item_class, 'MISC')                     as item_class
    from {{ ref('stg_erp__purchase_orders') }} p
    left join {{ ref('int_item_crosswalk') }} x on x.item_number = p.item_number
    left join {{ ref('stg_remediation__supplier_crosswalk') }} s on s.alias_supplier_id = p.supplier_id
    left join {{ ref('stg_erp__item_master') }} im on im.item_number = coalesce(x.canonical_item_number, p.item_number)
    where p.received_date is not null
      and not p.is_rush
      and not p.is_generic_item

),

keyed as (

    select 'item' as key_type, canonical_item_number as key_id, received_date, po_id, line, lead_days from receipts
    union all
    select 'supplier', supplier_id, received_date, po_id, line, lead_days from receipts
    union all
    select 'supplier_class', supplier_id || '|' || item_class, received_date, po_id, line, lead_days from receipts

),

numbered as (

    select k.*,
           row_number() over (partition by key_type, key_id order by received_date, po_id, line) as rn
    from keyed k

),

members as (

    -- window 0: the anchor and the receipts before it; window 1: the window before that
    select a.key_type, a.key_id, a.rn as anchor_rn, a.received_date as anchor_date,
           case when m.rn > a.rn - {{ n }} then 0 else 1 end as win,
           m.lead_days
    from numbered a
    join numbered m
      on m.key_type = a.key_type and m.key_id = a.key_id
     and m.rn <= a.rn and m.rn > a.rn - {{ 2 * n }}

),

ranked as (

    select m.*,
           row_number() over (partition by key_type, key_id, anchor_rn, win order by lead_days) as pos,
           count(*) over (partition by key_type, key_id, anchor_rn, win)                    as cnt
    from members m

),

stats as (

    select
        key_type, key_id, anchor_rn, anchor_date, win,
        max(cnt)                                                                  as n_in_window,
        avg(case when pos in (cast(floor((cnt + 1) / 2.0) as integer),
                              cast(ceil((cnt + 1) / 2.0) as integer)) then lead_days end) as median_lead,
        stddev_samp(lead_days)                                                    as sd_lead
    from ranked
    group by 1, 2, 3, 4, 5

)

select
    c.key_type,
    c.key_id,
    c.anchor_rn                    as receipts_to_date,
    c.anchor_date,
    c.median_lead                  as lt_roll8,
    c.sd_lead                      as lt_sd,
    p.median_lead                  as lt_prior8,
    case when p.n_in_window = {{ n }} and p.median_lead > 0
         then c.median_lead / p.median_lead end as lt_trend
from stats c
left join stats p
  on p.key_type = c.key_type and p.key_id = c.key_id and p.anchor_rn = c.anchor_rn and p.win = 1
where c.win = 0
