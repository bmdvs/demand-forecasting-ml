with source as (

    select * from {{ source('remediation', 'chronic_adjustment_list') }}

)

select
    item_number,
    cast(adj_count_12m as integer)           as adj_count_12m,
    cast(net_qty as double)                  as net_qty,
    cast(implied_monthly as double)          as implied_monthly,
    cast(on_bom as boolean)                  as on_bom,
    root_cause
from source
