with source as (

    select * from {{ source('remediation', 'duplicate_crosswalk') }}

)

select
    retired_item_number,
    survivor_item_number,
    reason,
    reviewer,
    decision,
    cast(decision_date as date)      as decision_date
from source
