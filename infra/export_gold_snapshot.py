"""Export the gold snapshot the report generators read, as Parquet and CSV with a manifest.

Contents (docs/data/gold_snapshot/):
  tables/      the gold tables the generators read (and the item crosswalk from silver), each at the Delta
               version of the run whose outputs the deliverables describe: the warehouse marts as the final
               pipeline update left them, the model tables of the run that issued the schedule in force
  monitoring/  the nine monitoring tables of the monitor run that judged that schedule
  registry/    the registered model's version tags and aliases
  replay/      the forward replay's three variants (status quo, cleaned records with the recomputed rule,
               the model) by window and by month, flattened from the landed forward results
  MANIFEST.json  for every file: source (table and Delta version, or API, or landed file), rows, columns,
                 bytes, sha256, and the generator input it stands for

The Delta versions come from the command line, so the snapshot names exactly what it read. Reads go
through a SQL warehouse (DFM_WAREHOUSE_ID or --warehouse-id, never from the repository), which is
stopped at the end.

Usage:
  python infra/export_gold_snapshot.py --profile PROFILE --catalog dfm --version gold.weekly_backtest=1 \
      --version gold.reorder_schedule=1 --version gold.reorder_queue=1 --issued-run JOB_RUN_ID \
      --monitor-run JOB_RUN_ID --pass pass2 [--out docs/data/gold_snapshot]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "tests" / "parity"))
import export_tables as E  # noqa: E402  (the statement API reader shared with the parity runner)

MODEL = "ml.demand_models"
# (schema.table, the file the report generators read in the local sequence, what the table is)
TABLES = [
    ("gold.mart_consumption_weekly", "ml/data/marts/consumption_weekly.parquet", "weekly consumption by item"),
    ("gold.mart_consumption_fully", "ml/data/marts/consumption_monthly.parquet", "monthly consumption, fully cleaned"),
    ("gold.mart_item_attributes", "ml/data/marts/item_attributes.parquet", "item attributes"),
    ("silver.int_item_crosswalk", "ml/data/marts/item_crosswalk.csv", "item number to canonical item (silver)"),
    ("gold.mart_dq_error_summary", "warehouse mart_dq_error_summary", "data quality error register"),
    ("gold.weekly_backtest", "ml/data/backtest/weekly_backtest.parquet", "weekly model backtest"),
    ("gold.reorder_schedule", "ml/data/policy/rop_schedule.json", "reorder schedule, one row per item per Monday"),
    ("gold.reorder_queue", "the ERP reorder queue page", "as-of reorder queue"),
]
MODEL_TABLES = {"gold.weekly_backtest", "gold.reorder_schedule", "gold.reorder_queue"}
MONITORING = ["monthly_status", "pattern_metrics", "cell_bias", "feature_drift", "bias_factors",
              "lead_time_reviews", "retrain_log", "forecast_errors", "monitoring_summary"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(table: pa.Table, folder: Path, name: str) -> list[dict]:
    """Parquet (microsecond timestamps) and CSV of one table; the manifest's file entries."""
    folder.mkdir(parents=True, exist_ok=True)
    pqp, csvp = folder / f"{name}.parquet", folder / f"{name}.csv"
    pq.write_table(table, pqp, coerce_timestamps="us", allow_truncated_timestamps=False)
    table.to_pandas().to_csv(csvp, index=False, lineterminator="\n")
    cols = [{"name": f.name, "type": str(f.type)} for f in table.schema]
    return [{"file": str(p.relative_to(folder.parent)).replace("\\", "/"), "bytes": p.stat().st_size,
             "sha256": sha(p), "rows": table.num_rows, "columns": cols} for p in (pqp, csvp)]


def flatten(prefix: str, v, out: dict) -> None:
    if isinstance(v, dict):
        for k, x in v.items():
            flatten(f"{prefix}.{k}" if prefix else str(k), x, out)
    else:
        out[prefix] = v


def replay_rows(fr: dict) -> pd.DataFrame:
    """The forward replay's variants as rows: window or month, variant, metric path, value."""
    rows = []
    for scope, block in [("window", fr["forward"]), ("month", fr["monthly"])]:
        for period, variants in block.items():
            for variant, metrics in variants.items():
                flat: dict = {}
                flatten("", metrics, flat)
                for m, x in flat.items():
                    num = isinstance(x, (int, float)) and not isinstance(x, bool)
                    rows.append({"scope": scope, "period": period, "variant": variant, "metric": m,
                                 "value": float(x) if num else None, "text": None if num else str(x)})
    return pd.DataFrame(rows)


