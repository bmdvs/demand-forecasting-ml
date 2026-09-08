-- Error #4: duplicate item records. Every record in a cluster that resolves to the same
-- physical part, with the usage split across the cluster's numbers.

with crosswalk as (

    select * from {{ ref('item_crosswalk') }}

),

clusters as (

    select canonical_item_number
    from crosswalk
    group by 1
    having count(*) > 1

),

usage as (

    select item_number, sum(abs(qty)) as units_used
    from {{ ref('stg_erp__inventory_transactions') }}
    where txn_type in ('ISSUE', 'BACKFLUSH')
    group by 1

)

select
    x.item_number,
    x.canonical_item_number,
    x.item_number = x.canonical_item_number as is_survivor,
    coalesce(u.units_used, 0)                as units_used
from crosswalk x
join clusters c using (canonical_item_number)
left join usage u using (item_number)
