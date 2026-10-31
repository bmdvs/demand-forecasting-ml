"""Run the dfm package's training and scoring locally and write the outputs the reference sequence wrote.

Inputs either from an archive (the exported mart files and CSV extracts, as the scripts read them) or
from Parquet exports of the platform's tables plus the landed extract files (the projection the platform
run uses). Outputs, in the reference layout:
  <out>/weekly_metrics.json, weekly_backtest.parquet
  <out>/ladder/frame.parquet, metrics_<rung>.json, pred_<rung>.parquet
  <out>/policy/rop_schedule.json, retrain_log.json

With --score-archive the policy scores a second archive's tables with the model trained on the first, as
dfm-score does at pass 2 when the champion was trained at pass 1.

Usage:
  python tests/parity/run_package.py --archive DIR --out DIR [--no-shap] [--score-archive DIR]
  python tests/parity/run_package.py --tables DIR --landing DIR [--pass pass1] --out DIR [--no-shap]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from dfm import store as S  # noqa: E402
from dfm import tasks  # noqa: E402
from dfm import training as T  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive")
    ap.add_argument("--tables")
    ap.add_argument("--landing")
    ap.add_argument("--pass", dest="pass_name", default="pass1")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-shap", action="store_true")
    ap.add_argument("--score-archive", help="score this archive's tables with the model trained on --archive")
    a = ap.parse_args()
    if a.archive:
        arch = Path(a.archive)
        store = S.FileStore(arch / "ml" / "data" / "marts", arch / "data_source" / "raw")
    else:
        store = S.TableStore(S.DirectoryTables(Path(a.tables), Path(a.landing), a.pass_name))
    out = Path(a.out)
    (out / "ladder").mkdir(parents=True, exist_ok=True)
    (out / "policy").mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    tr = tasks.train(store, shap=not a.no_shap)
    print(f"trained in {time.time() - t0:.0f} s; S1 winner {tr.winner}; selection {tr.selection}", flush=True)
    (out / "weekly_metrics.json").write_text(tasks.weekly_metrics_document(tr.weekly_metrics))
    tr.weekly_test.to_parquet(out / "weekly_backtest.parquet", index=False)
    tr.frame.to_parquet(out / "ladder" / "frame.parquet", index=False)
    for rung in tasks.RUNGS:
        tasks.predictions(tr.tests[rung]).to_parquet(out / "ladder" / f"pred_{rung}.parquet", index=False)
        (out / "ladder" / f"metrics_{rung}.json").write_text(tasks.metrics_document(tr.results[rung]))
    if tr.shap:
        (out / "ladder" / "shap_S1.json").write_text(json.dumps(tr.shap, indent=1, default=float))

    res = tr.results[tasks.POLICY_RUNG]
    kind = res["winner"]
    model = res["models"][kind]
    cap = tasks.rung_cap(tr.frame, tasks.POLICY_RUNG)
    assert cap == T._CAP, (cap, T._CAP)
    feats = res["features"]
    result = json.loads(tasks.metrics_document(res))
    t1 = time.time()
    if a.score_archive:
        sa = Path(a.score_archive)
        store = S.FileStore(sa / "ml" / "data" / "marts", sa / "data_source" / "raw")
    doc, retrains, _ = tasks.score(store, result, lambda test: T._predict(kind, model, test[feats].astype(float), cap))
    print(f"scored in {time.time() - t1:.0f} s", flush=True)
    (out / "policy" / "rop_schedule.json").write_text(tasks.schedule_document_text(doc))
    (out / "policy" / "retrain_log.json").write_text(json.dumps(retrains, indent=1))


if __name__ == "__main__":
    main()
