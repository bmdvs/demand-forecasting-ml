-- Usage as recorded on each surviving record alone: duplicate history stays split and
-- unrecorded usage stays missing. The uncleaned baseline. Grain: canonical item x month.

select
    item_number              as canonical_item_number,
    month,
    cast(sum(units) as bigint) as consumption
from {{ ref('int_recorded_usage') }}
where item_number = canonical_item_number
group by 1, 2
