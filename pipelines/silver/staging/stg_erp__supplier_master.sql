-- Staging for bronze.erp__supplier_master: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_erp__supplier_master
COMMENT 'Supplier records'
AS
SELECT
    supplier_id,
    supplier_name,
    supplier_type,
    payment_terms,
    status,
    -- Normalized name for fragment detection: letters only, legal suffix dropped.
    regexp_replace(
        regexp_replace(lower(supplier_name), '[^a-z]', ''),
        '(inc|llc|ltd|plc|co)$', '')         as supplier_name_norm
FROM bronze.erp__supplier_master;
