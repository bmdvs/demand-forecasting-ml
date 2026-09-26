with source as (

    select * from {{ source('remediation', 'open_document_closures') }}

)

select
    document_type,
    document_id,
    cast(line as integer)                    as line,
    cast(closed_date as date)                as closed_date,
    confirmation_source
from source
