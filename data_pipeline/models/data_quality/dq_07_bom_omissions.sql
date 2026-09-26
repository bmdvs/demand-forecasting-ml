-- Error #7: BOM omissions. Components consumed building a product but missing from its
-- bill of materials, so backflush never records them. Traced from chronic write-offs
-- and confirmed with the floor during remediation.

select
    b.product_number,
    b.component_item,
    b.qty_per,
    b.change_date
from {{ ref('stg_remediation__bom_change_log') }} b
left join {{ ref('stg_erp__bill_of_materials') }} m
    on b.product_number = m.product_number
   and b.component_item = m.component_item
where m.component_item is null
