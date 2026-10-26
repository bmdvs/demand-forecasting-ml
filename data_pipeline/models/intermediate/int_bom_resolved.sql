{{ config(materialized="table") }}

-- The corrected bill of materials as of any date. One row per parent x component x
-- validity interval [valid_from, valid_to): a component is on its parent's bill at date d
-- when valid_from <= d < valid_to.
--   bill rows        the ERP bill. Rows set up at the start of the history have always
--                    been in force; a use-up supersession ends the old part's row on the
--                    day its stock ran out (expiry_date) and starts the successor's row
--                    that day (effective_date). A successor row with no effective date
--                    has not taken effect.
--   restored rows    components engineering restored in the remediation, from the change
--                    log, in force from the change date (supersession entries in the log
--                    repeat the bill's own effectivity and are not added again).
-- Components resolve to their canonical item; subassembly components keep their number.

with bill as (

    select
        b.product_number                                       as parent,
        b.component_item,
        b.qty_per,
        case
            when b.effectivity = 'USE_UP' and b.replaces_item is not null then b.effective_date
            when b.effective_date <= cast('{{ var("start_date") }}' as date) then cast('1900-01-01' as date)
            else b.effective_date
        end                                                    as valid_from,
        coalesce(b.expiry_date, cast('9999-12-31' as date))    as valid_to,
        case when b.effectivity = 'USE_UP' then 'supersession' else 'bill' end as row_source
    from {{ ref('stg_erp__bill_of_materials') }} b

),

restored as (

    select
        c.product_number                                       as parent,
        c.component_item,
        c.qty_per,
        c.change_date                                          as valid_from,
        cast('9999-12-31' as date)                             as valid_to,
        'restored'                                             as row_source
    from {{ ref('stg_remediation__bom_change_log') }} c
    where c.change_source not like 'supersession%'

),

rows_ as (

    select * from bill where valid_from is not null
    union all
    select * from restored

)

select
    r.parent,
    case when r.parent like 'SUB-%' then 'subassembly' else 'product' end      as parent_type,
    r.component_item,
    case when r.component_item like 'SUB-%' then r.component_item
         else coalesce(x.canonical_item_number, r.component_item) end            as component,
    case when r.component_item like 'SUB-%' then 'subassembly' else 'purchased' end as component_type,
    r.qty_per,
    r.valid_from,
    r.valid_to,
    r.row_source
from rows_ r
left join {{ ref('int_item_crosswalk') }} x on x.item_number = r.component_item
where r.valid_from < r.valid_to
