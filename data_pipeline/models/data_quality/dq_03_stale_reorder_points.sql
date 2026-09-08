-- Error #3: stale reorder points. Live items whose reorder point on file differs from
-- the point recomputed from actual usage and lead time by at least the configured
-- number of units and share.

select
    item_number,
    abc_class,
    old_reorder_point,
    new_reorder_point,
    new_reorder_point - coalesce(old_reorder_point, 0) as gap_units
from {{ ref('stg_remediation__parameter_recommendations') }}
where abs(new_reorder_point - coalesce(old_reorder_point, 0)) >= {{ var('stale_rop_min_units') }}
  and abs(new_reorder_point - coalesce(old_reorder_point, 0))
      >= {{ var('stale_rop_min_share') }} * greatest(coalesce(old_reorder_point, 0), 1)
