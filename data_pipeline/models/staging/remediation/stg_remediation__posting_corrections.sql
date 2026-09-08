with source as (

    select * from {{ source('remediation', 'posting_corrections') }}

)

select
    correction,
    txn_id,
    detail,
    -- detail reads 'from -> to': an item number for re-points, a quantity for keying errors.
    trim(split_part(detail, '->', 1))        as corrected_from,
    trim(split_part(detail, '->', 2))        as corrected_to,
    reviewed_by,
    cast(corrected_date as date)             as corrected_date
from source
