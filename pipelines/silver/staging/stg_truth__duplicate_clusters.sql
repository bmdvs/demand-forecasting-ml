-- Staging for bronze.truth__duplicate_clusters: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_truth__duplicate_clusters
COMMENT 'Duplicate item clusters and their primary records'
AS
SELECT
    item_number,
    `primary`                as primary_item_number
FROM bronze.truth__duplicate_clusters;
