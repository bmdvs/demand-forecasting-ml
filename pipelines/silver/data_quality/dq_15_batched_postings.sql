-- Error #15: batched and backdated postings. Purchase order lines whose receipt was
-- held and keyed days after the material arrived, in a batch with others, so every lead
-- time computed from them runs long. The late lines come from the receiving record; in
-- the ERP alone the batching shows only as receipts piling up on one weekday.
CREATE OR REFRESH MATERIALIZED VIEW silver.dq_15_batched_postings
COMMENT 'Error 15: batched and backdated postings'
AS
select
    p.po_id,
    p.line,
    p.item_number,
    p.supplier_id,
    p.order_date,
    p.received_date,
    date_format(p.received_date, 'EEEE') as posted_weekday
from silver.stg_erp__purchase_orders p
join silver.stg_truth__batched_receipts b using (po_id, line);
