-- Recorded inventory position per live canonical item as of the reference date: the
-- corrected ledger's net on hand, material genuinely on order (open lines closed in
-- remediation excluded), and their value at standard cost.

with on_hand as (

    select
        canonical_item_number,
        sum(case txn_type when 'RECEIPT' then qty
                          when 'ADJUST' then qty
                          else -abs(qty) end) as on_hand_units
    from {{ ref('int_transactions_corrected') }}
    where txn_date <= cast('{{ var("as_of_date") }}' as date)
    group by 1

),

closed as (

    select document_id, line
    from {{ ref('stg_remediation__open_document_closures') }}
    where document_type = 'PO'

),

on_order as (

    select
        coalesce(x.canonical_item_number, p.item_number)       as canonical_item_number,
        sum(greatest(p.qty_ordered - coalesce(p.qty_received, 0), 0)) as on_order_units
    from {{ ref('stg_erp__purchase_orders') }} p
    left join {{ ref('item_crosswalk') }} x using (item_number)
    left join closed c on c.document_id = p.po_id and c.line = p.line
    where p.status = 'OPEN'
      and c.document_id is null
      and p.order_date <= cast('{{ var("as_of_date") }}' as date)
    group by 1

)

select
    a.canonical_item_number,
    a.abc_class,
    a.demand_pattern,
    a.standard_cost,
    greatest(coalesce(h.on_hand_units, 0), 0)                                   as on_hand_units,
    coalesce(o.on_order_units, 0)                                               as on_order_units,
    round(greatest(coalesce(h.on_hand_units, 0), 0) * coalesce(a.standard_cost, 0), 2) as on_hand_value
from {{ ref('mart_item_attributes') }} a
left join on_hand h using (canonical_item_number)
left join on_order o using (canonical_item_number)
