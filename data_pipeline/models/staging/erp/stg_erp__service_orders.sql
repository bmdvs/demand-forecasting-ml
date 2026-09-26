with source as (

    select * from {{ source('erp', 'service_orders') }}

)

select
    order_id,
    cast(line as integer)            as line,
    item_number,
    customer_id,
    cast(order_date as date)         as order_date,
    cast(ship_date as date)          as ship_date,
    cast(qty as double)              as qty,
    cast(unit_price as double)       as unit_price
from source
