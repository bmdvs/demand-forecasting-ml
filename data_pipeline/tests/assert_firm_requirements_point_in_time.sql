-- No job enters an origin's order book before it was booked, or after it was completed.
select origin, canonical_item_number, order_id, booked_date, completed_date
from {{ ref('int_firm_contributions') }}
where booked_date > origin
   or (completed_date is not null and completed_date < origin)
