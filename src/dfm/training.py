"""Candidates, tuning and selection for the weekly demand forecast.

Three candidate regressors (ridge on standardized features, a random forest and a gradient-boosted tree)
are tuned with Optuna on a validation block (seeded TPE sampler, seed 42), compared on validation WAPE
and refit on train plus validation. weekly_backtest is the weekly reference model on the reference
features. The rung functions train every rung of the demand-signal ladder on the same rows and target:
total demand over the reference horizon. From S1 the model learns the demand the order book does not
already cover and the forecast is firm requirements plus that; from S3 training rows whose target window
holds a short week on a line-critical part are half-weighted and service backorders count in the week
ordered; from S4 rows from week 13 of an item's history train the model, missing where a year of history
is needed, and parts with under 13 weeks take a class-and-family prior.

prepare_frame builds every feature once from the inputs; run_rung is a pure function of the frame and
returns metrics and predictions. Prediction runs on one thread (see predict).
"""
from __future__ import annotations

import warnings
from datetime import date, timedelta

import numpy as np
import optuna
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from . import config as C
from . import features as F
from .features import FEATS, _monday, build_frame
from .policy import SERVICE, Z_BY_ABC

warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)

_CAP = None          # cap on any forecast, so a linear model cannot extrapolate absurdly


def _wape(a, f):
    d = np.asarray(a).sum()
    return np.abs(np.asarray(a) - np.asarray(f)).sum() / d if d else np.nan


def predict(model, X):
    """Predict on one thread. A random forest predicting across threads sums its
    trees in whatever order the threads finish, so repeated runs differ in the
    last bits; training stays parallel (every tree is seeded)."""
    est = model.steps[-1][1] if hasattr(model, "steps") else model
    if isinstance(est, RandomForestRegressor) and est.n_jobs != 1:
        jobs, est.n_jobs = est.n_jobs, 1
        try:
            return model.predict(X)
        finally:
            est.n_jobs = jobs
    return model.predict(X)


def _fit_predict(model, Xtr, ytr, Xte):
    model.fit(Xtr, np.log1p(ytr))
    return np.clip(np.expm1(predict(model, Xte)), 0, _CAP)


def _make(kind, p):
    if kind == "Linear":
        return make_pipeline(StandardScaler(), Ridge(alpha=p["alpha"]))
    if kind == "RandomForest":
        return RandomForestRegressor(n_estimators=p["n_estimators"], max_depth=p["max_depth"],
                                     min_samples_leaf=p["min_samples_leaf"], n_jobs=-1, random_state=42)
    return XGBRegressor(n_estimators=p["n_estimators"], max_depth=p["max_depth"],
                        learning_rate=p["learning_rate"], subsample=p["subsample"],
                        colsample_bytree=p["colsample_bytree"], min_child_weight=p["min_child_weight"],
                        reg_lambda=p["reg_lambda"], random_state=42, n_jobs=-1)


def _space(trial, kind):
    if kind == "Linear":
        return {"alpha": trial.suggest_float("alpha", 0.01, 100.0, log=True)}
    if kind == "RandomForest":
        return {"n_estimators": trial.suggest_int("n_estimators", 150, 400, step=50),
                "max_depth": trial.suggest_int("max_depth", 5, 16),
                "min_samples_leaf": trial.suggest_int("min_samples_leaf", 1, 8)}
    return {"n_estimators": trial.suggest_int("n_estimators", 250, 600, step=50),
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.15, log=True),
            "subsample": trial.suggest_float("subsample", 0.7, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 8),
            "reg_lambda": trial.suggest_float("reg_lambda", 0.5, 4.0)}


# ── the weekly reference model ──────────────────────────────────────────────
def _tune_weekly(kind, trn, val):
    def objective(trial):
        p = _space(trial, kind)
        return _wape(val["target"], _fit_predict(_make(kind, p), trn[FEATS], trn["target"], val[FEATS]))
    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)
    return study.best_params, study.best_value


def _baselines(frame):
    """Simple methods scaled to the horizon: 4-, 13- and 52-week rates and last year's same weeks."""
    return pd.DataFrame({"ma4": frame["s4"] / 4 * frame["h"], "ma13": frame["s13"] / 13 * frame["h"],
                         "ma52": frame["s52"] / 52 * frame["h"], "snaive": frame["ly"]}, index=frame.index)


