"""Parity B: the model and schedule outputs of a run against the archived reference sequence.

Byte identity first; where bytes differ, the outcome standard: the selected candidates and tuned
parameters identical, every metric within 1e-6 (absolute), every schedule entry identical after the
policy's rounding, row counts, keys and strings exact; frames compared column by column.

Reference layout (the archive of the post-update sequence): ml/data/backtest/weekly_metrics.json,
weekly_backtest.parquet; runs/seq/ladder/metrics_<rung>.json, pred_<rung>.parquet, frame.parquet;
runs/seq/policy/rop_schedule.json, retrain_log.json. The run folder has the layout run_package.py writes.

Usage: python tests/parity/parity_b.py --reference DIR --run DIR [--json OUT]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

METRIC_TOL = 1e-6
PAIRS = [
    ("weekly_metrics.json", "ml/data/backtest/weekly_metrics.json", "weekly_metrics.json"),
    ("metrics_reference.json", "runs/seq/ladder/metrics_reference.json", "ladder/metrics_reference.json"),
    ("metrics_S1.json", "runs/seq/ladder/metrics_S1.json", "ladder/metrics_S1.json"),
    ("rop_schedule.json", "runs/seq/policy/rop_schedule.json", "policy/rop_schedule.json"),
    ("retrain_log.json", "runs/seq/policy/retrain_log.json", "policy/retrain_log.json"),
]
FRAMES = [
    ("weekly_backtest", "ml/data/backtest/weekly_backtest.parquet", "weekly_backtest.parquet"),
    ("frame", "runs/seq/ladder/frame.parquet", "ladder/frame.parquet"),
    ("pred_reference", "runs/seq/ladder/pred_reference.parquet", "ladder/pred_reference.parquet"),
    ("pred_S1", "runs/seq/ladder/pred_S1.parquet", "ladder/pred_S1.parquet"),
]
EXACT_KEYS = {"winner", "params", "rung", "features", "rows", "best_by_segment", "firm_best_by_segment",
              "baseline_method", "segment", "origins", "criticality", "model", "horizon", "entry_fields",
              "period", "trained_on", "training_rows", "error_rows", "chosen", "lowest"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def walk(a, b, path: str, out: dict, exact: bool = False) -> None:
    """Differences between two JSON documents: exact for keys, strings, ints and EXACT_KEYS subtrees;
    floats within METRIC_TOL elsewhere."""
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            out["structure"].append(f"{path}: keys {sorted(set(a) ^ set(b))}")
        for k in a.keys() & b.keys():
            walk(a[k], b[k], f"{path}.{k}", out, exact or k in EXACT_KEYS)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out["structure"].append(f"{path}: length {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f"{path}[{i}]", out, exact)
    elif isinstance(a, float) or isinstance(b, float):
        if a == b or (a != a and b != b):
            return
        d = abs(float(a) - float(b))
        out["max_abs"] = max(out["max_abs"], d)
        out["float_diffs"] += 1
        if exact:
            out["exact_misses"].append(f"{path}: {a!r} vs {b!r}")
        elif d > METRIC_TOL:
            out["tolerance_misses"].append(f"{path}: {a!r} vs {b!r}")
    elif a != b:
        out["exact_misses"].append(f"{path}: {a!r} vs {b!r}")


def lf(p: Path) -> bytes:
    """The document with Windows line endings written as LF (the reference was written on Windows)."""
    return p.read_bytes().replace(b"\r\n", b"\n")


def compare_doc(ref: Path, got: Path) -> dict:
    r = {"identical_bytes": sha(ref) == sha(got), "sha_ref": sha(ref), "sha_run": sha(got),
         "identical_after_line_endings": lf(ref) == lf(got),
         "sha_lf_ref": hashlib.sha256(lf(ref)).hexdigest(), "sha_lf_run": hashlib.sha256(lf(got)).hexdigest()}
    if r["identical_bytes"] or r["identical_after_line_endings"]:
        r["status"] = "identical" if r["identical_bytes"] else "identical (LF)"
        return r
    out = {"structure": [], "exact_misses": [], "tolerance_misses": [], "float_diffs": 0, "max_abs": 0.0}
    walk(json.loads(ref.read_text()), json.loads(got.read_text()), "$", out)
    miss = out["structure"] or out["exact_misses"] or out["tolerance_misses"]
    r.update({k: (v[:25] if isinstance(v, list) else v) for k, v in out.items()})
    r["counts"] = {k: len(v) for k, v in out.items() if isinstance(v, list)}
    r["status"] = "MISS" if miss else "within tolerance"
    return r


def compare_frame(ref: Path, got: Path) -> dict:
    a, b = pd.read_parquet(ref), pd.read_parquet(got)
    r = {"rows_ref": len(a), "rows_run": len(b), "columns_equal": list(a.columns) == list(b.columns)}
    if len(a) != len(b) or set(a.columns) != set(b.columns):
        r["status"] = "MISS"
        return r
    moved, exact_miss = {}, []
    for c in a.columns:
        x, y = a[c], b[c]
        if pd.api.types.is_float_dtype(x) and pd.api.types.is_float_dtype(y):
            xa, ya = x.to_numpy(), y.to_numpy()
            same = (xa == ya) | (np.isnan(xa) & np.isnan(ya))
            if not same.all():
                d = np.abs(xa - ya)[~same]
                moved[c] = {"cells": int((~same).sum()), "max_abs": float(np.nanmax(d)),
                            "max_rel": float(np.nanmax(d / np.maximum(np.abs(xa[~same]), 1e-300)))}
        elif not x.equals(y):
            exact_miss.append(c)
    r.update({"moved": moved, "exact_miss": exact_miss})
    r["status"] = "MISS" if exact_miss else ("identical" if not moved else "moved")
    return r


def tables_as_run(tables: Path, out: Path) -> None:
    """Write exported platform tables (gold.backtest_predictions, feature_frame, weekly_backtest) in the
    run layout, with the reference's column order and dtypes, so compare_frame applies."""
    (out / "ladder").mkdir(parents=True, exist_ok=True)
    pred = pd.read_parquet(tables / "backtest_predictions.parquet")
    for rung in ["reference", "S1"]:
        ref_cols = pd.read_parquet(REF_DEFAULT / f"runs/seq/ladder/pred_{rung}.parquet").columns
        p = pred[pred["rung"] == rung].sort_values(["item", "t"]).reset_index(drop=True)
        p["week"] = pd.to_datetime(p["week"]).astype("datetime64[ns]")
        p[list(ref_cols)].to_parquet(out / "ladder" / f"pred_{rung}.parquet", index=False)
    fr = pd.read_parquet(tables / "feature_frame.parquet").sort_values(["item", "t"]).reset_index(drop=True)
    fr["week"] = pd.to_datetime(fr["week"]).astype("datetime64[ns]")
    ref_fr = pd.read_parquet(REF_DEFAULT / "runs/seq/ladder/frame.parquet")
    for c in ref_fr.columns:
        if fr[c].dtype != ref_fr[c].dtype and pd.api.types.is_numeric_dtype(ref_fr[c]):
            fr[c] = fr[c].astype(ref_fr[c].dtype)
    fr[list(ref_fr.columns)].to_parquet(out / "ladder" / "frame.parquet", index=False)
    wb = pd.read_parquet(tables / "weekly_backtest.parquet").sort_values(["item", "t"]).reset_index(drop=True)
    wb["week"] = pd.to_datetime(wb["week"]).astype("datetime64[ns]")
    ref_wb = pd.read_parquet(REF_DEFAULT / "ml/data/backtest/weekly_backtest.parquet")
    for c in ref_wb.columns:
        if wb[c].dtype != ref_wb[c].dtype and pd.api.types.is_numeric_dtype(ref_wb[c]):
            wb[c] = wb[c].astype(ref_wb[c].dtype)
    wb[list(ref_wb.columns)].to_parquet(out / "weekly_backtest.parquet", index=False)


