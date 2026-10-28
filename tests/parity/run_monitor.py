"""The package's monitor on an archive, and its outputs against the archived monitor outputs.

Issued schedule: the archive's pass-1 ladder (metrics_S1.json, pred_S1.parquet) and policy
(rop_schedule.json, retrain_log.json), as the sequence passed them to the monitor. Current tables: the
archive's mart files and extracts; data quality from the archive's warehouse file (its staging views read
the extracts at ../data_source, so the file is opened from a scratch folder whose data_source points at
the archive's). Forward results: the archive's truth file.

Usage: python tests/parity/run_monitor.py --archive DIR --out DIR [--reference DIR] [--scratch DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfm import monitoring as M  # noqa: E402
from dfm import store as S  # noqa: E402
from dfm import tasks  # noqa: E402
from dfm import training as T  # noqa: E402

CSVS = ["feature_drift", "retrain_log", "bias_factors", "lead_time_reviews"]


def warehouse_tables(archive: Path, scratch: Path) -> dict[str, pd.DataFrame]:
    """The data-quality inputs from the archive's DuckDB file."""
    import duckdb

    base = scratch / archive.name
    (base / "data_pipeline").mkdir(parents=True, exist_ok=True)
    link = base / "data_source"
    if not link.exists():
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(archive / "data_source")], check=True,
                       capture_output=True)
    cwd = os.getcwd()
    os.chdir(base / "data_pipeline")
    try:
        con = duckdb.connect(str(archive / "data_source" / "demand_forecasting.duckdb"), read_only=True)
        q = {"shortage": "select week, short_week, short_active_week from mart_shortage_weekly",
             "corrected": "select canonical_item_number, item_number, txn_id, txn_type, qty from int_transactions_corrected",
             "staged": "select txn_id, uom from stg_erp__inventory_transactions",
             "conversions": "select * from stg_remediation__uom_conversions",
             "attrs": "select canonical_item_number, standard_cost from mart_item_attributes"}
        out = {k: con.execute(v).df() for k, v in q.items()}
        con.close()
    finally:
        os.chdir(cwd)
    return out


def run(archive: Path, issued_dir: Path, out: Path, scratch: Path) -> dict:
    lad, pol = issued_dir / "ladder", issued_dir / "policy"
    issued = M.Issued(json.loads((lad / "metrics_S1.json").read_text()), pd.read_parquet(lad / "pred_S1.parquet"),
                      json.loads((pol / "rop_schedule.json").read_text()), json.loads((pol / "retrain_log.json").read_text()))
    st = S.FileStore(archive / "ml/data/marts", archive / "data_source/raw")
    inp = tasks.load_inputs(st)
    frame, ctx = T.prepare_frame(inp)
    wh = warehouse_tables(archive, scratch)
    cur = M.Current(inp, frame, ctx, st.mart("supplier_leadtime_weekly"),
                    st.extract("erp", "item_master").set_index("item_number")["primary_supplier_id"],
                    json.loads((archive / "data_source/truth/forward_results.json").read_text()),
                    M.short_weeks(wh["shortage"]), M.uom_gap(wh["corrected"], wh["staged"], wh["conversions"], wh["attrs"]))
    summary, tables = M.monitor(issued, cur)
    out.mkdir(parents=True, exist_ok=True)
    (out / "monitoring_summary.json").write_text(json.dumps(summary, indent=2, default=float))
    for k in CSVS:
        tables[k].to_csv(out / f"{k}.csv", index=False)
    return summary


def compare(reference: Path, out: Path) -> dict:
    from parity_b import compare_doc

    res = {"monitoring_summary.json": compare_doc(reference / "monitoring_summary.json", out / "monitoring_summary.json")}
    for k in CSVS:
        a, b = (reference / f"{k}.csv").read_bytes(), (out / f"{k}.csv").read_bytes()
        same = a.replace(b"\r\n", b"\n") == b.replace(b"\r\n", b"\n")
        r = {"status": "identical" if a == b else ("identical (LF)" if same else "differs")}
        if not same:
            x, y = pd.read_csv(reference / f"{k}.csv"), pd.read_csv(out / f"{k}.csv")
            r["rows"] = [len(x), len(y)]
            if x.shape == y.shape and list(x.columns) == list(y.columns):
                num = [c for c in x.columns if pd.api.types.is_float_dtype(x[c])]
                r["max_abs"] = {c: float((x[c] - y[c]).abs().max()) for c in num}
                r["exact_equal"] = {c: bool(x[c].equals(y[c])) for c in x.columns if c not in num}
        res[k] = r
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", required=True, help="current tables: an archive with ml/data/marts, data_source")
    ap.add_argument("--issued", help="folder with ladder/ and policy/ of the issuing run (default: <archive>/runs/seq)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--reference", help="archived monitor outputs to compare against")
    ap.add_argument("--scratch", default=str(ROOT / "runs" / "parity" / "warehouse_links"))
    ap.add_argument("--json")
    a = ap.parse_args()
    arch = Path(a.archive).resolve()
    summary = run(arch, Path(a.issued) if a.issued else arch / "runs/seq", Path(a.out), Path(a.scratch))
    for p in summary["periods"]:
        print(p["period"], p["n_scored"], p["n_forecasts"], p["status"])
    if a.reference:
        res = compare(Path(a.reference), Path(a.out))
        for k, v in res.items():
            print(f"{k:26s} {v['status']:16s} {({kk: v[kk] for kk in ('counts', 'max_abs', 'rows') if kk in v})}")
        if a.json:
            Path(a.json).write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
