"""Flatten the generator's ground truth into tables the dbt warehouse can read.

The generator records what it planted (duplicate clusters, unrecorded usage,
batched receipts) and the true demand behind the recorded history. A real
warehouse would not have these; here they stand in for findings the business
confirmed, and they let the marts carry a true-demand series to score the
forecast against. Writes, under data_source/truth/:

  true_direct_demand.csv    item_id, month, qty     demand by the engine's direct channel
  duplicate_clusters.csv    item_number, primary    every record in a duplicate cluster
  abc_by_item.csv           item_id, abc            the planned value class
  unrecorded_usage.csv      item_number, annual_unrecorded   one row per unrecorded source
  uom_mismatch_items.csv    item_id                 items bought and stocked in different units
  batched_receipts.csv      po_id, line             receipt lines posted late in a batch

Run:  python -m data_source.generate.export_truth
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import config as C
from .generators.demand import build_item_plan, build_monthly_demand

TRUTH = C.REPO_ROOT / "data_source" / "truth"


def run():
    rng = np.random.default_rng(C.RANDOM_SEED)
    direct = build_monthly_demand(build_item_plan(rng), rng)
    direct.rename(columns={"demand_units": "qty"})[["item_id", "month", "qty"]].to_csv(
        TRUTH / "true_direct_demand.csv", index=False)

    cross = json.loads((TRUTH / "crosswalks.json").read_text())
    pd.DataFrame([{"item_number": r, "primary": cl["primary"]}
                  for cl in cross["duplicate_clusters"].values() for r in cl["records"]]).to_csv(
        TRUTH / "duplicate_clusters.csv", index=False)
    pd.DataFrame([{"item_id": int(k), "abc": v} for k, v in cross["abc_by_item"].items()]).to_csv(
        TRUTH / "abc_by_item.csv", index=False)
    pd.DataFrame({"item_id": cross["m5_items"]}).to_csv(TRUTH / "uom_mismatch_items.csv", index=False)

    txn = json.loads((TRUTH / "txn_defects.json").read_text())
    pd.DataFrame([{"source_no": i, "item_number": r["item_number"], "annual_unrecorded": r.get("annual_unrecorded", 0)}
                  for i, r in enumerate(txn.get("t1", []))],
                 columns=["source_no", "item_number", "annual_unrecorded"]).to_csv(
        TRUTH / "unrecorded_usage.csv", index=False)

    pod = json.loads((TRUTH / "po_defects.json").read_text())
    pd.DataFrame([{"po_id": r["po_id"], "line": int(r["line"])} for r in pod.get("t4", [])],
                 columns=["po_id", "line"]).to_csv(TRUTH / "batched_receipts.csv", index=False)
    print(f"Truth tables written to {TRUTH}: {len(direct):,} demand rows")


if __name__ == "__main__":
    run()