def schedule_table_check(tables: Path, doc: Path) -> dict:
    """gold.reorder_schedule row for row against a schedule document's entries."""
    t = pd.read_parquet(tables / "reorder_schedule.parquet").sort_values(["canonical_item_number", "date"])
    d = json.loads(doc.read_text())
    fields = d["entry_fields"]
    rows = [[i, *e] for i, es in d["items"].items() for e in es]
    ref = pd.DataFrame(rows, columns=["canonical_item_number", *fields]).sort_values(["canonical_item_number", "date"])
    t = t.assign(date=pd.to_datetime(t["date"]).dt.strftime("%Y-%m-%d")).reset_index(drop=True)
    ref = ref.reset_index(drop=True)
    same = len(t) == len(ref) and all((t[c].to_numpy() == ref[c].to_numpy()).all() for c in ["canonical_item_number", *fields])
    return {"rows_table": len(t), "rows_document": len(ref), "status": "identical" if same else "MISS"}


REF_DEFAULT = Path(__file__).resolve().parents[2] / "reference" / "2026-10_post_signal_update"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--tables", help="exported platform tables, written into the run layout first")
    ap.add_argument("--json")
    a = ap.parse_args()
    ref, run = Path(a.reference), Path(a.run)
    res = {}
    if a.tables:
        tables_as_run(Path(a.tables), run)
        res["reorder_schedule table"] = schedule_table_check(Path(a.tables), ref / "runs/seq/policy/rop_schedule.json")
    for name, rp, gp in PAIRS:
        res[name] = compare_doc(ref / rp, run / gp) if (run / gp).exists() else {"status": "absent"}
    for name, rp, gp in FRAMES:
        res[name] = compare_frame(ref / rp, run / gp) if (run / gp).exists() else {"status": "absent"}
    for k, v in res.items():
        extra = {kk: v[kk] for kk in ("counts", "max_abs", "moved", "exact_miss", "rows_ref") if kk in v}
        print(f"{k:24s} {v['status']:18s} {extra}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
