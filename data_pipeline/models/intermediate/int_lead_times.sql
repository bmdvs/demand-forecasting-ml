-- Corrected lead time per canonical item: the lead time recomputed from actual receipts
-- in remediation, replacing the stale master value (error #2), falling back to the
-- median realized lead time where no recommendation was made.

with recommended as (

    select item_number, recommended_lead_days
    from {{ ref('stg_remediation__lead_time_computation') }}

),

realized as (

    select item_number, median(actual_lead_days) as median_actual_lead_days
    from {{ ref('stg_erp__purchase_orders') }}
    where received_date is not null
    group by 1

)

select
    im.canonical_item_number,
    max(im.master_lead_time_days) filter (where im.is_survivor)                    as master_lead_time_days,
    coalesce(max(r.recommended_lead_days) filter (where im.is_survivor),
             median(a.median_actual_lead_days),
             max(im.master_lead_time_days) filter (where im.is_survivor))           as corrected_lead_days
from {{ ref('int_items_resolved') }} im
left join recommended r using (item_number)
left join realized a using (item_number)
where not im.is_dead
group by 1
