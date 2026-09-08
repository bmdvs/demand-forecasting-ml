with source as (

    select * from {{ source('truth', 'uom_mismatch_items') }}

)

select
    cast(item_id as integer) as item_id
from source
