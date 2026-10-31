-- Staging for bronze.remediation__bom_change_log: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_remediation__bom_change_log
COMMENT 'Bill changes made in the remediation'
AS
SELECT
    product_number,
    component_item,
    cast(qty_per as double)                  as qty_per,
    source                                   as change_source,
    cast(change_date as date)                as change_date
FROM bronze.remediation__bom_change_log;
