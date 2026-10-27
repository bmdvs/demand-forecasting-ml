-- Staging for bronze.remediation__dead_item_dispositions: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_remediation__dead_item_dispositions
COMMENT 'Dead item records and their dispositions'
AS
SELECT
    item_number,
    disposition,
    reason,
    decided_by,
    cast(decision_date as date)      as decision_date
FROM bronze.remediation__dead_item_dispositions;
