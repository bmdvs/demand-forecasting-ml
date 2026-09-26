with source as (

    select * from {{ source('erp', 'production_orders') }}

)

select
    order_id,
    product_number,
    configuration_code,
    cast(qty_ordered as integer)     as qty_ordered,
    cast(qty_completed as integer)   as qty_completed,
    customer_id,
    cast(booked_date as date)        as booked_date,
    cast(release_date as date)       as release_date,
    cast(due_date as date)           as due_date,
    cast(completed_date as date)     as completed_date,
    status,
    hold_reason,
    cast(delay_days as integer)      as delay_days
from source
