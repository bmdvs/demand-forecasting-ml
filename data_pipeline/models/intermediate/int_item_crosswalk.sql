{{ config(materialized="table") }}

-- Item resolution: every live item record (numbered below 100000; dead records carry
-- six-digit numbers) mapped to the canonical record of its physical item. Records in a
-- duplicate cluster resolve to the cluster's primary record; all others map to
-- themselves. Grain: one row per live item record.

with live as (

    select
        item_number,
        try_cast(split_part(item_number, '-', 2) as integer) as item_id
    from {{ ref('stg_erp__item_master') }}
    where regexp_full_match(split_part(item_number, '-', 2), '[0-9]+')
      and try_cast(split_part(item_number, '-', 2) as integer) < 100000

)

select
    l.item_number,
    l.item_id,
    coalesce(c.primary_item_number, l.item_number) as canonical_item_number
from live l
left join {{ ref('stg_truth__duplicate_clusters') }} c using (item_number)
