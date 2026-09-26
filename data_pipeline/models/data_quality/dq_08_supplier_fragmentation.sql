-- Error #8: supplier fragmentation. One vendor carried under several supplier records
-- whose names normalize to the same value.

with s as (

    select *, count(*) over (partition by supplier_name_norm) as n_records
    from {{ ref('stg_erp__supplier_master') }}

)

select
    supplier_id,
    supplier_name,
    supplier_name_norm,
    n_records
from s
where n_records > 1
