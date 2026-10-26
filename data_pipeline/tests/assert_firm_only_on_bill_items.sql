-- Firm requirements appear only on items that some bill carries or that go out on
-- service orders.
with carried as (
    select distinct component as canonical_item_number
    from {{ ref('int_bom_resolved') }} where component_type = 'purchased'
),
serviced as (
    select distinct coalesce(x.canonical_item_number, s.item_number) as canonical_item_number
    from {{ ref('stg_erp__service_orders') }} s
    left join {{ ref('int_item_crosswalk') }} x on x.item_number = s.item_number
)
select canonical_item_number, origin, firm_h
from {{ ref('mart_firm_requirements_weekly') }}
where firm_h > 0
  and canonical_item_number not in (select canonical_item_number from carried)
  and canonical_item_number not in (select canonical_item_number from serviced)
