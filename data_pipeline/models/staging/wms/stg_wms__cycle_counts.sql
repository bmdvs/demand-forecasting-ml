with source as (

    select * from {{ source('wms', 'cycle_counts') }}

)

select
    count_id,
    item_number,
    cast(count_date as date)         as count_date,
    cast(system_qty as double)       as system_qty,
    cast(counted_qty as double)      as counted_qty,
    cast(counted_qty as double) - cast(system_qty as double) as count_variance,
    counter_id,
    program
from source
