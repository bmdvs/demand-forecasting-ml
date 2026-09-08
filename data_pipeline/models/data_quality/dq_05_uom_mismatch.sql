-- Error #5: unit-of-measure mismatch. Live items bought in one unit and stocked in
-- another with no conversion factor on the record.

select
    item_number,
    item_class,
    purchase_uom,
    stock_uom,
    standard_cost
from {{ ref('int_items_resolved') }}
where not is_dead
  and purchase_uom <> stock_uom
  and uom_conversion is null
