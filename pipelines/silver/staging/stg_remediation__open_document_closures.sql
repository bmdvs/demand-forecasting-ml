-- Staging for bronze.remediation__open_document_closures: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_remediation__open_document_closures
COMMENT 'Open documents closed in the remediation'
AS
SELECT
    document_type,
    document_id,
    cast(line as int)                        as line,
    cast(closed_date as date)                as closed_date,
    confirmation_source
FROM bronze.remediation__open_document_closures;
