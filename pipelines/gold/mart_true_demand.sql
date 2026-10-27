-- True monthly demand per canonical item: direct demand plus true backflush, the target
-- the forecast is scored against. Grain: canonical item x month.
CREATE OR REFRESH MATERIALIZED VIEW gold.mart_true_demand (
  CONSTRAINT canonical_item_number_not_null EXPECT (canonical_item_number IS NOT NULL)
)
COMMENT 'True monthly demand by canonical item'
AS
with demand as (
    select item_id, month, qty from silver.stg_truth__true_direct_demand
    union all
    select item_id, month, qty from silver.stg_truth__true_backflush
),
survivor as (
    select distinct item_id, canonical_item_number from silver.int_item_crosswalk
)
select
    s.canonical_item_number,
    d.month,
    cast(sum(d.qty) as bigint) as consumption
from demand d
join survivor s using (item_id)
group by 1, 2;
