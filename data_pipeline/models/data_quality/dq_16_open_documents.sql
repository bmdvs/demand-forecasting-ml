-- Error #16: open documents never closed. Purchase order lines left open after they were
-- effectively complete, which leaves phantom material on order, and production jobs
-- still open past their due date at the close of the history.

select
    'PO'                                     as document_type,
    po_id                                    as document_id,
    line,
    order_date                               as document_date,
    qty_ordered - coalesce(qty_received, 0)  as open_qty
from {{ ref('stg_erp__purchase_orders') }}
where status = 'OPEN'

union all

select
    'JOB',
    order_id,
    null,
    due_date,
    qty_ordered - qty_completed
from {{ ref('stg_erp__production_orders') }}
where status = 'OPEN'
  and due_date < cast('{{ var("history_end") }}' as date)
