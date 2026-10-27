-- Item master with the resolution applied. One row per recorded item: the canonical
-- item it resolves to, whether it is the surviving record, and whether it is a dead
-- record. Nothing is deleted; merges and deactivations are expressed as attributes.
CREATE OR REFRESH MATERIALIZED VIEW silver.int_items_resolved
COMMENT 'Item master with resolution attributes'
AS
with crosswalk as (
    select * from silver.int_item_crosswalk
),
dead as (
    select distinct item_number from silver.stg_remediation__dead_item_dispositions
)
select
    im.*,
    coalesce(x.canonical_item_number, im.item_number)                   as canonical_item_number,
    im.item_number = coalesce(x.canonical_item_number, im.item_number)  as is_survivor,
    d.item_number is not null                                           as is_dead
from silver.stg_erp__item_master im
left join crosswalk x on x.item_number = im.item_number
left join dead d on d.item_number = im.item_number;
