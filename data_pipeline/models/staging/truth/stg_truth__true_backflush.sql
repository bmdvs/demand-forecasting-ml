with source as (

    select * from {{ source('truth', 'true_backflush') }}

)

select
    cast(item_id as integer) as item_id,
    cast(month as date)      as month,
    cast(qty as bigint)      as qty
from source
