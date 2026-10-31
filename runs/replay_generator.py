"""Run the generator unchanged and capture the replay, to read the forward window on a
set of items (the drift-supplier items) that the generator's own report aggregates.
Usage (from the repo root of the checkout to replay in): python runs/replay_generator.py <out.json>"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

from data_source.generate import run_generator as RG
from data_source.generate import config as C

captured = {}
_orig = RG._forward_results


def _wrap(sim, sim_dirty, sim_rule, *args, **kwargs):
    captured["sim"], captured["sim_rule"] = sim, sim_rule
    captured["cost"], captured["primary"] = args[3], args[5]   # (schedule, item_master, imc, cost_by_item, abc_by_item, primary, ...)
    return _orig(sim, sim_dirty, sim_rule, *args, **kwargs)


RG._forward_results = _wrap
RG.run()

truth = json.loads((C.REPO_ROOT / "data_source" / "truth" / "crosswalks.json").read_text())
ids = set(truth["m2_sharp_items"]) & set(truth["m2_drift_items"])
import pandas as pd
im = pd.read_csv(C.RAW_DIR / "erp" / "item_master.csv")
sup = im.set_index("item_number")["primary_supplier_id"].to_dict()
primary = captured["primary"]
drift = {iid: num for iid, num in primary.items() if iid in ids and sup.get(num) == truth["m2_drift_supplier"]}


def per_item(sim, cost):
    days = sim["days"]
    mask = np.asarray((days.date >= C.FORWARD_START) & (days.date <= C.END_DATE))
    out = {}
    for iid, num in drift.items():
        phys = sim["physical"].get(iid)
        if phys is None:
            continue
        out[num] = {"short_days": int(sim["short_days"][iid][mask].sum()),
                    "avg_inventory_value": float(np.clip(phys[mask], 0, None).mean() * cost.get(iid, 0.0))}
    return out


res = {"model": per_item(captured["sim"], captured["cost"]), "rule": per_item(captured["sim_rule"], captured["cost"])}
for k in ["model", "rule"]:
    res[k + "_total"] = {"short_days": sum(v["short_days"] for v in res[k].values()),
                         "avg_inventory_value": sum(v["avg_inventory_value"] for v in res[k].values()), "items": len(res[k])}
Path(sys.argv[1]).write_text(json.dumps(res, indent=1))
print("drift items:", res["model_total"], "| rule:", res["rule_total"])
