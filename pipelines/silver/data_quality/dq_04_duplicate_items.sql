-- Error #4: duplicate item records. Every record in a cluster that resolves to the same
-- physical part, with the usage split across the cluster's numbers.
CREATE OR REFRESH MATERIALIZED VIEW silver.dq_04_duplicate_items
COMMENT 'Error 4: duplicate item records'
AS
with crosswalk as (
    select item_number, canonical_item_number from silver.int_item_crosswalk
),
clusters as (
    select canonical_item_number
    from crosswalk
    group by 1
    having count(*) > 1
),
usage as (
    select item_number, sum(abs(qty)) as units_used
    from silver.stg_erp__inventory_transactions
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
left join usage u using (item_number);
