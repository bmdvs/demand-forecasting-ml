-- Error #6: missing and placeholder fields. Live items without a standard cost, a
-- reorder point or a primary supplier.
CREATE OR REFRESH MATERIALIZED VIEW silver.dq_06_missing_fields
COMMENT 'Error 6: missing and placeholder fields'
AS
select
    item_number,
    item_class,
    standard_cost is null           as missing_standard_cost,
    reorder_point is null           as missing_reorder_point,
    primary_supplier_id is null     as missing_supplier
from silver.int_items_resolved
where not is_dead
  and (standard_cost is null or reorder_point is null or primary_supplier_id is null);
