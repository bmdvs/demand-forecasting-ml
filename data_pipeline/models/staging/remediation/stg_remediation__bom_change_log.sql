with source as (

    select * from {{ source('remediation', 'bom_change_log') }}

)

select
    product_number,
    component_item,
    cast(qty_per as double)                  as qty_per,
    source                                   as change_source,
    cast(change_date as date)                as change_date
from source
