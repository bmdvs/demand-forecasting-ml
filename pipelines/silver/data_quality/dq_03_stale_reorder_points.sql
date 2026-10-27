-- Error #3: stale reorder points. Live items whose reorder point on file differs from
-- the point recomputed from actual usage and lead time by at least 5 units and 30 percent.
CREATE OR REFRESH MATERIALIZED VIEW silver.dq_03_stale_reorder_points
COMMENT 'Error 3: stale reorder points'
AS
select
    item_number,
    abc_class,
    old_reorder_point,
    new_reorder_point,
    new_reorder_point - coalesce(old_reorder_point, 0) as gap_units
from silver.stg_remediation__parameter_recommendations
where abs(new_reorder_point - coalesce(old_reorder_point, 0)) >= 5
  and abs(new_reorder_point - coalesce(old_reorder_point, 0))
      >= 0.30D * greatest(coalesce(old_reorder_point, 0), 1);
