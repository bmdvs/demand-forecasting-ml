-- replaces_item is set only on USE_UP rows (a successor's replacement row), and every
-- other USE_UP row is the old part's row that some replacement row names.
select product_number, component_item, effectivity, replaces_item
from {{ ref('stg_erp__bill_of_materials') }} b
where (b.replaces_item is not null and b.effectivity <> 'USE_UP')
   or (b.effectivity = 'USE_UP' and b.replaces_item is null
       and b.component_item not in (
           select replaces_item from {{ ref('stg_erp__bill_of_materials') }} where replaces_item is not null))
