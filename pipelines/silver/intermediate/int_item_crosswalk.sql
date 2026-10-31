-- Item resolution: every live item record (numbered below 100000; dead records carry
-- six-digit numbers) mapped to the canonical record of its physical item. Records in a
-- duplicate cluster resolve to the cluster's primary record; all others map to
-- themselves. Grain: one row per live item record.
CREATE OR REFRESH MATERIALIZED VIEW silver.int_item_crosswalk
COMMENT 'Live item records and their canonical records'
AS
with live as (
    select
        item_number,
        try_cast(split_part(item_number, '-', 2) as int) as item_id
    from silver.stg_erp__item_master
    where split_part(item_number, '-', 2) rlike '^[0-9]+$'
      and try_cast(split_part(item_number, '-', 2) as int) < 100000
)
select
    l.item_number,
    l.item_id,
    coalesce(c.primary_item_number, l.item_number) as canonical_item_number
from live l
left join silver.stg_truth__duplicate_clusters c using (item_number);
