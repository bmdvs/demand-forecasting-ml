#!/usr/bin/env bash
# One forward replay of a reorder schedule, in the replay worktree.
# Usage: runs/forward_replay.sh <name> <rop_schedule.json>
set -euo pipefail
NAME=$1; SCHED=$2
MAIN=/c/Users/brian/projects/mfg-inventory-forecast
WT=/c/Users/brian/projects/mfg-inventory-forecast-replay
PY=$MAIN/.venv/Scripts/python
DBT=$MAIN/.venv/Scripts/dbt
OUT=$MAIN/runs/forward/$NAME
mkdir -p "$OUT"
cd "$WT"
export PYTHONHASHSEED=1
mkdir -p ml/data/policy
cp "$SCHED" ml/data/policy/rop_schedule.json
cp "$MAIN/runs/run05c/pass1_model/policy/rule_schedule.json" ml/data/policy/rule_schedule.json
echo "=== $(date +%H:%M:%S) $NAME generator"
mkdir -p runs && cp "$MAIN/runs/replay_generator.py" runs/replay_generator.py
# run as a module from the worktree so its own data_source is imported, never the main checkout's
$PY -c "import data_source, sys; assert 'replay' in data_source.__file__, data_source.__file__"
$PY -u -m runs.replay_generator "$OUT/drift_items.json" > "$OUT/generator.log" 2>&1
echo "=== $(date +%H:%M:%S) $NAME validate, remediation, truth, warehouse"
$PY -u -m data_source.generate.validate > "$OUT/validate.log" 2>&1
$PY -u -m data_source.generate.remediation > /dev/null 2>&1
$PY -u -m data_source.generate.export_truth > /dev/null 2>&1
(cd data_pipeline && $DBT build --profiles-dir . > "$OUT/dbt.log" 2>&1; tail -1 "$OUT/dbt.log")
cp data_source/truth/forward_results.json data_source/truth/signal_checks.json data_source/truth/realism_checks.txt "$OUT/"
(cd data_pipeline && $PY - "$OUT/active_short.json" <<'EOF'
import duckdb, json, sys
c = duckdb.connect("../data_source/demand_forecasting.duckdb", read_only=True)
v = c.execute("""select avg(case when short_active_week then 1.0 else 0 end), avg(case when short_week then 1.0 else 0 end)
                 from mart_shortage_weekly where week >= date '2026-01-05' and week < date '2026-07-01'""").fetchone()
json.dump({"active_short_share_forward": v[0], "short_share_forward": v[1]}, open(sys.argv[1], "w"))
print("active-short share forward", round(v[0] * 100, 2), "%")
EOF
)
echo "=== $(date +%H:%M:%S) $NAME done"
