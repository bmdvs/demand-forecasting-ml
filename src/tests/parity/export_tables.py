"""Export Unity Catalog tables to local Parquet through a SQL warehouse, for the parity comparison.

Each table is read with the Statement Execution API (Arrow results, external links) and written to
<out>/<table>.parquet. Uses the Databricks CLI for authenticated calls; the result chunks are
downloaded from their pre-signed links without credentials. The warehouse id comes from the
environment (DFM_WAREHOUSE_ID) or --warehouse-id, never from the repository. The warehouse is
stopped at the end unless --keep-running is given.

Usage:
  python src/tests/parity/export_tables.py --profile PROFILE --catalog dfm_dev --schemas silver,gold --out DIR
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
import requests


def cli(profile: str, *args: str, body: dict | None = None) -> dict:
    cmd = ["databricks", "--profile", profile, *args]
    if body is not None:
        cmd += ["--json", json.dumps(body)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}: {r.stderr.strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else {}


def statement(profile: str, warehouse: str, sql: str) -> pa.Table:
    res = cli(profile, "api", "post", "/api/2.0/sql/statements", body={
        "warehouse_id": warehouse, "statement": sql, "wait_timeout": "30s",
        "disposition": "EXTERNAL_LINKS", "format": "ARROW_STREAM"})
    sid = res["statement_id"]
    while res["status"]["state"] in ("PENDING", "RUNNING"):
        time.sleep(2)
        res = cli(profile, "api", "get", f"/api/2.0/sql/statements/{sid}")
    if res["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(f"{sql}: {res['status']}")
    batches = []
    schema = None
    chunk = res.get("result", {})
    while True:
        for link in chunk.get("external_links", []):
            data = requests.get(link["external_link"], timeout=300)
            data.raise_for_status()
            reader = ipc.open_stream(io.BytesIO(data.content))
            schema = reader.schema
            batches.extend(reader)
        nxt = (chunk.get("external_links") or [{}])[-1].get("next_chunk_internal_link")
        if not nxt:
            break
        chunk = cli(profile, "api", "get", nxt)
    if schema is None:
        # empty result: no chunks; build the schema from the manifest
        cols = res["manifest"]["schema"]["columns"]
        return pa.table({c["name"]: pa.array([], pa.string()) for c in cols})
    return pa.Table.from_batches(batches, schema=schema)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE", "DEFAULT"))
    p.add_argument("--warehouse-id", default=os.environ.get("DFM_WAREHOUSE_ID"))
    p.add_argument("--catalog", required=True)
    p.add_argument("--schemas", default="silver,gold")
    p.add_argument("--tables", help="comma-separated schema.table names instead of whole schemas")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--keep-running", action="store_true")
    a = p.parse_args()
    if not a.warehouse_id:
        raise SystemExit("set DFM_WAREHOUSE_ID or pass --warehouse-id")
    a.out.mkdir(parents=True, exist_ok=True)
    if a.tables:
        names = a.tables.split(",")
    else:
        names = []
        for s in a.schemas.split(","):
            listed = cli(a.profile, "tables", "list", a.catalog, s, "-o", "json")
            names += [f"{s}.{t['name']}" for t in (listed if isinstance(listed, list) else listed.get("tables", []))]
    t0 = time.time()
    try:
        for n in sorted(names):
            table = statement(a.profile, a.warehouse_id, f"SELECT * FROM {a.catalog}.{n}")
            pq.write_table(table, a.out / f"{n.split('.')[1]}.parquet")
            print(f"  {n:55s} {table.num_rows:>9,} rows")
    finally:
        if not a.keep_running:
            cli(a.profile, "warehouses", "stop", a.warehouse_id, "--no-wait")
            print("warehouse stop requested")
    print(f"{len(names)} tables in {time.time() - t0:.0f}s -> {a.out}")


if __name__ == "__main__":
    main()
