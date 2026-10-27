-- Staging for bronze.remediation__duplicate_crosswalk: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_remediation__duplicate_crosswalk
COMMENT 'Duplicate item records and their survivors'
AS
SELECT
    retired_item_number,
    survivor_item_number,
    reason,
    reviewer,
    decision,
    cast(decision_date as date)      as decision_date
FROM bronze.remediation__duplicate_crosswalk;
