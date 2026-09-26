with source as (

    select * from {{ source('erp', 'inventory_transactions') }}

)

select
    txn_id,
    item_number,
    cast(txn_date as date)                          as txn_date,
    cast(txn_time as time)                          as txn_time,
    date_trunc('week', cast(txn_date as date))      as txn_week,
    type                                            as txn_type,
    cast(qty as double)                             as qty,
    uom,
    -- JOB- production orders, SO- service orders, WO- floor work orders, PO- receipts.
    job_id,
    reason_code,
    location,
    user_id
from source
