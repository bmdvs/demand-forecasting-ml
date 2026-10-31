-- Staging for bronze.remediation__chronic_adjustment_list: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_remediation__chronic_adjustment_list
COMMENT 'Items with chronic adjustments and their root causes'
AS
SELECT
    item_number,
    cast(adj_count_12m as int)               as adj_count_12m,
    cast(net_qty as double)                  as net_qty,
    cast(implied_monthly as double)          as implied_monthly,
    cast(on_bom as boolean)                  as on_bom,
    root_cause
FROM bronze.remediation__chronic_adjustment_list;
