-- Error #2: stale lead times. Live items whose master lead time differs from the median
-- lead time actually realized on received purchase orders by more than the threshold.

with actual as (

    select item_number, median(actual_lead_days) as median_actual_lead_days, count(*) as receipts
    from {{ ref('stg_erp__purchase_orders') }}
    where received_date is not null
    group by 1

)

select
    im.item_number,
    im.master_lead_time_days,
    a.median_actual_lead_days,
    a.median_actual_lead_days - im.master_lead_time_days as gap_days,
    a.receipts
from {{ ref('int_items_resolved') }} im
join actual a using (item_number)
where not im.is_dead
  and abs(a.median_actual_lead_days - im.master_lead_time_days) > {{ var('stale_lead_gap_days') }}
