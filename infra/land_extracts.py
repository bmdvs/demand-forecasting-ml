"""Land the source-system extracts in the Unity Catalog landing volume as Parquet.

Each CSV extract (ERP, WMS, purchasing, remediation records and the reference data) is checked against
its archive's sha256 manifest, read with the same type inference the warehouse's sources use
(DuckDB read_csv_auto), written as Parquet with microsecond timestamps and uploaded to
/Volumes/<catalog>/landing/exports/<source>/<table>/<pass>/<table>.parquet. Columns inferred as a time
of day are kept as the extract's text. After each upload the file is read back from the volume and
its checksum and row count are compared with the local file. A landing manifest (source checksum, rows,
column types, Parquet checksum, volume path) is written to the volume under _manifest/ and locally.

Usage:
  python infra/land_extracts.py --profile PROFILE [--catalog dfm] [--pass pass1|pass2|all]
  python infra/land_extracts.py --profile PROFILE --check [--pass ...]   read-only: verify the volume
                                                                          against the landing manifest
Environment: DFM_PASS1_ROOT, DFM_PASS2_ROOT override the archive folders.
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

import duckdb
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
ARCHIVES = {
    "pass1": Path(os.environ.get("DFM_PASS1_ROOT", REPO / "reference" / "2026-10_post_signal_update_pass1")),
    "pass2": Path(os.environ.get("DFM_PASS2_ROOT", REPO / "reference" / "2026-10_post_signal_update")),
}
LOCAL_MANIFESTS = REPO / "runs" / "landing"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extracts(archive: Path) -> list[tuple[str, str, Path]]:
    """(source, table, csv path) for every CSV extract in an archive, in a fixed order."""
    base = archive / "data_source"
    out = [(p.parent.name, p.stem, p) for p in sorted((base / "raw").glob("*/*.csv"))]
    out += [("truth", p.stem, p) for p in sorted((base / "truth").glob("*.csv"))]
    return out


def read_extract(con: duckdb.DuckDBPyConnection, csv: Path):
    """The extract as an Arrow table with the warehouse's inferred types; time-of-day columns stay text."""
    src = csv.as_posix()
    inferred = con.execute(f"DESCRIBE SELECT * FROM read_csv_auto('{src}')").fetchall()
    as_text = {c[0]: "VARCHAR" for c in inferred if c[1].startswith("TIME") and not c[1].startswith("TIMESTAMP")}
    opts = f", types={json.dumps(as_text)}" if as_text else ""
    table = con.execute(f"SELECT * FROM read_csv_auto('{src}'{opts})").to_arrow_table()
    return table, sorted(as_text)


