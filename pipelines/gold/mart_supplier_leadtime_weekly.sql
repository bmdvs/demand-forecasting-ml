-- Supplier lead-time behavior by week, point in time: rolling median and standard
-- deviation of the last 8 non-rush receipts dated before the week, the trend against the
-- 8 before those, on-time and partial-receipt rates over the prior 13 weeks, and the lines
-- open at the start of the week. Grain: canonical supplier x week.
CREATE OR REFRESH MATERIALIZED VIEW gold.mart_supplier_leadtime_weekly
COMMENT 'Point-in-time supplier lead times by week'
AS
select
    key_id                 as supplier_id,
    week,
    receipts_to_date,
    last_receipt_date,
    lt_roll8,
    lt_sd,
    lt_trend,
    ontime_13,
    partial_13,
    open_po_count,
    po_past_promise,
    receipts_26w,
    case when receipts_26w >= 4 then median_26w else lt_roll8 end as lt_roll26w,
    case when receipts_26w >= 4 then sd_26w else lt_sd end        as lt_sd26w,
    receipts_26w < 4                                              as lt26_fallback
from silver.int_leadtime_weekly
where key_type = 'supplier';
