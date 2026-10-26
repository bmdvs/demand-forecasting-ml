-- Item lead-time behavior by week, point in time, for every canonical item. Until an item
-- has {{ var('lt_min_receipts') }} non-rush receipts dated before the week, the corrected
-- master lead time stands in for lt_roll8 (lt_from_master). A successor part's statistics
-- start at its own first receipt.
-- lt_roll26w is the median of the non-rush receipts in the 26 weeks before the week when
-- there are at least {{ var('lt_min_receipts') }}, else lt_roll8, else the corrected master
-- (lt26_source records which), with lt_sd26w alongside. h_weeks, the policy horizon and the
-- firm-requirement horizon, is lt_roll26w in whole weeks, at least one.
-- Grain: canonical item x week.

with items as (

    select canonical_item_number, corrected_lead_days from {{ ref('mart_item_attributes') }}

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
    greatest(1, cast(round(
        case when coalesce(l.receipts_26w, 0) >= {{ var('lt_min_receipts') }} then l.median_26w
             when coalesce(l.receipts_to_date, 0) >= {{ var('lt_min_receipts') }} then l.lt_roll8
             else i.corrected_lead_days end / 7.0) as integer))              as h_weeks
from items i
cross join weeks w
left join lt l on l.key_id = i.canonical_item_number and l.week = w.week
