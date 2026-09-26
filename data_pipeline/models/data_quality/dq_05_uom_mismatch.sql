-- Error #5: unit-of-measure mismatch. Live item records bought in one unit and stocked
-- in another with no conversion factor on the record. Duplicate records of the same
-- part are listed separately; the error register counts physical items.

select
    im.item_number,
    x.item_id,
    im.item_class,
    im.purchase_uom,
    im.stock_uom,
    im.standard_cost
from {{ ref('int_items_resolved') }} im
join {{ ref('int_item_crosswalk') }} x using (item_number)
where not im.is_dead
  and im.purchase_uom <> im.stock_uom
  and im.uom_conversion is null
