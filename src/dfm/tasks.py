"""The monthly cycle's work, independent of where it runs: training, the promotion gates' inputs, scoring.

Each function takes a store (dfm.store) and returns frames and documents; the entry points add tracking
and the registry. The documents are serialized exactly as the reference outputs are (metrics with
indent 1 or 2, schedules with indent 1), so runs can be compared byte for byte.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from . import config as C
from . import features as F
from . import policy as P
from . import training as T

RUNGS = ["reference", "S1"]          # the production path: the reference rung and S1 for the policy
POLICY_RUNG = "S1"
HORIZON = "static"
PRED_COLUMNS = ["item", "t", "week", "h", "target", "firm_h", "bf_window", "segment", "abc", "tier", "item_class"]


def load_inputs(store: Any) -> dict:
    """The model's inputs: the marts, the item crosswalk and the extracts it reads."""
    rd = store.mart
    return {"weekly": rd("consumption_weekly"), "attrs": rd("item_attributes").set_index("canonical_item_number"),
            "job_req": rd("job_requirements"), "bom": rd("bom_resolved"), "item_family": rd("item_family"),
            "fam_usage": rd("family_usage_weekly"), "pf_weekly": rd("product_family_weekly"),
            "shortage": rd("shortage_weekly"), "ib_item": rd("item_installed_base"), "lt_item": rd("item_leadtime_weekly"),
            "dim_week": rd("dim_week"), "lifecycle": rd("item_lifecycle"),
            "xw": store.crosswalk(), "tx": store.extract("erp", "inventory_transactions"),
            "svc": store.extract("erp", "service_orders"), "bom_raw": store.extract("erp", "bill_of_materials"),
            "restored": store.extract("remediation", "bom_change_log")}


MART_NAMES = ["consumption_weekly", "item_attributes", "job_requirements", "bom_resolved", "item_family",
              "family_usage_weekly", "product_family_weekly", "shortage_weekly", "item_installed_base",
              "item_leadtime_weekly", "dim_week", "item_lifecycle"]
EXTRACT_NAMES = [("erp", "inventory_transactions"), ("erp", "service_orders"), ("erp", "bill_of_materials"),
                 ("remediation", "bom_change_log"), ("erp", "purchase_orders")]


def weeks_of(weekly: pd.DataFrame) -> pd.DatetimeIndex:
    """The frame's weeks, as build_frame sets them."""
    return pd.date_range(weekly["week"].min(), F._monday(C.END_DATE), freq="W-MON")


INPUT_TABLES = {
    "consumption_weekly": "gold.mart_consumption_weekly", "item_attributes": "gold.mart_item_attributes",
    "job_requirements": "silver.int_job_requirements", "bom_resolved": "silver.int_bom_resolved",
    "item_family": "silver.int_item_family", "family_usage_weekly": "gold.mart_family_usage_weekly",
    "product_family_weekly": "gold.mart_product_family_weekly", "shortage_weekly": "gold.mart_shortage_weekly",
    "item_installed_base": "gold.mart_item_installed_base", "item_leadtime_weekly": "gold.mart_item_leadtime_weekly",
    "dim_week": "gold.dim_week", "item_crosswalk": "silver.int_item_crosswalk",
    "inventory_transactions": "bronze.erp__inventory_transactions", "service_orders": "bronze.erp__service_orders",
    "bill_of_materials": "bronze.erp__bill_of_materials", "bom_change_log": "bronze.remediation__bom_change_log",
    "purchase_orders": "bronze.erp__purchase_orders",
}


# ── documents ───────────────────────────────────────────────────────────────
def metrics_document(res: dict) -> str:
    """A rung's metrics without its fitted models, as the ladder writes them."""
    return json.dumps({k: v for k, v in res.items() if k != "models"}, indent=1, default=float)


def weekly_metrics_document(metrics: dict) -> str:
    return json.dumps(metrics, indent=2, default=float)


