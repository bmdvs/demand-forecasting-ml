-- Staging for bronze.remediation__lead_time_computation: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_remediation__lead_time_computation
COMMENT 'Lead times recomputed in the remediation'
AS
SELECT
    item_number,
    supplier_id,
    cast(bround(master_lead_time, 0) as int) as master_lead_time_days,
    cast(median_actual as double)            as median_actual_lead_days,
    cast(p80_actual as double)               as p80_actual_lead_days,
    cast(sample_size as int)                 as sample_size,
    cast(recommended_lead_time as int)       as recommended_lead_days,
    cast(computed_date as date)              as computed_date
FROM bronze.remediation__lead_time_computation;
