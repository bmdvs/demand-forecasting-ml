with source as (

    select * from {{ source('remediation', 'supplier_crosswalk') }}

)

select
    alias_supplier_id,
    canonical_supplier_id,
    reason
from source