def predictions(test: pd.DataFrame) -> pd.DataFrame:
    """A rung's test rows with every prediction column, as the ladder writes them."""
    return test[PRED_COLUMNS + [c for c in test.columns if c.startswith("pred")]]


# ── training ────────────────────────────────────────────────────────────────
@dataclass
class Training:
    weekly_metrics: dict
    weekly_test: pd.DataFrame
    frame: pd.DataFrame
    ctx: dict
    results: dict
    tests: dict
    selection: dict
    shap: dict = field(default_factory=dict)

    @property
    def winner(self) -> str:
        return self.results[POLICY_RUNG]["winner"]


def train(store: Any, shap: bool = True) -> Training:
    """The weekly reference model, the frame, the reference and S1 rungs and the selection rule."""
    inp = load_inputs(store)
    weekly_metrics, weekly_test = T.weekly_backtest(inp["weekly"], inp["attrs"])
    frame, ctx = T.prepare_frame(inp)
    results, tests = {}, {}
    for rung in RUNGS:
        results[rung], tests[rung] = T.run_rung(frame, rung)
    out = Training(weekly_metrics, weekly_test, frame, ctx, results, tests, T.choose_final(results, RUNGS))
    if shap:
        out.shap = T.shap_summary(results[POLICY_RUNG], tests[POLICY_RUNG])
    return out


def selection_pick(results: dict) -> tuple[str, str]:
    """The rung and candidate the selection rules pick from logged results: within a rung the lowest
    validation WAPE, the booster on a tie within 0.5 points; across rungs the lowest validation WAPE,
    a rung within 0.3 points of a smaller feature set losing to the smaller set."""
    for r in results.values():
        c = r["candidates"]
        w = min(c, key=lambda k: c[k]["val_wape"])
        if w != "XGBoost" and c["XGBoost"]["val_wape"] <= c[w]["val_wape"] + 0.005:
            w = "XGBoost"
        if w != r["winner"]:
            return "", ""
    chosen = T.choose_final(results, list(results))["chosen"]
    return chosen, results[chosen]["winner"]


def rung_cap(frame: pd.DataFrame, rung: str = POLICY_RUNG) -> float:
    """The forecast cap run_rung applies: four times the largest training target on train and validation."""
    s1, s3 = T.RUNGS_AT_LEAST(rung, "S1"), T.RUNGS_AT_LEAST(rung, "S3")
    f, cold = T._rows(frame.assign(firm_h_total=frame["firm_h"]), rung)
    total = f["target"] + (f["backorder_shift"] if s3 else 0.0)
    y = np.maximum(total - f["firm_h_total"], 0.0) if s1 else total
    keep = ((f["split"] == "train") & ~cold & y.notna()) | ((f["split"] == "val") & ~cold)
    return float(y[keep].max()) * 4


# ── gate inputs ─────────────────────────────────────────────────────────────
def test_rows(frame: pd.DataFrame, rung: str = POLICY_RUNG) -> pd.DataFrame:
    f, _ = T._rows(frame, rung)
    return f[f["split"] == "test"]


def week_indices(weeks: pd.DatetimeIndex) -> dict:
    wi = F.week_index(weeks)
    t_test0 = wi[pd.Timestamp(F._monday(date(2025, 1, 1) + timedelta(days=7)))]
    return {"fwd": wi[pd.Timestamp(F._monday(C.FORWARD_START))], "test0": t_test0, "val0": t_test0 - 26}


def latest_matured_month(frame: pd.DataFrame, weeks: pd.DatetimeIndex) -> str | None:
    """The latest calendar month of origins in which every reference row's target window has closed
    by the planning-window start (all its forecasts are out of sample and matured)."""
    t_fwd = week_indices(weeks)["fwd"]
    ref = frame[frame["is_reference_row"]]
    month = pd.to_datetime(ref["week"]).dt.strftime("%Y-%m")
    closed = (ref["t"] + ref["h"] <= t_fwd).groupby(month).all()
    closed = closed[closed]
    return str(closed.index.max()) if len(closed) else None


