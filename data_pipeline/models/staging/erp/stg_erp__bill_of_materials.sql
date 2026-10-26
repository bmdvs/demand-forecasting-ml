with source as (

    select * from {{ source('erp', 'bill_of_materials') }}

)

select
    product_number,
    component_item,
    cast(qty_per as double)          as qty_per,
    uom,
    -- Null on a successor row whose predecessor has not yet been used up.
    cast(effective_date as date)     as effective_date,
    -- DATE rows take effect on effective_date; USE_UP rows switch when the old part's
    -- stock runs out, recorded in expiry_date (old part) and effective_date (successor).
    cast(effectivity as varchar)     as effectivity,
    cast(planned_date as date)       as planned_date,
    cast(expiry_date as date)        as expiry_date,
    cast(replaces_item as varchar)   as replaces_item
from source
