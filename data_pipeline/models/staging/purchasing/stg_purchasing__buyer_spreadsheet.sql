with source as (

    select * from {{ source('purchasing', 'buyer_spreadsheet') }}

)

select
    item_ref,
    on_hand_note,
    -- The approximate on-hand figure the buyer keeps, parsed from her note.
    try_cast(regexp_extract(on_hand_note, '([0-9]+)', 1) as integer) as on_hand_estimate,
    lead_time_note,
    reorder_note,
    preferred_supplier_note,
    cast(last_updated as date)       as last_updated
from source
