with source as (

    select * from {{ source('remediation', 'free_text_attribution') }}

)

select
    po_id,
    probable_item_number,
    cast(confidence as double)               as confidence,
    confirmation
from source
