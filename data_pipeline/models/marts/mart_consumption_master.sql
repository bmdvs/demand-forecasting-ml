-- Usage with duplicate records merged to their canonical item (master-level cleaning).
-- Grain: canonical item x month.

select
    canonical_item_number,
    month,
    cast(sum(units) as bigint) as consumption
from {{ ref('int_recorded_usage') }}
group by 1, 2
