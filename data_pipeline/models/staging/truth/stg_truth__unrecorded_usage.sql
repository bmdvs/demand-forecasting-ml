with source as (

    select * from {{ source('truth', 'unrecorded_usage') }}

)

select
    cast(source_no as integer)          as source_no,
    item_number,
    cast(annual_unrecorded as double)   as annual_unrecorded
from source
