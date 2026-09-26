"""Monthly monitoring of the live demand model, January to June 2026, for the MLOps report.

For each live month it scores the forecasts whose lead-time window has closed, and
compares the month against references fixed before go-live:

  performance     WAPE and bias of the bias-corrected forecast, overall and by demand pattern,
                  against the same measures on the held-out 2025 year
  target drift    Jensen-Shannon distance of actual lead-time usage vs the training rows
  prediction drift  distance of the month's forecasts vs the 2025 held-out forecasts
  feature drift   distance of each input feature vs the training rows
  data quality    nulls, negatives, missing attributes and unseen items in the month's inputs
  outcomes        fill rate by criticality, stockout events and held jobs from the replay

and evaluates the retraining rules in the technical report. Writes to ml/data/monitoring/.

Run:  python -m ml.src.monitor_weekly
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.spatial.distance import jensenshannon

from .forward_policy import build_frame, FEATS, _monday, MARTS, BACKTEST, OUT as POLICY
from data_source.generate import config as C

MON = BACKTEST.parent / "monitoring"
TRUTH = C.REPO_ROOT / "data_source" / "truth"
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


def run():
    MON.mkdir(parents=True, exist_ok=True)
    weekly = pd.read_parquet(MARTS / "consumption_weekly.parquet")
    attrs = pd.read_parquet(MARTS / "item_attributes.parquet").set_index("canonical_item_number")
    sched = json.loads((POLICY / "rop_schedule.json").read_text())
    metrics = json.loads((BACKTEST / "weekly_metrics.json").read_text())
    fr = json.loads((TRUTH / "forward_results.json").read_text())
    bt = pd.read_parquet(BACKTEST / "weekly_backtest.parquet")

    frame, weeks = build_frame(weekly, attrs)
    frame["nan_feats"] = (frame[FEATS].isna() | np.isinf(frame[FEATS].astype(float))).sum(axis=1)
    frame[FEATS] = frame[FEATS].replace([np.inf, -np.inf], np.nan).fillna(0)
    widx = {w: i for i, w in enumerate(weeks)}
    t_test0 = widx[pd.Timestamp(_monday(date(2025, 1, 1) + timedelta(days=7)))]
    t_val0 = t_test0 - 26
    t_end = widx[pd.Timestamp(_monday(C.END_DATE))]            # the partial last week is not scored
    ref = frame[frame["t"] + frame["h"] <= t_val0]            # the training rows

    # the live forecasts, one per item per weekly refresh
    rows = []
    for item, entries in sched["items"].items():
        for e in entries:
            o = pd.Timestamp(e[0]); mon = pd.Timestamp(_monday(o.date()))
            if mon in widx:
                rows.append((item, widx[mon], o.strftime("%Y-%m"), float(e[3])))
    fc = pd.DataFrame(rows, columns=["item", "t", "period", "forecast"])
    live = fc.merge(frame, on=["item", "t"], how="left")
    live["scored"] = live["t"] + live["h"] <= t_end
    meth = {r["segment"]: r["baseline_method"] for r in metrics["segments"]}
    base = {"ma4": live["s4"] / 4, "ma13": live["s13"] / 13, "ma52": live["s52"] / 52}
    live["base"] = [(live.at[i, "ly"] if meth.get(sg) == "snaive" else base.get(meth.get(sg, "ma52"), base["ma52"])[i] * live.at[i, "h"])
                    for i, sg in zip(live.index, live["segment"])]

    # references fixed before go-live
    ref_pat = {sg: {"wape": _wape(g["actual"], g["pred_c"]),
                    "bias": float((g["pred_c"].sum() - g["actual"].sum()) / g["actual"].sum())}
               for sg, g in bt.groupby("segment")}
    ref_wape = _wape(bt["actual"], bt["pred_c"])
    fill_target = sched["fill_rate_target"]
    m25 = fr.get("monthly_2025", {})
    ref_events = float(np.mean([v["stockout_episodes"] for v in m25.values()])) if m25 else np.nan
    ref_held = float(np.mean([v["jobs_delayed"] for v in m25.values()])) if m25 else np.nan
    train_items = set(ref["item"])

    periods, feat_rows = [], []
    for per, g in live.groupby("period"):
        sc = g[g["scored"] & g["target"].notna()]
        out = {"period": per, "n_forecasts": int(len(g)), "n_scored": int(len(sc)),
               "wape": _wape(sc["target"], sc["forecast"]), "base_wape": _wape(sc["target"], sc["base"]),
               "bias": float((sc["forecast"].sum() - sc["target"].sum()) / sc["target"].sum()) if len(sc) else np.nan,
               "target_drift": _js(ref["target"], sc["target"]),
               "prediction_drift": _js(bt["pred_c"], g["forecast"])}
        worst_w, worst_b, pat_w, pat_b = 0.0, 0.0, {}, {}
        for sg, gg in sc.groupby("segment"):
            if len(gg) < MIN_ROWS:
                continue
            w_ = _wape(gg["target"], gg["forecast"]); b_ = float((gg["forecast"].sum() - gg["target"].sum()) / gg["target"].sum())
            pat_w[sg], pat_b[sg] = w_, b_
            worst_w = max(worst_w, w_ - ref_pat[sg]["wape"]); worst_b = max(worst_b, abs(b_))
        out["pattern_wape"], out["pattern_bias"] = pat_w, pat_b
        out["worst_wape_gap"], out["worst_bias"] = worst_w, worst_b

        n_drift = 0
        for f in FEATS:
            if f in CALENDAR:
                continue
            d = _js(ref[f], g[f], categorical=f in CATEGORICAL)
            feat_rows.append({"period": per, "feature": f, "drift_score": d, "drift_detected": bool(d >= DRIFT)})
            n_drift += int(d >= DRIFT)
        out["n_features"] = len(FEATS) - len(CALENDAR)
        out["n_features_drifted"] = n_drift

        # data quality of the month's inputs
        out["null_feature_share"] = float((g["nan_feats"] > 0).mean())
        wk = weekly[(weekly["week"] >= pd.Timestamp(per + "-01")) & (weekly["week"] < pd.Timestamp(per + "-01") + pd.offsets.MonthBegin(1))]
        out["usage_rows"] = int(len(wk)); out["negative_usage"] = int((wk["consumption"] < 0).sum())
        out["items_scored"] = int(g["item"].nunique())
        out["unseen_items"] = int(len(set(g["item"]) - train_items))
        out["missing_attributes"] = int(attrs.loc[attrs.index.isin(g["item"]), ["standard_cost", "corrected_lead_days", "segment", "abc"]]
                                        .isna().any(axis=1).sum())
        out["max_week_usage_vs_ref"] = float(wk["consumption"].max() / max(1.0, weekly[weekly["week"] < pd.Timestamp("2025-01-01")]["consumption"].max())) if len(wk) else np.nan

        # outcomes from the replay
        mm = fr.get("monthly", {}).get(per, {}).get("model")
        if mm:
            out["fill_by_tier"] = mm["fill_rate_by_tier"]
            out["fill_gap"] = max(fill_target[t] - v for t, v in mm["fill_rate_by_tier"].items())
            out["stockout_events"] = mm["stockout_episodes"]; out["jobs_held"] = mm["jobs_delayed"]
            out["rush_spend"] = mm["rush_spend"]; out["end_inventory"] = mm["end_inventory_value"]
            out["fill_rate"] = mm["fill_rate"]
        out["ref_events"], out["ref_held"] = ref_events, ref_held
        periods.append(out)

    # rules and status. Accuracy is judged only on months whose forecasts have mostly matured.
    # Model rules have two levels: 1 = investigate, 2 = retrain. A fill-rate shortfall calls for
    # recalibrating the buffers, not retraining the model.
    def lvl(value, inv, ret):
        return 2 if value > ret else 1 if value > inv else 0

    for out in periods:
        out["matured"] = out["n_scored"] >= MATURED * out["n_forecasts"]
        m = out["matured"]
        pat = {sg: {"wape": lvl(w_, ref_pat[sg]["wape"], ref_pat[sg]["wape"] + WAPE_TOL),
                    "bias": 2 if abs(out["pattern_bias"][sg]) > BIAS_TOL else 0}
               for sg, w_ in out["pattern_wape"].items()} if m else {}
        out["pattern_levels"] = pat
        out["model_levels"] = {
            "overall_wape": lvl(out["wape"], ref_wape, ref_wape + WAPE_OVERALL_TOL) if m else 0,
            "overall_bias": (2 if abs(out["bias"]) > BIAS_TOL else 0) if m else 0,
            "pattern_wape": max([v["wape"] for v in pat.values()], default=0),
            "pattern_bias": max([v["bias"] for v in pat.values()], default=0)}
        model = {k: v > 0 for k, v in out["model_levels"].items()}
        policy = {"service": out.get("fill_gap", 0) > FILL_TOL}
        guard = {"outcomes": (out.get("stockout_events", 0) > ref_events) or (out.get("jobs_held", 0) > ref_held)}
        sec = {"target_drift": out["matured"] and out["target_drift"] >= DRIFT,
               "prediction_drift": out["prediction_drift"] >= DRIFT,
               "feature_drift": out["n_features_drifted"] > MAX_FEATS}
        out["primary"] = {**model, **policy, **guard}
        out["secondary"] = sec
        out["status"] = ("RETRAIN" if max(out["model_levels"].values()) == 2 else
                         "INVESTIGATE" if any(out["primary"].values()) or sum(sec.values()) >= 2 else "HEALTHY")

    # the monthly retrains the forward policy performed
    log = []
    for o in sorted({pd.Timestamp(e[0]) for es in sched["items"].values() for e in es}):
        if o.strftime("%Y-%m") in [l["period"] for l in log]:
            continue
        t_o = widx[pd.Timestamp(_monday(o.date()))]
        log.append({"period": o.strftime("%Y-%m"), "trained_on": o.date().isoformat(),
                    "training_rows": int((frame["t"] + frame["h"] <= t_o).sum()),
                    "history_through": str(weeks[t_o - 1].date()), "model": metrics["winner"]})
    pd.DataFrame(log).to_csv(MON / "retrain_log.csv", index=False)
    pd.DataFrame(feat_rows).to_csv(MON / "feature_drift.csv", index=False)
    summary = {"periods": periods, "reference_pattern": ref_pat, "reference_wape": ref_wape, "fill_target": fill_target,
               "thresholds": {"drift": DRIFT, "wape_overall_tol": WAPE_OVERALL_TOL, "wape_tol": WAPE_TOL, "bias_tol": BIAS_TOL, "fill_tol": FILL_TOL,
                              "max_feats": MAX_FEATS, "min_rows": MIN_ROWS, "matured": MATURED},
               "ref_events": ref_events, "ref_held": ref_held, "latest_status": periods[-1]["status"]}
    (MON / "monitoring_summary.json").write_text(json.dumps(summary, indent=2, default=float))
    for p_ in periods:
        print(f"  {p_['period']}  scored {p_['n_scored']:>5,}/{p_['n_forecasts']:>5,}  WAPE {p_['wape']*100:5.1f}%  bias {p_['bias']*100:+5.1f}%  "
              f"target {p_['target_drift']:.3f}  pred {p_['prediction_drift']:.3f}  feats {p_['n_features_drifted']}  "
              f"fill gap {p_.get('fill_gap', 0)*100:+.1f}  events {p_.get('stockout_events')}  held {p_.get('jobs_held')}  -> {p_['status']}")
    print("  primary:", [(p_['period'], [k for k, v in p_['primary'].items() if v]) for p_ in periods])


if __name__ == "__main__":
    run()