def completeness_universe(lifecycle: pd.DataFrame, origin: date, weeks_needed: int = 13) -> list:
    """Items in use for at least weeks_needed weeks before the origin."""
    first = pd.to_datetime(lifecycle["first_use_date"])
    ok = first.notna() & (first <= pd.Timestamp(origin) - pd.Timedelta(weeks=weeks_needed))
    return sorted(lifecycle.loc[ok, "canonical_item_number"])


# ── scoring ─────────────────────────────────────────────────────────────────
def score(store: Any, result: dict, oos_predict) -> tuple[dict, list, pd.DataFrame]:
    """The planning-window schedule from the champion's rung result. oos_predict(test rows) returns the
    champion's uncovered-demand predictions on its 2025 test rows (the error pool's start)."""
    inp = load_inputs(store)
    frame, ctx = T.prepare_frame(inp)
    attrs = inp["attrs"]
    tier_of = T.criticality(inp, ctx["items"])
    po = store.extract("erp", "purchase_orders")
    lt_sd = P.lead_time_sd(po, inp["xw"], attrs["item_class"].to_dict())
    test = test_rows(frame, POLICY_RUNG)
    kind = result["winner"]
    pred = test[["item", "t", "h", "target", "firm_h", "segment", "tier", "abc"]].copy()
    pred[f"predu_{kind}"] = oos_predict(test)
    oos = P.oos_pool(pred, kind)
    sched, retrains = P.build_schedule(frame, POLICY_RUNG, result, oos, HORIZON, lt_sd, tier_of, attrs, ctx["weeks"])
    return P.schedule_document(sched, POLICY_RUNG, result, HORIZON, tier_of), retrains, frame


def schedule_document_text(doc: dict) -> str:
    return json.dumps(doc, indent=1)


def schedule_rows(doc: dict, model_version: str) -> pd.DataFrame:
    """gold.reorder_schedule: one row per item per schedule date."""
    fields = doc["entry_fields"]
    rows = [[item, *e] for item, es in doc["items"].items() for e in es]
    df = pd.DataFrame(rows, columns=["canonical_item_number", *fields])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["horizon_days"] = df["horizon_days"].astype("int64")
    df["criticality"] = df["canonical_item_number"].map(doc["criticality"])
    df["model"] = doc["model"]
    df["model_version"] = model_version
    return df.sort_values(["canonical_item_number", "date"]).reset_index(drop=True)


def queue_rows(schedule: pd.DataFrame, as_of: date = C.AS_OF_DATE) -> pd.DataFrame:
    """gold.reorder_queue: each item's schedule entry in effect on the as-of date."""
    s = schedule[schedule["date"] <= as_of]
    q = s.sort_values(["canonical_item_number", "date"]).groupby("canonical_item_number", as_index=False).tail(1)
    q = q.rename(columns={"date": "effective_date"})
    q.insert(1, "as_of", as_of)
    return q.reset_index(drop=True)


def retrain_rows(retrains: list) -> pd.DataFrame:
    """gold.policy_retrains: what each monthly retrain of the policy estimated."""
    rows = []
    for r in retrains:
        for seg, v in r["bias_factors"].items():
            rows.append({"period": r["period"], "trained_on": r["trained_on"], "training_rows": r["training_rows"],
                         "error_rows": r["error_rows"], "segment": seg, "bias_factor": v})
    return pd.DataFrame(rows)


def frame_table(frame: pd.DataFrame) -> pd.DataFrame:
    """gold.feature_frame: the feature frame with dates as dates."""
    out = frame.copy()
    out["week"] = pd.to_datetime(out["week"]).dt.date
    return out


def float_close(a: np.ndarray, b: np.ndarray, rel: float = 1e-9, floor: float = 1e-12) -> np.ndarray:
    a, b = np.asarray(a, float), np.asarray(b, float)
    tol = np.maximum(rel * np.maximum(np.abs(a), np.abs(b)), floor)
    return (np.abs(a - b) <= tol) | (np.isnan(a) & np.isnan(b))