def weekly_backtest(weekly: pd.DataFrame, attrs: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """The weekly reference model as of the planning-window start: candidates tuned on validation
    weeks, the winner scored on the held-out 2025 origins against each pattern's best simple method,
    with the bias correction and calibrated safety factors from the 2025 errors. Returns the metrics
    document and the test rows with their predictions."""
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    frame, weeks = build_frame(weekly, attrs)
    frame[FEATS] = frame[FEATS].replace([np.inf, -np.inf], np.nan).fillna(0)
    week_idx = {w: i for i, w in enumerate(weeks)}
    t_fwd = week_idx[pd.Timestamp(_monday(C.FORWARD_START))]      # first week of the forward window

    # ── backtest as of the forward start: train / validation / held-out 2025 ─
    t_test0 = week_idx[pd.Timestamp(_monday(date(2025, 1, 1) + timedelta(days=7)))]
    t_val0 = t_test0 - 26
    known = frame["t"] + frame["h"] <= t_fwd
    test = frame[known & (frame["t"] >= t_test0)].copy()
    val = frame[(frame["t"] >= t_val0) & (frame["t"] + frame["h"] <= t_test0)]
    trn = frame[frame["t"] + frame["h"] <= t_val0]
    global _CAP
    _CAP = float(pd.concat([trn, val])["target"].max()) * 4
    results = {}
    for kind in ["Linear", "RandomForest", "XGBoost"]:
        bp, vw = _tune_weekly(kind, trn, val)
        tv = pd.concat([trn, val])
        tw_ = _wape(test["target"], _fit_predict(_make(kind, bp), tv[FEATS], tv["target"], test[FEATS]))
        results[kind] = {"params": bp, "val_wape": vw, "test_wape": tw_}
    winner = min(results, key=lambda k_: results[k_]["val_wape"])
    if winner != "XGBoost" and results["XGBoost"]["val_wape"] <= results[winner]["val_wape"] + 0.005:
        winner = "XGBoost"
    params = results[winner]["params"]
    tv = pd.concat([trn, val])
    test["pred"] = _fit_predict(_make(winner, params), tv[FEATS], tv["target"], test[FEATS])
    base = _baselines(test)
    seg_method = {sg: min(base.columns, key=lambda b: _wape(g["target"], base.loc[g.index, b]))
                  for sg, g in test.groupby("segment")}
    test["base"] = [base.at[i, seg_method[sg]] for i, sg in zip(test.index, test["segment"])]

    # bias correction, per-item error and the calibrated safety factor, all from 2025
    bias = (test.groupby("segment")["target"].sum() / test.groupby("segment")["pred"].sum()).to_dict()
    test["pred_c"] = test["pred"] * test["segment"].map(bias)
    resid = (test["target"] - test["pred_c"]).groupby(test["item"]).std()
    std_err = ((test["target"] - test["pred_c"]) / test["item"].map(resid)).replace([np.inf, -np.inf], np.nan)
    k_abc = {a_: float(np.nanquantile(std_err[test["abc"] == a_], q)) for a_, q in SERVICE.items()}
    # the loss function of the standardized errors, per class: expected units
    # short per cycle, in standard errors, for a buffer of k standard errors
    k_grid = np.round(np.arange(0.0, 6.001, 0.01), 2)
    loss = {}
    for a_ in SERVICE:
        z_ = std_err[test["abc"] == a_].dropna().to_numpy()
        loss[a_] = np.array([np.maximum(z_ - k_, 0).mean() for k_ in k_grid])

    seg_rows = []
    for sg in ["smooth", "erratic", "lumpy", "intermittent"]:
        g = test[test["segment"] == sg]
        wm, wb = _wape(g["target"], g["pred"]), _wape(g["target"], g["base"])
        seg_rows.append({"segment": sg, "wape_model": wm, "wape_baseline": wb, "lift": (wb - wm) / wb,
                         "bias": float((g["pred"] - g["target"]).sum() / g["target"].sum()),
                         "baseline_method": seg_method[sg]})
    overall = {"model": _wape(test["target"], test["pred"]), "baseline": _wape(test["target"], test["base"])}
    metrics = {"winner": winner, "candidates": results, "segments": seg_rows, "overall": overall,
               "bias_correction": bias, "safety_factor": k_abc, "normal_z": Z_BY_ABC}
    return metrics, test.rename(columns={"target": "actual"})


# ── the demand-signal ladder ────────────────────────────────────────────────
N_TRIALS = 12
KINDS = ["Linear", "RandomForest", "XGBoost"]


def criticality(inp: dict, items) -> dict:
    """line (on a corrected bill), service (issued to service orders in 2024-25), standard."""
    xw = inp["xw"]
    on_bill = set(inp["bom_raw"]["component_item"].map(lambda n: xw.get(n, n))) | \
        set(inp["restored"]["component_item"].map(lambda n: xw.get(n, n)))
    tx = inp["tx"]
    svc = tx[tx["job_id"].astype(str).str.startswith("SO-") & (tx["txn_date"] >= "2024-01-01")
             & (tx["txn_date"] < C.FORWARD_START.isoformat())]
    on_service = set(svc["item_number"].map(lambda n: xw.get(n, n)))
    return {i: ("line" if i in on_bill else "service" if i in on_service else "standard") for i in items}


def prepare_frame(inp: dict) -> tuple[pd.DataFrame, dict]:
    weekly, attrs = inp["weekly"], inp["attrs"]
    ref, weeks = build_frame(weekly, attrs)
    ref[FEATS] = ref[FEATS].replace([np.inf, -np.inf], np.nan).fillna(0)
    ref["is_reference_row"] = True
    extra = F.extra_history_rows(weekly, attrs, weeks, 13, 52)
    extra[[c for c in FEATS if c not in F.NULLABLE_52]] = \
        extra[[c for c in FEATS if c not in F.NULLABLE_52]].replace([np.inf, -np.inf], np.nan).fillna(0)
    extra["is_reference_row"] = False
    frame = pd.concat([ref, extra], ignore_index=True).sort_values(["item", "t"]).reset_index(drop=True)
    items = sorted(frame["item"].unique())
    xw = inp["xw"]

    wide = weekly.pivot(index="canonical", columns="week", values="consumption").reindex(index=items, columns=weeks).fillna(0).to_numpy()
    tx = inp["tx"]
    bf = tx[tx["type"] == "BACKFLUSH"].copy()
    bf["canonical_item_number"] = bf["item_number"].map(lambda n: xw.get(n, n))
    bf["week"] = pd.to_datetime(bf["txn_date"]) - pd.to_timedelta(pd.to_datetime(bf["txn_date"]).dt.weekday, unit="D")
    bf["qty"] = bf["qty"].abs()
    bfw = F.item_matrix(bf, items, weeks, "qty")
    svc = inp["svc"].copy()
    svc["canonical_item_number"] = svc["item_number"].map(lambda n: xw.get(n, n))
    gap = (pd.to_datetime(svc["ship_date"]) - pd.to_datetime(svc["order_date"])).dt.days
    backorders = svc[gap > 5]

    feats = [F.firm_features(frame, inp["job_req"], weeks)]
    frame = pd.concat([frame] + feats, axis=1)
    frame["book_cover"] = np.where(frame["s13"] > 0, frame["firm_h"] / np.maximum(frame["s13"] / 13, 1e-9), np.nan)
    fam_sets = F.item_family_sets(inp["job_req"])
    frame = pd.concat([frame, F.family_book_features(frame, fam_sets, inp["pf_weekly"], inp["job_req"], weeks),
                       F.family_usage_features(frame, inp["item_family"], inp["fam_usage"], weeks)], axis=1)
    sh, S = F.shortage_features(frame, inp["shortage"], items, weeks)
    frame = pd.concat([frame, sh, F.lifecycle_features(frame, inp["lifecycle"], inp["bom"], inp["ib_item"], weeks),
                       F.leadtime_features(frame, inp["lt_item"]),
                       F.calendar_features(frame, inp["dim_week"], wide, items, weeks)], axis=1)
    frame["short_in_target"] = F.short_in_target_window(frame, S, items)
    # backflush over the target window, for the order book's own timing error
    ii = frame["item"].map({it: k for k, it in enumerate(items)}).to_numpy()
    frame["bf_window"] = F.gather_window(F.cumsum_rows(bfw), ii, frame["t"].to_numpy(), (frame["t"] + frame["h"]).to_numpy())
    frame["backorder_shift"] = F.backorder_shift(frame, backorders, items, weeks)
    unscheduled = np.maximum(wide - bfw, 0.0)
    frame = pd.concat([frame, F.simple_methods(frame, F.cumsum_rows(unscheduled), items)], axis=1)
    tier = criticality(inp, items)
    frame["tier"] = frame["item"].map(tier)
    frame["item_class"] = frame["item"].map(attrs["item_class"])
    frame["family"] = frame["item"].map(inp["item_family"].set_index("canonical_item_number")["family"])

    wi = F.week_index(weeks)
    t_fwd = wi[pd.Timestamp(_monday(C.FORWARD_START))]
    t_test0 = wi[pd.Timestamp(_monday(date(2025, 1, 1) + timedelta(days=7)))]
    t_val0 = t_test0 - 26
    known = frame["t"] + frame["h"] <= t_fwd
    frame["split"] = np.select(
        [frame["is_reference_row"] & known & (frame["t"] >= t_test0),
         (frame["t"] >= t_val0) & (frame["t"] + frame["h"] <= t_test0),
         frame["t"] + frame["h"] <= t_val0],
        ["test", "val", "train"], default="none")
    # the reference rung's validation and test rows are reference rows only (as in the weekly model)
    frame.loc[(frame["split"] == "val") & ~frame["is_reference_row"], "split"] = "none"
    return frame, {"weeks": weeks, "items": items}


def _fit(kind, params, X, y, w):
    model = _make(kind, params)
    X = X.fillna(0) if kind == "Linear" else X
    if w is None:
        model.fit(X, np.log1p(y))
    elif kind == "Linear":
        model.fit(X, np.log1p(y), ridge__sample_weight=w)
    else:
        model.fit(X, np.log1p(y), sample_weight=w)
    return model


def _predict(kind, model, X, cap):
    X = X.fillna(0) if kind == "Linear" else X
    return np.clip(np.expm1(predict(model, X)), 0, cap)


def RUNGS_AT_LEAST(rung, ref):
    base = "S1" if rung == "S1-alt" else rung
    return F.RUNGS.index(base) >= F.RUNGS.index(ref)


def _rows(frame, rung):
    """The rows a rung trains and scores on, with S4b's history rules applied."""
    s4b = RUNGS_AT_LEAST(rung, "S4b")
    f = frame[frame["is_reference_row"] | (frame["split"] == "train")] if s4b else frame[frame["is_reference_row"]]
    f = f.copy()
    if s4b:
        f.loc[f["hist_wks"] < 52, F.NULLABLE_52] = np.nan
    cold = (f["hist_wks"] < 13) if s4b else pd.Series(False, index=f.index)
    return f, cold


def run_rung(frame: pd.DataFrame, rung: str, target_change: bool = True, n_trials: int = N_TRIALS,
             lag_order_book: str | None = None, fixed: dict | None = None) -> tuple[dict, pd.DataFrame]:
    """One rung. rung is a name from F.RUNGS or "S1-alt" (the S1 features, the total target).
    target_change: from S1 on, learn uncovered demand and add firm_h back (the ladder's choice
    after S1 against S1-alt). Candidates are tuned and chosen on validation total demand.
    lag_order_book: None, "inputs" or "inputs_and_total" (the shuffle test); with fixed =
    {"kind": ..., "params": ...} the given model is refit without tuning."""
    feats = F.features_for("S1" if rung == "S1-alt" else rung)
    s1 = RUNGS_AT_LEAST(rung, "S1") and target_change and rung != "S1-alt"
    s3, s4b = RUNGS_AT_LEAST(rung, "S3"), RUNGS_AT_LEAST(rung, "S4b")
    fr = frame
    if lag_order_book:
        fr = frame.copy(); g = frame.groupby("item")
        same = (g["t"].shift(4) == frame["t"] - 4).to_numpy()
        for c in F.FORWARD_LOOKING:
            fr[c] = np.where(same, g[c].shift(4), np.nan)
        fr["firm_h_total"] = np.nan_to_num(fr["firm_h"]) if lag_order_book == "inputs_and_total" else frame["firm_h"]
    else:
        fr = frame.assign(firm_h_total=frame["firm_h"])
    f, cold = _rows(fr, rung)
    total = f["target"] + (f["backorder_shift"] if s3 else 0.0)
    f["y_train"] = np.maximum(total - f["firm_h_total"], 0.0) if s1 else total
    f["w"] = np.where(f["short_in_target"] & (f["tier"] == "line"), 0.5, 1.0) if s3 else 1.0
    trn = f[(f["split"] == "train") & ~cold & f["y_train"].notna()]
    val = f[(f["split"] == "val") & ~cold]
    test = f[f["split"] == "test"].copy()
    tv = pd.concat([trn, val])
    cap = float(tv["y_train"].max()) * 4
    global _CAP
    _CAP = cap
    X = lambda d: d[feats].astype(float)
    W = lambda d: d["w"].to_numpy() if s3 else None
    add = lambda d: d["firm_h_total"].to_numpy() if s1 else 0.0
    vwape = lambda pu: _wape(val["target"], add(val) + pu)          # validation on total demand

    results, preds = {}, {}
    kinds = [fixed["kind"]] if fixed else KINDS
    for kind in kinds:
        if fixed:
            params = fixed["params"]
        else:
            def objective(trial):
                m = _fit(kind, _space(trial, kind), X(trn), trn["y_train"], W(trn))
                return vwape(_predict(kind, m, X(val), cap))
            study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=42))
            study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
            params = study.best_params
        # the train-only fit gives the validation forecast the bias factors come from
        m_tr = _fit(kind, params, X(trn), trn["y_train"], W(trn))
        v_tot = add(val) + _predict(kind, m_tr, X(val), cap)
        factors = {sg: float(g_["target"].sum() / max(v_tot[val.index.get_indexer(g_.index)].sum(), 1e-9))
                   for sg, g_ in val.groupby("segment")}
        m = _fit(kind, params, X(tv), tv["y_train"], W(tv))
        pu = _predict(kind, m, X(test), cap)
        tot = add(test) + pu
        if s4b:
            tot = np.where(cold.loc[test.index], _cold_start_prior(f, test), tot)
        test[f"pred_{kind}"] = tot
        test[f"predc_{kind}"] = tot * test["segment"].map(factors).fillna(1.0).to_numpy()
        test[f"predu_{kind}"] = pu
        results[kind] = {"params": params, "val_wape": _wape(val["target"], v_tot),
                         "test_wape": _wape(test["target"], tot),
                         "test_wape_corrected": _wape(test["target"], test[f"predc_{kind}"]),
                         "bias_factors": factors}
        preds[kind] = m
    winner = min(results, key=lambda k: results[k]["val_wape"])
    if not fixed and winner != "XGBoost" and results["XGBoost"]["val_wape"] <= results[winner]["val_wape"] + 0.005:
        winner = "XGBoost"
    out = {"rung": rung, "target_change": s1, "features": feats, "n_features": len(feats), "winner": winner,
           "candidates": results,
           "rows": {"train": len(trn), "val": len(val), "test": len(test), "cold_start_test": int(cold.loc[test.index].sum())}}
    for label, kind in [("scores_winner", winner), ("scores_xgboost", "XGBoost")]:
        if kind not in results:
            continue
        out[label] = _scores(test, f"pred_{kind}")
        out[label]["corrected"] = _scores(test, f"predc_{kind}")
        if s1:
            out[label]["uncovered_wape"] = _wape(np.maximum(test["target"] - test["firm_h"], 0.0), test[f"predu_{kind}"])
    out["simple"] = _simple(test)
    out["models"] = preds
    return out, test


