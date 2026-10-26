#!/usr/bin/env bash
# The post-update production sequence, from a clean generated state, in the checkout it is
# run from (a worktree for the parity reference):
#   pass 1  generate, validate, remediate, truth, warehouse, marts; the weekly model's
#           steps (baselines, training, three-way, the reference model, explain), whose rule
#           schedule the forward replay keeps; the ladder's reference and S1 rungs; the S1
#           policy on the static horizon, which replaces the reference schedule
#   pass 2  the forward window replayed on the S1 schedule: generate, validate, remediate,
#           truth, warehouse, marts, reliability, financials, the signals monitor
# Pass 2 regenerates in place, so the pass-1 extracts, truth, marts and warehouse are copied
# to runs/seq/pass1/ before it starts.
# Usage: runs/post_update_sequence.sh <pythonhashseed>
set -euo pipefail
HSEED=${1:-1}
REPO=$(pwd)
MAIN=/c/Users/brian/projects/mfg-inventory-forecast
PY=$MAIN/.venv/Scripts/python
DBT=$MAIN/.venv/Scripts/dbt
SEQ=runs/seq
export PYTHONHASHSEED=$HSEED
step(){ echo; echo "=== $(date +%H:%M:%S) $*"; }
# the checkout's own code must be the one imported, never another checkout's
$PY -c "import data_source, os; assert os.path.realpath(data_source.__file__).lower().startswith(os.path.realpath(os.getcwd()).lower()), data_source.__file__"
generate(){
  step "$1 generator";    $PY -u -m data_source.generate.run_generator
  step "$1 validate";     $PY -u -m data_source.generate.validate
  step "$1 remediation";  $PY -u -m data_source.generate.remediation
  step "$1 export_truth"; $PY -u -m data_source.generate.export_truth
  step "$1 dbt";          (cd data_pipeline && $DBT build --profiles-dir . > ../$SEQ/dbt_$1.log 2>&1; tail -1 ../$SEQ/dbt_$1.log)
  step "$1 export_marts"; $PY -u -m ml.src.export_marts
}
step "clean generated state (PYTHONHASHSEED=$HSEED)"
rm -rf data_source/raw data_source/truth ml/data data_pipeline/target data_source/demand_forecasting.duckdb $SEQ
mkdir -p $SEQ
generate pass1
cp data_source/truth/realism_checks.txt $SEQ/pass1_checks.txt
step "pass1 baselines";      $PY -u -m ml.src.baselines
step "pass1 training";       $PY -u -m ml.src.training
step "pass1 training_3way";  $PY -u -m ml.src.training_3way
step "pass1 demand_model";   $PY -u -m ml.src.demand_model
step "pass1 explain_weekly"; $PY -u -m ml.src.explain_weekly
step "pass1 ladder: reference and S1"; $PY -u -m ml.src.signal_ladder --rungs reference S1 --out $SEQ/ladder
step "pass1 S1 policy, static horizon"; $PY -u -m ml.src.signal_policy S1 static $SEQ/policy $SEQ/ladder
cp ml/data/policy/rop_schedule.json $SEQ/reference_rop_schedule.json
cp $SEQ/policy/rop_schedule.json ml/data/policy/rop_schedule.json
step "pass1 state copied to $SEQ/pass1"
mkdir -p $SEQ/pass1/data_source $SEQ/pass1/ml/data
cp -r data_source/raw data_source/truth $SEQ/pass1/data_source/
cp data_source/demand_forecasting.duckdb $SEQ/pass1/data_source/
cp -r ml/data/marts $SEQ/pass1/ml/data/
generate pass2
step "pass2 reliability";    $PY -u -m ml.src.reliability
step "pass2 financials";     $PY -u -m ml.src.financials
step "pass2 signals monitor"
$PY -u -m ml.src.monitor_weekly --signals --ladder $SEQ/ladder --policy $SEQ/policy \
    --forward-results data_source/truth/forward_results.json --out ml/data/monitoring/signals
step done
