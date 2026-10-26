-- Item lead-time behavior by week, point in time, for every canonical item. Until an item
-- has {{ var('lt_min_receipts') }} non-rush receipts dated before the week, the corrected
-- master lead time stands in for lt_roll8 (lt_from_master). A successor part's statistics
-- start at its own first receipt.
-- lt_roll26w is the median of the non-rush receipts in the 26 weeks before the week when
-- there are at least {{ var('lt_min_receipts') }}, else lt_roll8, else the corrected master
-- (lt26_source records which), with lt_sd26w alongside.
-- lt_pooled26w pools thin items with their supplier: the item's own 26-week median when it
-- has {{ var('lt_min_receipts') }} receipts in the window; else the canonical supplier's 26-week
-- median across its items of the same class (at least {{ var('lt_min_receipts') }} receipts), scaled
-- by the item's long-run ratio to that pool (int_leadtime_longrun: the item's median over its
-- full history to date against the pool's median over the same span); else the item's
-- lt_roll8; else the corrected master. lt_source records the level used (item,
-- supplier, roll8, master). h_weeks, the policy horizon and the firm-requirement horizon, is
-- lt_pooled26w in whole weeks, at least one. Grain: canonical item x week.

with items as (

    select a.canonical_item_number, a.corrected_lead_days,
           coalesce(sx.canonical_supplier_id, im.primary_supplier_id) || '|' || coalesce(im.item_class, 'MISC') as pool_key
    from {{ ref('mart_item_attributes') }} a
    left join {{ ref('stg_erp__item_master') }} im on im.item_number = a.canonical_item_number
    left join {{ ref('stg_remediation__supplier_crosswalk') }} sx on sx.alias_supplier_id = im.primary_supplier_id

),

pool as (

    select key_id as pool_key, week, receipts_26w, median_26w, sd_26w, lt_roll8 as pool_roll8, receipts_to_date
    from {{ ref('int_leadtime_weekly') }} where key_type = 'supplier_class'

),

weeks as (

    select week from {{ ref('dim_week') }}

),

lt as (

    select * from {{ ref('int_leadtime_weekly') }} where key_type = 'item'

)

select
    i.canonical_item_number,
    w.week,
    coalesce(l.receipts_to_date, 0)                                          as receipts_to_date,
    l.last_receipt_date,
    coalesce(l.receipts_to_date, 0) < {{ var('lt_min_receipts') }}           as lt_from_master,
    case when coalesce(l.receipts_to_date, 0) < {{ var('lt_min_receipts') }}
         then i.corrected_lead_days else l.lt_roll8 end                      as lt_roll8,
    l.lt_sd,
    l.lt_trend,
    l.ontime_13,
    l.partial_13,
    coalesce(l.open_po_count, 0)                                             as open_po_count,
    coalesce(l.po_past_promise, 0)                                           as po_past_promise,
    coalesce(l.receipts_26w, 0)                                              as receipts_26w,
    case when coalesce(l.receipts_26w, 0) >= {{ var('lt_min_receipts') }} then '26w'
         when coalesce(l.receipts_to_date, 0) >= {{ var('lt_min_receipts') }} then 'roll8'
         else 'master' end                                                   as lt26_source,
    case when coalesce(l.receipts_26w, 0) >= {{ var('lt_min_receipts') }} then l.median_26w
         when coalesce(l.receipts_to_date, 0) >= {{ var('lt_min_receipts') }} then l.lt_roll8
         else i.corrected_lead_days end                                      as lt_roll26w,
    case when coalesce(l.receipts_26w, 0) >= {{ var('lt_min_receipts') }} then l.sd_26w
         else l.lt_sd end                                                    as lt_sd26w,
    p.lt_source,
    p.lt_pooled26w,
    p.lt_pooled_sd26w,
    greatest(1, cast(round(p.lt_pooled26w / 7.0) as integer))               as h_weeks
from items i
cross join weeks w
left join lt l on l.key_id = i.canonical_item_number and l.week = w.week
left join (
    select i2.canonical_item_number, w2.week,
           case when coalesce(l2.receipts_26w, 0) >= {{ var('lt_min_receipts') }} then 'item'
                when coalesce(po.receipts_26w, 0) >= {{ var('lt_min_receipts') }} and lr.longrun_ratio > 0 then 'supplier'
                when coalesce(l2.receipts_to_date, 0) >= {{ var('lt_min_receipts') }} then 'roll8'
                else 'master' end as lt_source,
           case when coalesce(l2.receipts_26w, 0) >= {{ var('lt_min_receipts') }} then l2.median_26w
                when coalesce(po.receipts_26w, 0) >= {{ var('lt_min_receipts') }} and lr.longrun_ratio > 0
                     then po.median_26w * lr.longrun_ratio
                when coalesce(l2.receipts_to_date, 0) >= {{ var('lt_min_receipts') }} then l2.lt_roll8
                else i2.corrected_lead_days end as lt_pooled26w,
           case when coalesce(l2.receipts_26w, 0) >= {{ var('lt_min_receipts') }} then l2.sd_26w
                when coalesce(po.receipts_26w, 0) >= {{ var('lt_min_receipts') }} and lr.longrun_ratio > 0
                     then po.sd_26w * lr.longrun_ratio
                else l2.lt_sd end as lt_pooled_sd26w
    from items i2
    cross join weeks w2
    left join lt l2 on l2.key_id = i2.canonical_item_number and l2.week = w2.week
    left join pool po on po.pool_key = i2.pool_key and po.week = w2.week
    left join {{ ref('int_leadtime_longrun') }} lr on lr.canonical_item_number = i2.canonical_item_number and lr.week = w2.week
) p on p.canonical_item_number = i.canonical_item_number and p.week = w.week