def _cold_start_prior(f, test):
    """Parts with under 13 weeks of history: the median 13-week weekly rate of parts of the
    same class and family at the same origin, over the horizon."""
    warm = f[f["hist_wks"] >= 13]
    rate = (warm["s13"] / 13).groupby([warm["t"], warm["item_class"], warm["family"]]).median()
    cls_rate = (warm["s13"] / 13).groupby([warm["t"], warm["item_class"]]).median()
    r = rate.reindex(pd.MultiIndex.from_arrays([test["t"], test["item_class"], test["family"]])).to_numpy()
    r2 = cls_rate.reindex(pd.MultiIndex.from_arrays([test["t"], test["item_class"]])).to_numpy()
    return np.nan_to_num(np.where(np.isnan(r), r2, r)) * test["h"].to_numpy()


def _scores(test, col):
    bias = lambda g: float((g[col] - g["target"]).sum() / g["target"].sum())
    out = {"wape": _wape(test["target"], test[col]), "bias": bias(test)}
    for key in ["segment", "item_class", "tier", "abc"]:
        out["by_" + key] = {str(k): {"wape": _wape(g["target"], g[col]), "bias": bias(g), "rows": len(g)}
                            for k, g in test.groupby(key)}
    return out


def _best_by_segment(test, cols, add=None):
    base = test[cols].fillna(0)
    sel = {sg: min(cols, key=lambda b: _wape(g["target"], (0 if add is None else g[add]) + base.loc[g.index, b]))
           for sg, g in test.groupby("segment")}
    vals = np.array([base.at[i, sel[sg]] for i, sg in zip(test.index, test["segment"])], dtype=float)
    return (vals if add is None else test[add].to_numpy() + vals), sel


