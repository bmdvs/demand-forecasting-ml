-- Staging for bronze.remediation__parameter_recommendations: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_remediation__parameter_recommendations
COMMENT 'Reorder parameters recomputed in the remediation'
AS
SELECT
    item_number,
    abc_class,
    cast(service_level as double)            as service_level,
    cast(old_reorder_point as double)        as old_reorder_point,
    cast(old_safety_stock as double)         as old_safety_stock,
    cast(new_reorder_point as double)        as new_reorder_point,
    cast(new_safety_stock as double)         as new_safety_stock
FROM bronze.remediation__parameter_recommendations;
