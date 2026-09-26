with source as (

    select * from {{ source('remediation', 'uom_conversions') }}

)

select
    item_number,
    purchase_uom,
    stock_uom,
    cast(conversion as double)       as conversion,
    cast(added_date as date)         as added_date
from source
