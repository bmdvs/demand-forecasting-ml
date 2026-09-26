-- True monthly demand per canonical item: the engine's direct demand plus true backflush,
-- the target the forecast is scored against. Grain: canonical item x month.

with demand as (

    select item_id, month, qty from {{ ref('stg_truth__true_direct_demand') }}
    union all
    select item_id, month, qty from {{ ref('stg_truth__true_backflush') }}

),

survivor as (

    select distinct item_id, canonical_item_number from {{ ref('int_item_crosswalk') }}

)

select
    s.canonical_item_number,
    d.month,
    cast(sum(d.qty) as bigint) as consumption
from demand d
join survivor s using (item_id)
group by 1, 2
