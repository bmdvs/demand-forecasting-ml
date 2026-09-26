with source as (

    select * from {{ source('truth', 'batched_receipts') }}

)

select
    po_id,
    cast(line as integer)    as line
from source
