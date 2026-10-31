# Platform setup and operation

The demand-forecasting platform runs on Azure Databricks: Unity Catalog for storage, a Lakeflow pipeline for the warehouse (`resources/pipeline.yml`, sources in `pipelines/`) and the monthly job `dfm_monthly` for the model (`resources/jobs.yml`, package in `src/dfm/`). Both are deployed as one Databricks Asset Bundle (`databricks.yml`). This folder holds the setup and maintenance scripts. Workspace hosts, application ids, subscription ids and secrets come from the environment or a CLI profile and are never written to the repository.

## Scripts, in setup order

| Script | What it does | Run as |
|---|---|---|
| `unity_catalog.sh [PROFILE] [--check \| --dev \| --dev-check]` | Creates the catalog, the six schemas (`landing`, `bronze`, `silver`, `gold`, `ml`, `monitoring`) and the landing volume, or the development catalog; `--check` and `--dev-check` verify an existing setup read-only. The storage credential and external locations are shared and only verified. Needs `DFM_STORAGE_ACCOUNT` | catalog owner |
| `grant_deploy_sp.sh [--apply \| --check]` | Grants the deploy service principal what the prod job needs on the catalog (prints the SQL by default). Needs `DFM_DEPLOY_SP` | catalog owner |
| `land_extracts.py --profile PROFILE [--pass pass1\|pass2\|all] [--check]` | Lands the source extracts as Parquet in the landing volume with checksum and read-back verification, plus the forward-window results file, and writes a landing manifest | catalog owner |
| `build_wheel.py` | Builds the `dfm` wheel into an emptied `dist/bundle/`; the bundle runs it on every deploy | (bundle) |
| `data_profiles.sh [--check]` | Creates the three data profiles (`gold.reorder_schedule` snapshot, `gold.feature_frame` time series, `monitoring.forecast_errors` inference) after the first monthly run in a catalog; the monitor task refreshes them each month | the deploy service principal on prod (`DATABRICKS_CONFIG_PROFILE`), see below |
| `export_gold_snapshot.py --profile PROFILE --version ... --issued-run ... --monitor-run ...` | Exports `exports/gold_snapshot/`: the gold tables the report generators read, the monitoring tables, the registry's version tags and the forward replay, as Parquet and CSV with a manifest. Needs `DFM_WAREHOUSE_ID` | a reader of `gold` and `monitoring` |

## Deploying

```bash
databricks bundle deploy -t dev
```

```bash
databricks bundle deploy -t prod
```

- **dev** deploys under the deploying user (`[dev <user>]` names, catalog `dfm_dev`, landing pass `pass1`), so the parity sequence can be rerun there.
- **prod** deploys under `/Workspace/Shared/.bundle/dfm/prod`, catalog `dfm`, landing pass `pass2` (the final extracts, prod's standing state). The job runs as the deploy service principal, whose application id is passed as `BUNDLE_VAR_deploy_sp`. Prod is deployed as that service principal, from CI (`.github/workflows/ci.yml`, with the workspace host, client id and client secret as repository secrets) or from a CLI profile holding its OAuth credentials. Deploying as a user would need the `servicePrincipal.user` role on the service principal to set the job's run-as identity.
- Changing a target's landing pass is a full refresh of its pipeline: `databricks pipelines start-update <pipeline id> --full-refresh`.
- A deploy builds the wheel; `exports/` is not synced to the workspace.

## Standing permission rules

1. **A bundle resource first created by a user and later managed by the service principal needs that principal to hold CAN_MANAGE on it.** The prod pipeline was created by a user deploy, and the service principal's first deploy was refused until it held CAN_MANAGE on the pipeline (`databricks pipelines update-permissions`). The same applies to anything else created by hand before a service-principal deploy. The owner does not change.
2. **Tables written by the job belong to the service principal.** Its tasks overwrite with a schema replace, so it owns `gold.feature_frame`, `backtest_predictions`, `weekly_backtest`, `reorder_schedule`, `reorder_queue`, `policy_retrains`, the monitoring tables and the profile outputs, and the registered model `ml.demand_models`. The catalog owner does not read them by ownership: readers hold SELECT on the `gold` and `monitoring` schemas.
3. **Data profiles on prod are created as the service principal**, which owns the profiled tables, so no MANAGE grant is needed and the monitor task refreshes them as their owner.
4. The pipeline runs as its owner; changing a pipeline's owner or run-as identity needs a metastore admin.

## First run in a new catalog

The registry starts empty, so the first `dfm_monthly` run registers version 1 and the promotion step stops: the bias gate fails closed (no champion), and there is no `champion` alias to score with. Set the alias by hand and repair the run from `promote`, passing the job parameters explicitly:

```bash
databricks registered-models set-alias <catalog>.ml.demand_models champion 1
```

```bash
databricks jobs repair-run --json '{"run_id": <run id>, "rerun_tasks": ["promote", "score", "monitor"], "job_parameters": {"auto_promote": "true"}}'
```

On the repair, `promote` reuses version 1. From then on `champion` moves only when every gate passes and `auto_promote` is true. The bias gate judges the schedule in force on its latest month with 80% of its forecasts matured, so it fails closed until a schedule has been issued and has matured. Create the data profiles once the first run has written the profiled tables.

## Cost and budget

- Data is small (about 190,000 ledger rows, 1,300 items, 184 weeks). A monthly run is about 55 minutes on one `Standard_D4ds_v5` node (train 30 to 35 minutes, score about 15), plus a serverless pipeline update of about 4 minutes and three profile refreshes. A full refresh of the pipeline takes a few minutes on serverless.
- Job clusters bill as virtual machines in the workspace's managed resource group (`databricks-rg-*`), not in the workspace's own resource group. A budget scoped to the workspace's resource group misses them: the budget belongs at subscription scope (alerts at $25 and $50).
- The workspace's DBU trial ends about 2026-11-05; after that DBUs are pay-as-you-go on top of the virtual machine and storage cost.
- Stop the SQL warehouse and any all-purpose cluster after interactive use.
