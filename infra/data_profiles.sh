#!/usr/bin/env bash
# Databricks data profiles for the demand model's monitoring, created with the Databricks CLI by the
# catalog owner once the profiled tables exist (after the first monthly job run in a catalog):
#   gold.reorder_schedule        snapshot profile: the issued reorder points, buffers and lots
#   gold.feature_frame           time series profile on week, monthly: feature drift and data quality
#   monitoring.forecast_errors   inference profile (regression), monthly by origin week: each issued
#                                forecast against its actual once the target window has closed, by
#                                model version, sliced by demand pattern and criticality tier
# Profile outputs go to <catalog>.monitoring; the monthly job's monitor task refreshes all three.
# --check reads them back (read-only).
#
# Optional: DFM_CATALOG (default dfm), DFM_PROFILE_ASSETS (default /Workspace/Shared/dfm_profiles),
# DATABRICKS_CONFIG_PROFILE
set -euo pipefail

CATALOG="${DFM_CATALOG:-dfm}"
ASSETS="${DFM_PROFILE_ASSETS:-/Workspace/Shared/dfm_profiles}"
TABLES="gold.reorder_schedule gold.feature_frame monitoring.forecast_errors"

if [[ "${1:-}" == "--check" ]]; then
  for t in $TABLES; do
    databricks quality-monitors get "$CATALOG.$t" -o json
  done
  exit 0
fi

databricks quality-monitors create "$CATALOG.gold.reorder_schedule" --json '{
  "output_schema_name": "'"$CATALOG"'.monitoring",
  "assets_dir": "'"$ASSETS"'/reorder_schedule",
  "snapshot": {},
  "slicing_exprs": ["criticality"]
}'

databricks quality-monitors create "$CATALOG.gold.feature_frame" --json '{
  "output_schema_name": "'"$CATALOG"'.monitoring",
  "assets_dir": "'"$ASSETS"'/feature_frame",
  "time_series": {"granularities": ["1 month"], "timestamp_col": "week"},
  "slicing_exprs": ["segment"]
}'

databricks quality-monitors create "$CATALOG.monitoring.forecast_errors" --json '{
  "output_schema_name": "'"$CATALOG"'.monitoring",
  "assets_dir": "'"$ASSETS"'/forecast_errors",
  "inference_log": {
    "granularities": ["1 month"],
    "timestamp_col": "origin_ts",
    "model_id_col": "model_version",
    "prediction_col": "forecast",
    "label_col": "actual",
    "problem_type": "PROBLEM_TYPE_REGRESSION"
  },
  "slicing_exprs": ["segment", "tier"]
}'
