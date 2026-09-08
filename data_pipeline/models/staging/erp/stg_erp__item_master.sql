with source as (

    select * from {{ source('erp', 'item_master') }}

)

select
    item_number,
    description,
    uom                                      as stock_uom,
    purchase_uom,
    cast(uom_conversion as double)           as uom_conversion,
    item_class,
    -- Nullable: blank costs, reorder points and suppliers are error #6.
    cast(standard_cost as double)            as standard_cost,
    cast(reorder_point as double)            as reorder_point,
    cast(safety_stock as double)             as safety_stock,
    cast(master_lead_time_days as integer)   as master_lead_time_days,
    primary_supplier_id,
    status,
    created_by,
    cast(created_date as date)               as created_date,
    cast(last_updated as date)               as last_updated
from source
