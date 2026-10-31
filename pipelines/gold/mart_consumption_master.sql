-- Usage with duplicate records merged to their canonical item (master-level cleaning).
-- Grain: canonical item x month.
CREATE OR REFRESH MATERIALIZED VIEW gold.mart_consumption_master
COMMENT 'Master-cleaned monthly usage'
AS
select
    canonical_item_number,
    month,
    cast(bround(sum(units), 0) as bigint) as consumption
from silver.int_recorded_usage
group by 1, 2;
