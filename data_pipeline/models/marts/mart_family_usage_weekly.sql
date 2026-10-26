-- Weekly usage by item family (int_item_family), the fully cleaned series summed over the
-- family's items, with the number of items. Grain: family x week.

select
    f.family,
    w.week,
    count(distinct f.canonical_item_number)                as n_items,
    coalesce(sum(c.consumption), 0)                        as family_usage
from {{ ref('int_item_family') }} f
cross join {{ ref('dim_week') }} w
left join {{ ref('mart_consumption_weekly') }} c
  on c.canonical_item_number = f.canonical_item_number and c.week = w.week
group by 1, 2
