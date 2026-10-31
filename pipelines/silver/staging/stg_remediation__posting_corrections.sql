-- Staging for bronze.remediation__posting_corrections: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_remediation__posting_corrections
COMMENT 'Ledger postings corrected in the remediation'
AS
SELECT
    correction,
    txn_id,
    detail,
    -- detail reads 'from -> to': an item number for re-points, a quantity for keying errors.
    trim(split_part(detail, '->', 1))        as corrected_from,
    trim(split_part(detail, '->', 2))        as corrected_to,
    reviewed_by,
    cast(corrected_date as date)             as corrected_date
FROM bronze.remediation__posting_corrections;
