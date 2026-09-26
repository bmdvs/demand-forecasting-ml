with source as (

    select * from {{ source('erp', 'supplier_master') }}

)

select
    supplier_id,
    supplier_name,
    supplier_type,
    payment_terms,
    status,
    -- Normalized name for fragment detection: letters only, legal suffix dropped.
    regexp_replace(
        regexp_replace(lower(supplier_name), '[^a-z]', '', 'g'),
        '(inc|llc|ltd|plc|co)$', '')         as supplier_name_norm
from source
