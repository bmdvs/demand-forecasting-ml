with source as (

    select * from {{ source('remediation', 'lead_time_computation') }}

)

select
    item_number,
    supplier_id,
    cast(master_lead_time as integer)        as master_lead_time_days,
    cast(median_actual as double)            as median_actual_lead_days,
    cast(p80_actual as double)               as p80_actual_lead_days,
    cast(sample_size as integer)             as sample_size,
    cast(recommended_lead_time as integer)   as recommended_lead_days,
    cast(computed_date as date)              as computed_date
from source
