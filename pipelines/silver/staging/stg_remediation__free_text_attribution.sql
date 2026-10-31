-- Staging for bronze.remediation__free_text_attribution: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_remediation__free_text_attribution
COMMENT 'Generic-code purchase lines attributed to stocked items'
AS
SELECT
    po_id,
    probable_item_number,
    cast(confidence as double)               as confidence,
    confirmation
FROM bronze.remediation__free_text_attribution;
