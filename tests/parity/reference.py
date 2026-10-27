"""Export every warehouse model of an archived DuckDB build to Parquet, as the parity reference.

The archive's warehouse holds the dbt models as tables and views; the views read the archived
CSV extracts through relative paths, so they are evaluated with the archive as the working root.
Time-of-day values are written as HH:MM:SS text, the representation the pipeline carries.

Usage:
  python tests/parity/reference.py --pass pass1|pass2 [--out runs/parity/reference]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
ARCHIVES = {
    "pass1": Path(os.environ.get("DFM_PASS1_ROOT", REPO / "reference" / "2026-10_post_signal_update_pass1")),
    "pass2": Path(os.environ.get("DFM_PASS2_ROOT", REPO / "reference" / "2026-10_post_signal_update")),
}


def export(pass_name: str, out_root: Path) -> dict:
    archive = ARCHIVES[pass_name]
    out = out_root / pass_name
    out.mkdir(parents=True, exist_ok=True)
    warehouse = archive / "data_source" / "demand_forecasting.duckdb"
    cwd = os.getcwd()
    # the views resolve ../data_source/... from the working directory
    os.chdir(archive / "ml")
    try:
        con = duckdb.connect(str(warehouse), read_only=True)
        models = [r[0] for r in con.execute(
            "select table_name from information_schema.tables where table_schema = 'main' order by 1").fetchall()]
        summary = {}
        for m in models:
            cols = con.execute(
                "select column_name, data_type from information_schema.columns "
                f"where table_schema = 'main' and table_name = '{m}' order by ordinal_position").fetchall()
            select = ", ".join(
                f'cast("{c}" as varchar) as "{c}"' if t == "TIME"
                else f'cast("{c}" as bigint) as "{c}"' if t == "HUGEINT"
                else f'"{c}"' for c, t in cols)
            path = out / f"{m}.parquet"
            con.execute(f'copy (select {select} from "{m}") to \'{path.as_posix()}\' (format parquet)')
            summary[m] = {"rows": con.execute(f'select count(*) from "{m}"').fetchone()[0],
                          "types": dict(cols)}
        con.close()
    finally:
        os.chdir(cwd)
    (out / "_reference.json").write_text(json.dumps(
        {"archive": str(archive), "models": summary}, indent=1))
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pass", dest="pass_name", choices=sorted(ARCHIVES), required=True)
    p.add_argument("--out", type=Path, default=REPO / "runs" / "parity" / "reference")
    a = p.parse_args()
    s = export(a.pass_name, a.out)
    print(f"{a.pass_name}: {len(s)} models, {sum(v['rows'] for v in s.values()):,} rows -> {a.out / a.pass_name}")


if __name__ == "__main__":
    main()
