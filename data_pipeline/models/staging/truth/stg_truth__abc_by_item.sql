with source as (

    select * from {{ source('truth', 'abc_by_item') }}

)

select
    cast(item_id as integer) as item_id,
    abc
from source