def db(profile: str, *args: str) -> str:
    r = subprocess.run(["databricks", "--profile", profile, *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"databricks {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def volume_root(catalog: str) -> str:
    return f"dbfs:/Volumes/{catalog}/landing/exports"


def read_back(profile: str, remote: str, tmp: Path) -> tuple[str, int, int]:
    """Download a landed file and return its checksum, bytes and Parquet row count."""
    local = tmp / ("readback_" + remote.rsplit("/", 1)[-1])
    db(profile, "fs", "cp", remote, str(local), "--overwrite")
    out = (sha256(local), local.stat().st_size, pq.ParquetFile(local).metadata.num_rows)
    local.unlink()
    return out


def land(profile: str, catalog: str, pass_name: str) -> dict:
    archive = ARCHIVES[pass_name]
    files = json.loads((archive / "MANIFEST.json").read_text())["files"]
    con = duckdb.connect()
    entries = []
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        for source, table, csv in extracts(archive):
            rel = csv.relative_to(archive).as_posix()
            csv_sha = sha256(csv)
            if files.get(rel, {}).get("sha256") != csv_sha:
                raise RuntimeError(f"{rel}: checksum does not match {archive / 'MANIFEST.json'}")
            arrow, text_cols = read_extract(con, csv)
            rows = con.execute(f"SELECT count(*) FROM read_csv_auto('{csv.as_posix()}')").fetchone()[0]
            local = tmp / f"{table}.parquet"
            pq.write_table(arrow, local, coerce_timestamps="us", allow_truncated_timestamps=False)
            if pq.ParquetFile(local).metadata.num_rows != rows or arrow.num_rows != rows:
                raise RuntimeError(f"{rel}: row count changed in conversion")
            remote = f"{volume_root(catalog)}/{source}/{table}/{pass_name}/{table}.parquet"
            db(profile, "fs", "mkdir", remote.rsplit("/", 1)[0])
            db(profile, "fs", "cp", str(local), remote, "--overwrite")
            p_sha, p_bytes = sha256(local), local.stat().st_size
            r_sha, r_bytes, r_rows = read_back(profile, remote, tmp)
            if (r_sha, r_bytes, r_rows) != (p_sha, p_bytes, rows):
                raise RuntimeError(f"{remote}: read-back mismatch")
            entries.append({
                "source": source, "table": table, "pass": pass_name, "csv": rel, "csv_sha256": csv_sha,
                "rows": rows, "columns": {f.name: str(f.type) for f in arrow.schema},
                "kept_as_text": text_cols, "parquet_bytes": p_bytes, "parquet_sha256": p_sha,
                "path": remote.removeprefix("dbfs:"),
            })
            print(f"  {pass_name} {source}/{table}: {rows:,} rows, {p_bytes:,} bytes, read back ok")
    manifest = {"landed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "catalog": catalog,
                "pass": pass_name, "archive": archive.relative_to(REPO).as_posix() if archive.is_relative_to(REPO) else str(archive),
                "archive_git_commit": json.loads((archive / "MANIFEST.json").read_text()).get("git_commit"),
                "files": entries}
    LOCAL_MANIFESTS.mkdir(parents=True, exist_ok=True)
    local_manifest = LOCAL_MANIFESTS / f"landing_{catalog}_{pass_name}.json"
    local_manifest.write_text(json.dumps(manifest, indent=1))
    db(profile, "fs", "mkdir", f"{volume_root(catalog)}/_manifest")
    db(profile, "fs", "cp", str(local_manifest), f"{volume_root(catalog)}/_manifest/landing_{pass_name}.json", "--overwrite")
    return manifest


def check(profile: str, catalog: str, pass_name: str) -> bool:
    """Read-only: every file in the landing manifest is in the volume with its checksum and row count,
    and the volume holds no other Parquet file for this pass."""
    manifest = json.loads((LOCAL_MANIFESTS / f"landing_{catalog}_{pass_name}.json").read_text())
    ok = True
    expected = {e["path"] for e in manifest["files"]}
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        for e in manifest["files"]:
            r_sha, r_bytes, r_rows = read_back(profile, "dbfs:" + e["path"], tmp)
            good = (r_sha, r_bytes, r_rows) == (e["parquet_sha256"], e["parquet_bytes"], e["rows"])
            ok &= good
            print(f"  {'ok  ' if good else 'DIFF'} {e['path']} rows {r_rows:,}")
    found = set()
    for source in sorted({e["source"] for e in manifest["files"]}):
        for entry in json.loads(db(profile, "fs", "ls", f"{volume_root(catalog)}/{source}", "-o", "json") or "[]"):
            table = entry["name"].rstrip("/").split("/")[-1]
            sub = f"{volume_root(catalog)}/{source}/{table}/{pass_name}"
            try:
                listed = json.loads(db(profile, "fs", "ls", sub, "-o", "json") or "[]")
            except RuntimeError:
                continue
            found |= {f"/Volumes/{catalog}/landing/exports/{source}/{table}/{pass_name}/{x['name'].split('/')[-1]}"
                      for x in listed}
    extra = sorted(found - expected)
    if extra:
        ok = False
        print("  files in the volume not in the manifest:", extra)
    return ok


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE", "DEFAULT"))
    p.add_argument("--catalog", default="dfm")
    p.add_argument("--pass", dest="pass_name", choices=["pass1", "pass2", "all"], default="all")
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    passes = ["pass1", "pass2"] if a.pass_name == "all" else [a.pass_name]
    if a.check:
        results = [check(a.profile, a.catalog, ps) for ps in passes]
        sys.exit(0 if all(results) else 1)
    for ps in passes:
        m = land(a.profile, a.catalog, ps)
        print(f"{ps}: {len(m['files'])} extracts, {sum(e['rows'] for e in m['files']):,} rows, "
              f"{sum(e['parquet_bytes'] for e in m['files']):,} bytes")


if __name__ == "__main__":
    main()
