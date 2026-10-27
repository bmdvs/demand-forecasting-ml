-- Component requirements of every production order, exploded through the corrected bill
-- as it stood on the day the order was booked: quantity ordered x quantity per, through
-- subassemblies. The component is the part the bill named at booking; a later switch to a
-- successor does not rewrite it. Requirements fall in the job's required week (the Monday
-- of its due week). Grain: order x canonical component.
CREATE OR REFRESH MATERIALIZED VIEW silver.int_job_requirements (
  CONSTRAINT required_date_not_null EXPECT (required_date IS NOT NULL)
)
COMMENT 'Component requirements of production orders'
AS
with jobs as (
    select
        order_id,
        product_number,
        case split_part(product_number, '-', 2)
            when 'CO' then 'Conveyor' when 'MI' then 'Mixer' when 'EN' then 'Enclosure'
        end                                   as product_family,
        configuration_code,
        customer_id,
        qty_ordered,
        qty_completed,
        booked_date,
        release_date,
        due_date,
        required_date,
        completed_date,
        status,
        coalesce(delay_days, 0)               as delay_days
    from silver.stg_erp__production_orders
),
bom as (
    select * from silver.int_bom_resolved
),
direct as (
    select j.order_id, b.component, j.qty_ordered * b.qty_per as qty
    from jobs j
    join bom b
      on b.parent = j.product_number
     and b.component_type = 'purchased'
     and j.booked_date >= b.valid_from and j.booked_date < b.valid_to
),
via_sub as (
    select j.order_id, s.component, j.qty_ordered * p.qty_per * s.qty_per as qty
    from jobs j
    join bom p
      on p.parent = j.product_number
     and p.component_type = 'subassembly'
     and j.booked_date >= p.valid_from and j.booked_date < p.valid_to
    join bom s
      on s.parent = p.component
     and s.component_type = 'purchased'
     and j.booked_date >= s.valid_from and j.booked_date < s.valid_to
),
req as (
    select order_id, component as canonical_item_number, sum(qty) as req_qty
    from (select * from direct union all select * from via_sub) u
    group by 1, 2
)
select
    r.order_id,
    r.canonical_item_number,
    r.req_qty,
    j.required_date                           as required_week,
    j.booked_date,
    j.release_date,
    j.due_date,
    j.required_date,
    j.completed_date,
    j.status,
    j.delay_days,
    j.qty_ordered,
    j.qty_completed,
    j.customer_id,
    j.product_number,
    j.product_family,
    j.configuration_code
from req r
join jobs j using (order_id);
