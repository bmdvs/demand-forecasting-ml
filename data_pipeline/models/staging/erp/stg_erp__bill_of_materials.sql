with source as (

    select * from {{ source('erp', 'bill_of_materials') }}

)

select
    product_number,
    component_item,
    cast(qty_per as double)          as qty_per,
    uom,
    cast(effective_date as date)     as effective_date
from source