def _simple(test):
    out = {m: _wape(test["target"], test[m].fillna(0)) for m in ["ma4", "ma13", "ma52", "snaive", "firm_ma13"]}
    best, sel = _best_by_segment(test, ["ma4", "ma13", "ma52", "snaive"])
    out["best_reference_method"] = _wape(test["target"], best); out["best_by_segment"] = sel
    # the buyer with the order book and a spreadsheet: firm_h plus the best of the four on the
    # demand jobs do not carry, chosen by segment
    fb, fsel = _best_by_segment(test, ["u_ma4", "u_ma13", "u_ma52", "u_snaive"], add="firm_h")
    out["firm_best"] = _wape(test["target"], fb); out["firm_best_by_segment"] = fsel
    return out


def s1_diagnostics(test: pd.DataFrame) -> dict:
    """On bill items: how much of the target the order book holds, and the order book's own
    timing error against the backflush over the same window."""
    b = test[test["tier"] == "line"]
    return {"rows": len(b), "firm_over_target": float(b["firm_h"].sum() / b["target"].sum()),
            "firm_over_backflush": float(b["firm_h"].sum() / max(b["bf_window"].sum(), 1e-9)),
            "wape_firm_vs_backflush": _wape(b["bf_window"], b["firm_h"])}


def shap_summary(result: dict, test: pd.DataFrame, n: int = 1500) -> dict:
    import shap
    kind = result["winner"]; model = result["models"][kind]
    feats = result["features"]
    if kind == "Linear":
        return {"note": "linear winner: coefficients, not SHAP"}
    X = test[feats].astype(float).sample(min(n, len(test)), random_state=42)
    sv = shap.TreeExplainer(model).shap_values(X)
    imp = pd.Series(np.abs(sv).mean(axis=0), index=feats).sort_values(ascending=False)
    groups = imp.groupby([F.group_of(c) for c in imp.index]).sum().sort_values(ascending=False)
    return {"top15": {k: float(v) for k, v in imp.head(15).items()},
            "top15_group": {k: F.group_of(k) for k in imp.head(15).index},
            "by_group": {k: float(v) for k, v in groups.items()}, "rows": len(X)}


def choose_final(results: dict, chain: list) -> dict:
    """The rung with the lowest validation total-demand WAPE for its winner; a rung within 0.3
    points of a smaller feature set loses to the smaller set."""
    v = {r: results[r]["candidates"][results[r]["winner"]]["val_wape"] for r in chain}
    best = min(v.values())
    eligible = [r for r in chain if v[r] <= best + 0.003]
    chosen = min(eligible, key=lambda r: (results[r]["n_features"], chain.index(r)))
    return {"validation_wape": v, "lowest": min(v, key=v.get), "chosen": chosen}
