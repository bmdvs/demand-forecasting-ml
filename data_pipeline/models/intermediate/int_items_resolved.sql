-- Item master with the resolution applied. One row per recorded item: the canonical
-- item it resolves to, whether it is the surviving record, and whether it is a dead
-- record. Nothing is deleted; merges and deactivations are expressed as attributes.

with item_master as (

    select * from {{ ref('stg_erp__item_master') }}

),

crosswalk as (

    select * from {{ ref('int_item_crosswalk') }}

),

dead as (

    select item_number from {{ ref('stg_remediation__dead_item_dispositions') }}

)

select
    im.*,
    coalesce(x.canonical_item_number, im.item_number)                   as canonical_item_number,
    im.item_number = coalesce(x.canonical_item_number, im.item_number)  as is_survivor,
    im.item_number in (select item_number from dead)                    as is_dead
from item_master im
left join crosswalk x using (item_number)
