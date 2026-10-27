-- Staging for bronze.remediation__uom_conversions: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_remediation__uom_conversions
COMMENT 'Unit-of-measure conversions confirmed in the remediation'
AS
SELECT
    item_number,
    purchase_uom,
    stock_uom,
    cast(conversion as double)       as conversion,
    cast(added_date as date)         as added_date
FROM bronze.remediation__uom_conversions;
