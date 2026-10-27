-- Staging for bronze.truth__abc_by_item: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_truth__abc_by_item
COMMENT 'Planned ABC class by item'
AS
SELECT
    cast(item_id as int) as item_id,
    abc
FROM bronze.truth__abc_by_item;
