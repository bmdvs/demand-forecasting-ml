with source as (

    select * from {{ source('truth', 'duplicate_clusters') }}

)

select
    item_number,
    "primary"                as primary_item_number
from source
