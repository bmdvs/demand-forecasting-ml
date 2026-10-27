-- Error #14: free-text purchases. Purchase order lines entered under a generic item code
-- with a typed description, hiding the demand of the stocked item they really bought.
CREATE OR REFRESH MATERIALIZED VIEW silver.dq_14_free_text_purchases
COMMENT 'Error 14: free-text purchases'
AS
select
    p.po_id,
    p.line,
    p.item_number        as generic_code,
    p.description_text,
    p.order_date,
    p.qty_ordered,
    p.unit_price,
    a.probable_item_number,
    a.confidence,
    a.confirmation
from silver.stg_erp__purchase_orders p
left join silver.stg_remediation__free_text_attribution a using (po_id)
where p.is_generic_item;
