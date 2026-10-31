-- Staging for bronze.erp__bill_of_materials: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_erp__bill_of_materials (
  CONSTRAINT effectivity_not_null EXPECT (effectivity IS NOT NULL),
  CONSTRAINT effectivity_accepted EXPECT (effectivity IN ('DATE', 'USE_UP'))
)
COMMENT 'Bill of materials, one row per product, component and effectivity row'
AS
SELECT
    product_number,
    component_item,
    cast(qty_per as double)          as qty_per,
    uom,
    -- Null on a successor row whose predecessor has not yet been used up.
    cast(effective_date as date)     as effective_date,
    -- DATE rows take effect on effective_date; USE_UP rows switch when the old part's
    -- stock runs out, recorded in expiry_date (old part) and effective_date (successor).
    cast(effectivity as string)      as effectivity,
    cast(planned_date as date)       as planned_date,
    cast(expiry_date as date)        as expiry_date,
    cast(replaces_item as string)    as replaces_item
FROM bronze.erp__bill_of_materials;
