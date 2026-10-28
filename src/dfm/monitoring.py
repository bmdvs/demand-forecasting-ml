"""Monthly monitoring of the production demand model (S1, static horizon) over the planning window.

Each month of the window is judged on the forecasts the issued schedule made for it, scored once their
lead-time windows have closed, against references fixed when the model was trained:

  performance       WAPE and corrected bias, overall and by demand pattern (and pattern x tier), against
                    the same measures on the model's 2025 test rows
  target drift      Jensen-Shannon distance of actual lead-time usage against the training rows
  prediction drift  distance of the month's forecasts against the 2025 test forecasts
  feature drift     distance of each input feature against the training rows
  bias factors      the factors the policy re-estimates at each monthly retrain, by pattern
  lead-time review  the pooled 26-week lead time against the corrected master, by item and supplier
  data quality      book-side short weeks, the receipts' unit-of-measure gap, null features, unseen items
  outcomes          fill rate by criticality, stockout episodes and held jobs from the forward results

and evaluates the retraining rules (Investigate and Retrain thresholds below). The issued schedule is the
one in force over the window: the schedule, retrain log, rung result and test predictions of the run that
issued it. The current tables give the actuals, the features and the lead times.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.spatial.distance import jensenshannon

from . import config as C
from . import features as SF
from .features import _monday

DRIFT = 0.10              # Jensen-Shannon distance flagged as drift
WAPE_OVERALL_TOL = 0.03   # overall WAPE above the 2025 reference: investigate; this far above: retrain
WAPE_TOL = 0.05           # pattern WAPE above its 2025 level: investigate; this far above: retrain
BIAS_TOL = 0.10           # corrected bias, overall or for a pattern, outside +/- this: retrain
FILL_TOL = 0.01           # fill rate this far below target is degraded
MAX_FEATS = 3             # more drifted features than this is a secondary trigger
MIN_ROWS = 150            # a pattern needs this many scored forecasts to be judged
MATURED = 0.80            # a month is judged on accuracy once this share of its forecasts has matured
CALENDAR = {"woy", "month"}
CATEGORICAL = {"seg_code", "abc_code", "cls_code"}
LEAD_REVIEW_RATIO = 1.25  # pooled 26-week lead time this far above the corrected master...
LEAD_REVIEW_MONTHS = 2    # ...for this many consecutive month-ends raises a lead-time review


def _js(ref, cur, categorical=False, bins=20):
    ref, cur = np.asarray(ref, float), np.asarray(cur, float)
    if len(cur) == 0:
        return np.nan
    if categorical:
        cats = np.union1d(np.unique(ref), np.unique(cur))
        p = np.array([(ref == c).mean() for c in cats]); q = np.array([(cur == c).mean() for c in cats])
    else:
        r, c = np.log1p(np.clip(ref, 0, None)), np.log1p(np.clip(cur, 0, None))
        edges = np.unique(np.quantile(r, np.linspace(0, 1, bins + 1)))
        if len(edges) < 3:
            edges = np.linspace(min(r.min(), c.min()), max(r.max(), c.max()) + 1e-9, bins + 1)
        edges[0], edges[-1] = -np.inf, np.inf
        p = np.histogram(r, edges)[0] / len(r); q = np.histogram(c, edges)[0] / len(c)
    return float(jensenshannon(p + 1e-9, q + 1e-9, base=2))


def _wape(a, f):
    a, f = np.asarray(a, float), np.asarray(f, float)
    return float(np.abs(a - f).sum() / a.sum()) if a.sum() > 0 else np.nan


# ── the issued schedule's forecasts, joined to the current tables ─────────────
def schedule_entries(doc: dict) -> list[tuple]:
    """(item, date, forecast over the horizon) for every entry of a schedule document, in its order."""
    return [(item, e[0], float(e[3])) for item, entries in doc["items"].items() for e in entries]


def table_entries(schedule: pd.DataFrame) -> list[tuple]:
    """The same from gold.reorder_schedule rows (sorted by item and date, the document's order)."""
    s = schedule.sort_values(["canonical_item_number", "date"])
    return list(zip(s["canonical_item_number"], s["date"], s["forecast_over_horizon"].astype(float), strict=True))


def window_indices(weeks: pd.DatetimeIndex) -> dict:
    widx = {w: i for i, w in enumerate(weeks)}
    t_test0 = widx[pd.Timestamp(_monday(date(2025, 1, 1) + timedelta(days=7)))]
    return {"widx": widx, "t_test0": t_test0, "t_val0": t_test0 - 26, "t_end": widx[pd.Timestamp(_monday(C.END_DATE))]}


def live_forecasts(entries: list[tuple], frame: pd.DataFrame, weeks: pd.DatetimeIndex) -> pd.DataFrame:
    """Each issued forecast with the current frame's row for its item and origin week; scored when its
    target window has closed by the end of the window."""
    ix = window_indices(weeks)
    widx = ix["widx"]
    frame = frame[frame["is_reference_row"]]
    rows = []
    for item, d, fc in entries:
        mon = pd.Timestamp(_monday(pd.Timestamp(d).date()))
        if mon in widx:
            rows.append((item, widx[mon], pd.Timestamp(d).strftime("%Y-%m"), float(fc)))
    live = pd.DataFrame(rows, columns=["item", "t", "period", "forecast"]).merge(frame, on=["item", "t"], how="left")
    live["scored"] = live["t"] + live["h"] <= ix["t_end"]
    return live


@dataclass
class MonthBias:
    period: str
    n_forecasts: int
    n_scored: int
    matured: bool
    pattern_bias: dict


def month_bias(live: pd.DataFrame) -> list[MonthBias]:
    """By month: forecasts, scored forecasts, maturity and corrected bias by pattern (patterns with
    MIN_ROWS scored forecasts), as the monitor computes them."""
    out = []
    for per, g in live.groupby("period"):
        sc = g[g["scored"] & g["target"].notna()]
        pat_b = {}
        for sg, gg in sc.groupby("segment"):
            if len(gg) < MIN_ROWS:
                continue
            pat_b[sg] = float((gg["forecast"].sum() - gg["target"].sum()) / gg["target"].sum())
        out.append(MonthBias(per, int(len(g)), int(len(sc)), len(sc) >= MATURED * len(g), pat_b))
    return out


# ── data quality from the warehouse ──────────────────────────────────────────
def short_weeks(shortage: pd.DataFrame) -> dict:
    """Book-side short-week shares by month of the planning window (gold.mart_shortage_weekly)."""
    s = shortage[pd.to_datetime(shortage["week"]) >= pd.Timestamp("2026-01-01")].copy()
    s["period"] = pd.to_datetime(s["week"]).dt.strftime("%Y-%m")
    s["sw"] = np.where(s["short_week"].eq(True), 1.0, 0.0)
    s["sa"] = np.where(s["short_active_week"].eq(True), 1.0, 0.0)
    g = s.groupby("period")
    return {p: {"short_week_share": float(a), "active_short_share": float(b)}
            for p, a, b in zip(g["sw"].mean().index, g["sw"].mean(), g["sa"].mean(), strict=True)}


def uom_gap(corrected: pd.DataFrame, staged: pd.DataFrame, conversions: pd.DataFrame, attrs: pd.DataFrame) -> dict:
    """On-hand value as booked against converted at the purchase unit, for the items whose receipts were
    booked in a purchase unit other than the stock unit (silver.int_transactions_corrected,
    silver.stg_erp__inventory_transactions, silver.stg_remediation__uom_conversions,
    gold.mart_item_attributes)."""
    c = corrected[["canonical_item_number", "item_number", "txn_id", "txn_type", "qty"]].merge(
        staged[["txn_id", "uom"]], on="txn_id", how="inner")
    u = conversions[conversions["stock_uom"] != conversions["purchase_uom"]][["item_number", "purchase_uom", "conversion"]]
    c = c.merge(u, left_on=["item_number", "uom"], right_on=["item_number", "purchase_uom"], how="left")
    qty = c["qty"].astype(float)
    signed = np.where(c["txn_type"].isin(["RECEIPT", "ADJUST"]), qty, -qty.abs())
    conv = np.where(c["txn_type"] == "RECEIPT", qty * c["conversion"].fillna(1.0).astype(float),
                    np.where(c["txn_type"] == "ADJUST", qty, -qty.abs()))
    per = pd.DataFrame({"canonical_item_number": c["canonical_item_number"], "as_is": signed, "conv": conv}) \
        .groupby("canonical_item_number", as_index=False)[["as_is", "conv"]].sum(min_count=1)
    per = per.merge(attrs[["canonical_item_number", "standard_cost"]], on="canonical_item_number", how="inner")
    gap = per[per["as_is"] != per["conv"]]
    booked = float((gap["as_is"].clip(lower=0) * gap["standard_cost"]).sum())
    converted = float((gap["conv"].clip(lower=0) * gap["standard_cost"]).sum())
    total = float((per["as_is"].clip(lower=0) * per["standard_cost"]).sum())
    return {"items": int(len(gap)), "on_hand_value_as_booked": booked, "on_hand_value_converted": converted,
            "understatement_of_total": float((converted - booked) / total)}


# ── the monitor ──────────────────────────────────────────────────────────────
@dataclass
class Issued:
    """What the run that issued the schedule in force wrote: the S1 rung result (metrics_S1.json), its
    2025 test predictions, the schedule document and the policy's retrain log."""
    result: dict
    predictions: pd.DataFrame
    schedule: dict
    retrains: list


@dataclass
class Current:
    """The current pass's tables: model inputs (tasks.load_inputs), the prepared frame and its context,
    the supplier lead-time mart, item master primary suppliers, the forward results and data quality."""
    inputs: dict
    frame: pd.DataFrame
    ctx: dict
    supplier_leadtime: pd.DataFrame
    primary_supplier: pd.Series
    forward_results: dict
    short_by: dict
    uom_gap: dict


def monitor(issued: Issued, cur: Current) -> tuple[dict, dict[str, pd.DataFrame]]:
    """The monthly statuses (monitoring_summary.json) and the per-month detail tables."""
    res = issued.result
    feats = res["features"]
    sched = issued.schedule
    fr = cur.forward_results
    retrains = issued.retrains
    bt = issued.predictions
    inp = cur.inputs
    weeks = cur.ctx["weeks"]
    ix = window_indices(weeks)
    t_val0 = ix["t_val0"]
    frame = cur.frame[cur.frame["is_reference_row"]]
    ref = frame[frame["t"] + frame["h"] <= t_val0]

    live = live_forecasts(schedule_entries(sched), cur.frame, weeks)
    # the buyer with the order book and a spreadsheet, as the ladder chose it by pattern
    sel = res["simple"]["firm_best_by_segment"]
    live["base"] = live["firm_h"] + np.array([live.at[i, sel.get(sg, "u_ma13")] for i, sg in zip(live.index, live["segment"])], dtype=float)

    kind = res["winner"]
    ref_pat = {sg: {"wape": _wape(g["target"], g[f"predc_{kind}"]),
                    "bias": float((g[f"predc_{kind}"].sum() - g["target"].sum()) / g["target"].sum())}
               for sg, g in bt.groupby("segment")}
    ref_wape = _wape(bt["target"], bt[f"predc_{kind}"])
    m25 = fr.get("monthly_2025", {})
    ref_events = float(np.mean([v["stockout_episodes"] for v in m25.values()])) if m25 else np.nan
    ref_held = float(np.mean([v["jobs_delayed"] for v in m25.values()])) if m25 else np.nan
    fill_target = sched["fill_rate_target"]
    drift_feats = [f for f in feats if f not in CALENDAR]

    # lead-time review: the pooled 26-week median against the corrected master at each month-end
    lt = inp["lt_item"].copy(); lt["week"] = pd.to_datetime(lt["week"])
    master = inp["attrs"]["corrected_lead_days"]
    month_end = lt.groupby(lt["week"].dt.to_period("M"))["week"].max()
    lt_m = lt[lt["week"].isin(month_end.values)].copy()
    lt_m["period"] = lt_m["week"].dt.strftime("%Y-%m")
    lt_m["over"] = lt_m["lt_pooled26w"] > LEAD_REVIEW_RATIO * lt_m["canonical_item_number"].map(master)
    piv = lt_m.pivot(index="canonical_item_number", columns="period", values="over").fillna(False).sort_index(axis=1)
    sup_lt = cur.supplier_leadtime.copy(); sup_lt["week"] = pd.to_datetime(sup_lt["week"])
    im = cur.primary_supplier
    sup_master = master.groupby(master.index.map(im)).median()
    sm = sup_lt[sup_lt["week"].isin(month_end.values)].copy(); sm["period"] = sm["week"].dt.strftime("%Y-%m")
    sm["over"] = sm["lt_roll26w"] > LEAD_REVIEW_RATIO * sm["supplier_id"].map(sup_master)
    spiv = sm.pivot(index="supplier_id", columns="period", values="over").fillna(False).sort_index(axis=1)

    def reviews(p, per):
        cols = list(p.columns)
        if per not in cols or cols.index(per) < LEAD_REVIEW_MONTHS - 1:
            return []
        window = cols[cols.index(per) - LEAD_REVIEW_MONTHS + 1: cols.index(per) + 1]
        return sorted(p.index[p[window].all(axis=1)].tolist())

    short_by, uom = cur.short_by, cur.uom_gap

    factors = {r["period"]: r["bias_factors"] for r in retrains}
    periods, feat_rows, prev_f = [], [], None
    for per, g in live.groupby("period"):
        sc = g[g["scored"] & g["target"].notna()]
        o = {"period": per, "n_forecasts": int(len(g)), "n_scored": int(len(sc)),
             "wape": _wape(sc["target"], sc["forecast"]), "base_wape": _wape(sc["target"], sc["base"]),
             "bias": float((sc["forecast"].sum() - sc["target"].sum()) / sc["target"].sum()) if len(sc) else np.nan,
             "target_drift": _js(ref["target"], sc["target"]),
             "prediction_drift": _js(bt[f"predc_{kind}"], g["forecast"])}
        pat_w, pat_b, worst_w, worst_b = {}, {}, 0.0, 0.0
        for sg, gg in sc.groupby("segment"):
            if len(gg) < MIN_ROWS:
                continue
            pat_w[sg] = _wape(gg["target"], gg["forecast"])
            pat_b[sg] = float((gg["forecast"].sum() - gg["target"].sum()) / gg["target"].sum())
            worst_w = max(worst_w, pat_w[sg] - ref_pat[sg]["wape"]); worst_b = max(worst_b, abs(pat_b[sg]))
        o.update(pattern_wape=pat_w, pattern_bias=pat_b, worst_wape_gap=worst_w, worst_bias=worst_b)
        # corrected bias by pattern x tier, against the bias threshold
        cell = {}
        for (sg, tr_), gg in sc.groupby(["segment", "tier"]):
            if len(gg) >= MIN_ROWS:
                cell[f"{sg}|{tr_}"] = float((gg["forecast"].sum() - gg["target"].sum()) / gg["target"].sum())
        o["cell_bias"] = cell
        f_now = factors.get(per, {})
        o["bias_factors"] = f_now
        moved = {k: v / prev_f[k] - 1 for k, v in f_now.items() if prev_f and k in prev_f and prev_f[k] > 0}
        o["bias_factor_change"] = moved
        # a factor is judged on its own pattern's corrected bias (factors are by pattern)
        o["bias_factor_levels"] = {k: (2 if abs(o["pattern_bias"].get(k, cell.get(k, 0.0))) > BIAS_TOL
                                       else 1 if abs(moved.get(k, 0.0)) > BIAS_TOL else 0)
                                   for k in f_now}
        if f_now:
            prev_f = f_now
        n_drift = 0
        for f in drift_feats:
            d = _js(ref[f].fillna(0), g[f].fillna(0), categorical=f in CATEGORICAL)
            feat_rows.append({"period": per, "feature": f, "group": SF.group_of(f), "drift_score": d, "drift_detected": bool(d >= DRIFT)})
            n_drift += int(d >= DRIFT)
        o.update(n_features=len(drift_feats), n_features_drifted=n_drift)
        o["lead_time_reviews_items"] = reviews(piv, per)
        o["lead_time_reviews_suppliers"] = reviews(spiv, per)
        o["data_quality"] = {**short_by.get(per, {}), "uom_gap": uom,
                             "null_feature_share": float(g[feats].isna().any(axis=1).mean()),
                             "unseen_items": int(len(set(g["item"]) - set(ref["item"])))}
        mm = fr.get("monthly", {}).get(per, {}).get("model")
        if mm:
            o.update(fill_by_tier=mm["fill_rate_by_tier"], fill_gap=max(fill_target[t] - v for t, v in mm["fill_rate_by_tier"].items()),
                     stockout_events=mm["stockout_episodes"], jobs_held=mm["jobs_delayed"], rush_spend=mm["rush_spend"],
                     end_inventory=mm["end_inventory_value"], fill_rate=mm["fill_rate"])
        o["ref_events"], o["ref_held"] = ref_events, ref_held
        periods.append(o)

    def lvl(value, inv, ret):
        return 2 if value > ret else 1 if value > inv else 0
    for o in periods:
        o["matured"] = o["n_scored"] >= MATURED * o["n_forecasts"]
        m = o["matured"]
        pat = {sg: {"wape": lvl(w_, ref_pat[sg]["wape"], ref_pat[sg]["wape"] + WAPE_TOL),
                    "bias": 2 if abs(o["pattern_bias"][sg]) > BIAS_TOL else 0}
               for sg, w_ in o["pattern_wape"].items()} if m else {}
        o["model_levels"] = {"overall_wape": lvl(o["wape"], ref_wape, ref_wape + WAPE_OVERALL_TOL) if m else 0,
                             "overall_bias": (2 if abs(o["bias"]) > BIAS_TOL else 0) if m else 0,
                             "pattern_wape": max([v["wape"] for v in pat.values()], default=0),
                             "pattern_bias": max([v["bias"] for v in pat.values()], default=0),
                             "bias_factors": (max(o["bias_factor_levels"].values(), default=0) if m else
                                              min(1, max(o["bias_factor_levels"].values(), default=0)))}
        primary = {k: v > 0 for k, v in o["model_levels"].items()}
        primary["service"] = o.get("fill_gap", 0) > FILL_TOL
        primary["outcomes"] = (o.get("stockout_events", 0) > ref_events) or (o.get("jobs_held", 0) > ref_held)
        sec = {"target_drift": m and o["target_drift"] >= DRIFT, "prediction_drift": o["prediction_drift"] >= DRIFT,
               "feature_drift": o["n_features_drifted"] > MAX_FEATS}
        o["primary"], o["secondary"] = primary, sec
        o["status"] = ("RETRAIN" if max(o["model_levels"].values()) == 2 else
                       "INVESTIGATE" if any(primary.values()) or sum(sec.values()) >= 2 else "HEALTHY")

    tables = {
        "feature_drift": pd.DataFrame(feat_rows),
        "retrain_log": pd.DataFrame([{"period": r["period"], "trained_on": r["trained_on"], "training_rows": r["training_rows"],
                                      "error_rows": r["error_rows"], "model": f"S1 {kind}"} for r in retrains]),
        "bias_factors": pd.DataFrame([{"period": p["period"], "factor_cell": k, "factor": v, "change": p["bias_factor_change"].get(k),
                                       "corrected_bias": p["pattern_bias"].get(k, p["cell_bias"].get(k)), "level": p["bias_factor_levels"][k]}
                                      for p in periods for k, v in p["bias_factors"].items()]),
        "lead_time_reviews": pd.DataFrame([{"period": p["period"], "level": lvl_, "id": i} for p in periods
                                           for lvl_, ids in [("item", p["lead_time_reviews_items"]), ("supplier", p["lead_time_reviews_suppliers"])]
                                           for i in ids]),
    }
    summary = {"model": f"S1 {kind}, static horizon", "periods": periods, "reference_pattern": ref_pat, "reference_wape": ref_wape,
               "fill_target": fill_target, "uom_gap": uom,
               "thresholds": {"drift": DRIFT, "wape_overall_tol": WAPE_OVERALL_TOL, "wape_tol": WAPE_TOL, "bias_tol": BIAS_TOL,
                              "fill_tol": FILL_TOL, "max_feats": MAX_FEATS, "min_rows": MIN_ROWS, "matured": MATURED,
                              "lead_review_ratio": LEAD_REVIEW_RATIO, "lead_review_months": LEAD_REVIEW_MONTHS},
               "latest_status": periods[-1]["status"]}
    return summary, {**tables, "live": live}


# ── tables for monitoring.* ──────────────────────────────────────────────────
def status_rows(summary: dict) -> pd.DataFrame:
    """monitoring.monthly_status: one row per month with its measures, rule levels and status."""
    rows = []
    for p in summary["periods"]:
        r = {k: p.get(k) for k in ["period", "n_forecasts", "n_scored", "matured", "wape", "base_wape", "bias",
                                    "target_drift", "prediction_drift", "worst_wape_gap", "worst_bias", "n_features",
                                    "n_features_drifted"]}
        r.update({f"level_{k}": int(v) for k, v in p["model_levels"].items()})
        r.update({f"primary_{k}": bool(v) for k, v in p["primary"].items()})
        r.update({f"secondary_{k}": bool(v) for k, v in p["secondary"].items()})
        for k in ["fill_rate", "fill_gap", "stockout_events", "jobs_held", "rush_spend", "end_inventory", "ref_events", "ref_held"]:
            r[k] = float(p[k]) if p.get(k) is not None else None
        dq = p["data_quality"]
        r.update(short_week_share=dq.get("short_week_share"), active_short_share=dq.get("active_short_share"),
                 null_feature_share=dq["null_feature_share"], unseen_items=dq["unseen_items"],
                 lead_time_review_items=len(p["lead_time_reviews_items"]),
                 lead_time_review_suppliers=len(p["lead_time_reviews_suppliers"]), status=p["status"])
        rows.append(r)
    out = pd.DataFrame(rows)
    for c in out.columns:
        if c.startswith(("level_",)) or c in ("n_forecasts", "n_scored", "n_features", "n_features_drifted", "unseen_items",
                                              "lead_time_review_items", "lead_time_review_suppliers"):
            out[c] = out[c].astype("int64")
        elif c.startswith(("primary_", "secondary_")) or c == "matured":
            out[c] = out[c].astype(bool)
        elif c not in ("period", "status"):
            out[c] = out[c].astype(float)
    return out


def pattern_rows(summary: dict) -> pd.DataFrame:
    """monitoring.pattern_metrics: WAPE and corrected bias by month and pattern, with the 2025 reference."""
    ref = summary["reference_pattern"]
    rows = [{"period": p["period"], "segment": sg, "wape": float(p["pattern_wape"][sg]), "bias": float(p["pattern_bias"][sg]),
             "reference_wape": float(ref[sg]["wape"]), "reference_bias": float(ref[sg]["bias"]), "matured": bool(p["matured"])}
            for p in summary["periods"] for sg in p["pattern_wape"]]
    return pd.DataFrame(rows, columns=["period", "segment", "wape", "bias", "reference_wape", "reference_bias", "matured"])


def cell_rows(summary: dict) -> pd.DataFrame:
    """monitoring.cell_bias: corrected bias by month, pattern and criticality tier."""
    rows = [{"period": p["period"], "segment": k.split("|")[0], "tier": k.split("|")[1], "corrected_bias": float(v)}
            for p in summary["periods"] for k, v in p["cell_bias"].items()]
    return pd.DataFrame(rows, columns=["period", "segment", "tier", "corrected_bias"])


def error_rows(live: pd.DataFrame, weeks: pd.DatetimeIndex, model_version: str) -> pd.DataFrame:
    """monitoring.forecast_errors: each issued forecast with its actual once scored (the table the data
    profile reads)."""
    origin = pd.DatetimeIndex(weeks)[live["t"].to_numpy()]
    scored = live["scored"].fillna(False).astype(bool) & live["target"].notna()
    out = pd.DataFrame({"canonical_item_number": live["item"].to_numpy(), "origin_week": origin.date,
                        "origin_ts": origin.astype("datetime64[us]"), "period": live["period"].to_numpy(),
                        "segment": live["segment"].to_numpy(), "tier": live["tier"].to_numpy(),
                        "horizon_weeks": live["h"].astype("Int64").to_numpy(),
                        "forecast": live["forecast"].astype(float).to_numpy(),
                        "actual": np.where(scored, live["target"].astype(float), np.nan),
                        "scored": scored.to_numpy(), "model_version": model_version})
    out["error"] = out["forecast"] - out["actual"]
    return out