def registry_rows(profile: str, catalog: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    name = f"{catalog}.{MODEL}"
    res = E.cli(profile, "api", "get", f"/api/2.1/unity-catalog/models/{name}?include_aliases=true")
    aliases = pd.DataFrame([{"alias": a["alias_name"], "version": int(a["version_num"])} for a in res.get("aliases", [])])
    vers = E.cli(profile, "api", "get", f"/api/2.1/unity-catalog/models/{name}/versions")
    rows = []
    for v in sorted(int(x["version"]) for x in vers.get("model_versions", [])):
        mv = E.cli(profile, "api", "get", f"/api/2.0/mlflow/unity-catalog/model-versions/get?name={name}&version={v}")
        for t in sorted(mv["model_version"].get("tags", []), key=lambda t: t["key"]):
            rows.append({"version": v, "key": t["key"], "value": t["value"]})
    return pd.DataFrame(rows), aliases


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE", "DEFAULT"))
    ap.add_argument("--warehouse-id", default=os.environ.get("DFM_WAREHOUSE_ID"))
    ap.add_argument("--catalog", default="dfm")
    ap.add_argument("--version", action="append", default=[], help="schema.table=DELTA_VERSION (model tables)")
    ap.add_argument("--issued-run", required=True, help="job run that wrote the model tables at those versions")
    ap.add_argument("--monitor-run", required=True, help="job run whose monitor wrote the monitoring tables")
    ap.add_argument("--pass", dest="pass_name", default="pass2", help="landing pass of the warehouse tables")
    ap.add_argument("--landing-root", default="/Volumes/dfm/landing/exports")
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "data" / "gold_snapshot")
    a = ap.parse_args()
    if not a.warehouse_id:
        raise SystemExit("set DFM_WAREHOUSE_ID or pass --warehouse-id")
    versions = dict(v.split("=") for v in a.version)
    missing = MODEL_TABLES - versions.keys()
    if missing:
        raise SystemExit(f"--version required for {sorted(missing)}")
    out = a.out
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    try:
        for t, reads, what in TABLES:
            v = versions.get(t)
            sql = f"SELECT * FROM {a.catalog}.{t}" + (f" VERSION AS OF {int(v)}" if v is not None else "")
            tab = E.statement(a.profile, a.warehouse_id, sql)
            src = {"table": f"{a.catalog}.{t}", "delta_version": int(v) if v is not None else "current",
                   "job_run": a.issued_run if t in MODEL_TABLES else None,
                   "pass": "pass1 model, issued schedule" if t in MODEL_TABLES else a.pass_name}
            entries.append({"name": t.split(".")[1], "what": what, "read_by_generators_as": reads, "source": src,
                            "files": write(tab, out / "tables", t.split(".")[1])})
            print(f"  {t:36s} {tab.num_rows:>9,} rows  version {src['delta_version']}")
        for m in MONITORING:
            tab = E.statement(a.profile, a.warehouse_id, f"SELECT * FROM {a.catalog}.monitoring.{m}")
            entries.append({"name": m, "what": "monitoring table", "read_by_generators_as": "ml/data/monitoring/signals",
                            "source": {"table": f"{a.catalog}.monitoring.{m}", "delta_version": "current",
                                       "job_run": a.monitor_run, "pass": a.pass_name},
                            "files": write(tab, out / "monitoring", m)})
            print(f"  monitoring.{m:25s} {tab.num_rows:>9,} rows")
    finally:
        E.cli(a.profile, "warehouses", "stop", a.warehouse_id, "--no-wait")
        print("warehouse stop requested")
    tags, aliases = registry_rows(a.profile, a.catalog)
    for name, df in [("version_tags", tags), ("aliases", aliases)]:
        entries.append({"name": name, "what": f"{a.catalog}.{MODEL} {name.replace('_', ' ')}",
                        "read_by_generators_as": None,
                        "source": {"api": "Unity Catalog model registry", "model": f"{a.catalog}.{MODEL}"},
                        "files": write(pa.Table.from_pandas(df, preserve_index=False), out / "registry", name)})
        print(f"  registry.{name:27s} {len(df):>9,} rows")
    vol = f"{a.landing_root}/truth/forward_results/{a.pass_name}/forward_results.json"
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "forward_results.json"
        r = subprocess.run(["databricks", "--profile", a.profile, "fs", "cp", f"dbfs:{vol}", str(local)],
                           capture_output=True, text=True, env={**os.environ, "MSYS_NO_PATHCONV": "1"})
        if r.returncode != 0:
            raise SystemExit(f"forward results: {r.stderr.strip()}")
        fr_sha = sha(local)
        df = replay_rows(json.loads(local.read_text(encoding="utf-8")))
    entries.append({"name": "forward_replay", "what": "forward replay by window and month: dirty (status quo), "
                    "clean_rule (cleaned records, recomputed rule), model",
                    "read_by_generators_as": "data_source/truth/forward_results.json (forward, monthly)",
                    "source": {"landed_file": vol, "sha256": fr_sha, "pass": a.pass_name},
                    "files": write(pa.Table.from_pandas(df, preserve_index=False), out / "replay", "forward_replay")})
    print(f"  replay.forward_replay              {len(df):>9,} rows")
    manifest = {"created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "catalog": a.catalog,
                "issued_run": a.issued_run, "monitor_run": a.monitor_run, "pass": a.pass_name, "entries": entries}
    (out / "MANIFEST.json").write_bytes((json.dumps(manifest, indent=1) + "\n").encode("utf-8"))
    n = sum(len(e["files"]) for e in entries)
    print(f"{len(entries)} entries, {n} files -> {out}")


if __name__ == "__main__":
    main()
