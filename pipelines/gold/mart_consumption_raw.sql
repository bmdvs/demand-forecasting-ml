-- Usage as recorded on each surviving record alone: duplicate history stays split and
-- unrecorded usage stays missing. The uncleaned baseline. Grain: canonical item x month.
CREATE OR REFRESH MATERIALIZED VIEW gold.mart_consumption_raw
COMMENT 'Recorded monthly usage on surviving records'
AS
select
    item_number              as canonical_item_number,
    month,
    cast(bround(sum(units), 0) as bigint) as consumption
from silver.int_recorded_usage
where item_number = canonical_item_number
group by 1, 2;
