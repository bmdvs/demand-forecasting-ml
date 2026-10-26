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

Run:  python -m ml.src.monitor_weekly              (the weekly model, for the published report)
      python -m ml.src.monitor_weekly --signals    (the S1 demand-signal production model)
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.spatial.distance import jensenshannon

from .demand_model import build_frame, FEATS, _monday, MARTS, BACKTEST, OUT as POLICY
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


# ── the demand-signal production model (S1, static horizon) ──────────────────
LEAD_REVIEW_RATIO = 1.25   # pooled 26-week lead time this far above the corrected master...
LEAD_REVIEW_MONTHS = 2     # ...for this many consecutive month-ends raises a lead-time review


def run_signals(ladder_dir=None, policy_dir=None, forward_results=None, out_dir=None):
    """Monthly monitoring of the S1 production model (order-book features, uncovered target,
    static horizon), January to June 2026, with the thresholds above unchanged. Beyond the
    weekly model's checks it tracks the S1 feature groups for drift, the bias factors the
    policy re-estimates at each retrain by demand pattern (with corrected bias also shown by
    pattern x criticality tier), the lead-time
    review signal from the pooled supplier lead time, and, under data quality, the book-side
    short-week shares and the receipts' unit-of-measure gap. Writes ml/data/monitoring/signals/."""
    import duckdb, os
    from . import signal_ladder as L
    from . import signal_features as SF
    repo = C.REPO_ROOT
    lad = Path(ladder_dir) if ladder_dir else repo / "runs" / "ladder"
    fwd = Path(policy_dir) if policy_dir else repo / "runs" / "forward" / "s1_static"
    out_dir = Path(out_dir) if out_dir else MON / "signals"; out_dir.mkdir(parents=True, exist_ok=True)
    res = json.loads((lad / "metrics_S1.json").read_text())
    feats = res["features"]
    sched = json.loads((fwd / "rop_schedule.json").read_text())
    fr = json.loads((Path(forward_results) if forward_results else fwd / "forward_results.json").read_text())
    retrains = json.loads((fwd / "retrain_log.json").read_text())
    bt = pd.read_parquet(lad / "pred_S1.parquet")
    inp = L.load_inputs()
    frame, ctx = L.prepare_frame(inp)
    weeks = ctx["weeks"]
    widx = {w: i for i, w in enumerate(weeks)}
    t_test0 = widx[pd.Timestamp(_monday(date(2025, 1, 1) + timedelta(days=7)))]
    t_val0 = t_test0 - 26
    t_end = widx[pd.Timestamp(_monday(C.END_DATE))]
    frame = frame[frame["is_reference_row"]]
    ref = frame[frame["t"] + frame["h"] <= t_val0]

    rows = []
    for item, entries in sched["items"].items():
        for e in entries:
            mon = pd.Timestamp(_monday(pd.Timestamp(e[0]).date()))
            if mon in widx:
                rows.append((item, widx[mon], pd.Timestamp(e[0]).strftime("%Y-%m"), float(e[3])))
    live = pd.DataFrame(rows, columns=["item", "t", "period", "forecast"]).merge(frame, on=["item", "t"], how="left")
    live["scored"] = live["t"] + live["h"] <= t_end
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
    sup_lt = pd.read_parquet(MARTS / "supplier_leadtime_weekly.parquet"); sup_lt["week"] = pd.to_datetime(sup_lt["week"])
    im = pd.read_csv(C.RAW_DIR / "erp" / "item_master.csv").set_index("item_number")["primary_supplier_id"]
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

    # data quality from the warehouse: book-side short weeks and the receipts' unit gap
    cwd = os.getcwd(); os.chdir(repo / "data_pipeline")
    try:
        con = duckdb.connect(str(repo / "data_source" / "demand_forecasting.duckdb"), read_only=True)
        shortq = con.execute("""select strftime(week, '%Y-%m') as period,
                                       avg(case when short_week then 1.0 else 0 end), avg(case when short_active_week then 1.0 else 0 end)
                                from mart_shortage_weekly where week >= date '2026-01-01' group by 1""").fetchall()
        uom = con.execute("""
            with conv as (
              select c.canonical_item_number,
                     sum(case c.txn_type when 'RECEIPT' then c.qty when 'ADJUST' then c.qty else -abs(c.qty) end) as as_is,
                     sum(case c.txn_type when 'RECEIPT' then c.qty * coalesce(u.conversion, 1) when 'ADJUST' then c.qty else -abs(c.qty) end) as conv
              from int_transactions_corrected c join stg_erp__inventory_transactions t on t.txn_id = c.txn_id
              left join stg_remediation__uom_conversions u on u.item_number = c.item_number and u.purchase_uom = t.uom and u.stock_uom <> t.uom
              group by 1)
            select count(*) filter (where as_is <> conv),
                   sum(greatest(as_is, 0) * a.standard_cost) filter (where as_is <> conv),
                   sum(greatest(conv, 0) * a.standard_cost) filter (where as_is <> conv),
                   sum(greatest(as_is, 0) * a.standard_cost)
            from conv join mart_item_attributes a using (canonical_item_number)""").fetchone()
        con.close()
    finally:
        os.chdir(cwd)
    short_by = {p: {"short_week_share": s, "active_short_share": a} for p, s, a in shortq}
    uom_gap = {"items": int(uom[0]), "on_hand_value_as_booked": float(uom[1]), "on_hand_value_converted": float(uom[2]),
               "understatement_of_total": float((uom[2] - uom[1]) / uom[3])}

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
        o["data_quality"] = {**short_by.get(per, {}), "uom_gap": uom_gap,
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

    pd.DataFrame(feat_rows).to_csv(out_dir / "feature_drift.csv", index=False)
    pd.DataFrame([{"period": r["period"], "trained_on": r["trained_on"], "training_rows": r["training_rows"],
                   "error_rows": r["error_rows"], "model": f"S1 {kind}"} for r in retrains]).to_csv(out_dir / "retrain_log.csv", index=False)
    pd.DataFrame([{"period": p["period"], "factor_cell": k, "factor": v, "change": p["bias_factor_change"].get(k),
                   "corrected_bias": p["pattern_bias"].get(k, p["cell_bias"].get(k)), "level": p["bias_factor_levels"][k]}
                  for p in periods for k, v in p["bias_factors"].items()]).to_csv(out_dir / "bias_factors.csv", index=False)
    pd.DataFrame([{"period": p["period"], "level": lvl_, "id": i} for p in periods
                  for lvl_, ids in [("item", p["lead_time_reviews_items"]), ("supplier", p["lead_time_reviews_suppliers"])]
                  for i in ids]).to_csv(out_dir / "lead_time_reviews.csv", index=False)
    summary = {"model": f"S1 {kind}, static horizon", "periods": periods, "reference_pattern": ref_pat, "reference_wape": ref_wape,
               "fill_target": fill_target, "uom_gap": uom_gap,
               "thresholds": {"drift": DRIFT, "wape_overall_tol": WAPE_OVERALL_TOL, "wape_tol": WAPE_TOL, "bias_tol": BIAS_TOL,
                              "fill_tol": FILL_TOL, "max_feats": MAX_FEATS, "min_rows": MIN_ROWS, "matured": MATURED,
                              "lead_review_ratio": LEAD_REVIEW_RATIO, "lead_review_months": LEAD_REVIEW_MONTHS},
               "latest_status": periods[-1]["status"]}
    (out_dir / "monitoring_summary.json").write_text(json.dumps(summary, indent=2, default=float))
    for p in periods:
        dq = p["data_quality"]
        print(f"  {p['period']}  scored {p['n_scored']:>5,}/{p['n_forecasts']:>5,}  WAPE {p['wape']*100:5.1f}%  base {p['base_wape']*100:5.1f}%  "
              f"bias {p['bias']*100:+5.1f}%  pred {p['prediction_drift']:.3f}  feats {p['n_features_drifted']}/{p['n_features']}  "
              f"factor flags {sum(1 for v in p['bias_factor_levels'].values() if v)}  lead reviews {len(p['lead_time_reviews_items'])} items "
              f"{len(p['lead_time_reviews_suppliers'])} suppliers  short {dq.get('short_week_share', 0)*100:.1f}% active {dq.get('active_short_share', 0)*100:.1f}%  -> {p['status']}")


if __name__ == "__main__":
    import sys
    if "--signals" in sys.argv:
        # --signals [--ladder DIR] [--policy DIR] [--forward-results FILE] [--out DIR]
        arg = lambda k: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else None
        run_signals(arg("--ladder"), arg("--policy"), arg("--forward-results"), arg("--out"))
    else:
        run()
