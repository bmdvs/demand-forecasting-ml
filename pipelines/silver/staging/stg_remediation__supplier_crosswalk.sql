-- Staging for bronze.remediation__supplier_crosswalk: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_remediation__supplier_crosswalk
COMMENT 'Supplier aliases and their canonical records'
AS
SELECT
    alias_supplier_id,
    canonical_supplier_id,
    reason
FROM bronze.remediation__supplier_crosswalk;
