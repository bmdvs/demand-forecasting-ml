with source as (

    select * from {{ source('remediation', 'dead_item_dispositions') }}

)

select
    item_number,
    disposition,
    reason,
    decided_by,
    cast(decision_date as date)      as decision_date
from source
