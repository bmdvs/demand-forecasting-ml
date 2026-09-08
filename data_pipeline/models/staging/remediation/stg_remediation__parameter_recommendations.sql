with source as (

    select * from {{ source('remediation', 'parameter_recommendations') }}

)

select
    item_number,
    abc_class,
    cast(service_level as double)            as service_level,
    cast(old_reorder_point as double)        as old_reorder_point,
    cast(old_safety_stock as double)         as old_safety_stock,
    cast(new_reorder_point as double)        as new_reorder_point,
    cast(new_safety_stock as double)         as new_safety_stock
from source
