-- No receipt dated on or after the week enters that week's lead-time statistics.
select key_type, key_id, week, last_receipt_date
from {{ ref('int_leadtime_weekly') }}
where last_receipt_date >= week
