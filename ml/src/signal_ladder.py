"""The demand-signal ablation ladder: reference, then S1 to S6, each cumulative.

Every rung is trained and scored on the same rows and the same target: total demand over
the reference horizon (the corrected master lead time in whole weeks), with the splits,
candidates, tuning budget and seeds of the weekly model. From S1 the model learns the
demand the order book does not already cover (the uncovered target) and the forecast is
firm requirements plus that; from S3 training rows whose target window holds a short week
on a line-critical part are half-weighted and service backorders count in the week
ordered; from S4 rows from week 13 of an item's history train the model, missing where a
year of history is needed, and parts with under 13 weeks take a class-and-family prior.

Structure: load_inputs reads files and prepare_frame builds every feature once; run_rung
is a pure function of the frame and returns metrics and predictions; main writes results.
Run:  python -m ml.src.signal_ladder
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import optuna
import pandas as pd

from data_source.generate import config as C
from . import training as tr
from .training import _make, _space, _wape, predict
from .demand_model import build_frame, FEATS as REF_FEATS, _monday
from . import signal_features as SF

REPO = Path(__file__).resolve().parents[2]
MARTS = REPO / "ml" / "data" / "marts"
RAW = REPO / "data_source" / "raw"
OUT = REPO / "runs" / "ladder"
N_TRIALS = 12
KINDS = ["Linear", "RandomForest", "XGBoost"]


# ── edges: files in ─────────────────────────────────────────────────────────
def load_inputs(marts: Path = MARTS, raw: Path = RAW) -> dict:
    rd = lambda n: pd.read_parquet(marts / f"{n}.parquet")
    xw = pd.read_csv(marts / "item_crosswalk.csv").set_index("item_number")["canonical_item_number"].to_dict()
    tx = pd.read_csv(raw / "erp" / "inventory_transactions.csv", low_memory=False)
    svc = pd.read_csv(raw / "erp" / "service_orders.csv")
    bom_raw = pd.read_csv(raw / "erp" / "bill_of_materials.csv")
    restored = pd.read_csv(raw / "remediation" / "bom_change_log.csv")
    return {"weekly": rd("consumption_weekly"), "attrs": rd("item_attributes").set_index("canonical_item_number"),
            "job_req": rd("job_requirements"), "bom": rd("bom_resolved"), "item_family": rd("item_family"),
            "fam_usage": rd("family_usage_weekly"), "pf_weekly": rd("product_family_weekly"),
            "shortage": rd("shortage_weekly"), "ib_item": rd("item_installed_base"), "lt_item": rd("item_leadtime_weekly"),
            "dim_week": rd("dim_week"), "lifecycle": rd("item_lifecycle"),
            "xw": xw, "tx": tx, "svc": svc, "bom_raw": bom_raw, "restored": restored}


# ── the frame ───────────────────────────────────────────────────────────────
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
    ref[REF_FEATS] = ref[REF_FEATS].replace([np.inf, -np.inf], np.nan).fillna(0)
    ref["is_reference_row"] = True
    extra = SF.extra_history_rows(weekly, attrs, weeks, 13, 52)
    extra[[c for c in REF_FEATS if c not in SF.NULLABLE_52]] = \
        extra[[c for c in REF_FEATS if c not in SF.NULLABLE_52]].replace([np.inf, -np.inf], np.nan).fillna(0)
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
    bfw = SF.item_matrix(bf, items, weeks, "qty")
    svc = inp["svc"].copy()
    svc["canonical_item_number"] = svc["item_number"].map(lambda n: xw.get(n, n))
    gap = (pd.to_datetime(svc["ship_date"]) - pd.to_datetime(svc["order_date"])).dt.days
    backorders = svc[gap > 5]

    feats = [SF.firm_features(frame, inp["job_req"], weeks)]
    frame = pd.concat([frame] + feats, axis=1)
    frame["book_cover"] = np.where(frame["s13"] > 0, frame["firm_h"] / np.maximum(frame["s13"] / 13, 1e-9), np.nan)
    fam_sets = SF.item_family_sets(inp["job_req"])
    frame = pd.concat([frame, SF.family_book_features(frame, fam_sets, inp["pf_weekly"], inp["job_req"], weeks),
                       SF.family_usage_features(frame, inp["item_family"], inp["fam_usage"], weeks)], axis=1)
    sh, S = SF.shortage_features(frame, inp["shortage"], items, weeks)
    frame = pd.concat([frame, sh, SF.lifecycle_features(frame, inp["lifecycle"], inp["bom"], inp["ib_item"], weeks),
                       SF.leadtime_features(frame, inp["lt_item"]),
                       SF.calendar_features(frame, inp["dim_week"], wide, items, weeks)], axis=1)
    frame["short_in_target"] = SF.short_in_target_window(frame, S, items)
    # backflush over the target window, for the order book's own timing error
    ii = frame["item"].map({it: k for k, it in enumerate(items)}).to_numpy()
    frame["bf_window"] = SF.gather_window(SF.cumsum_rows(bfw), ii, frame["t"].to_numpy(), (frame["t"] + frame["h"]).to_numpy())
    frame["backorder_shift"] = SF.backorder_shift(frame, backorders, items, weeks)
    unscheduled = np.maximum(wide - bfw, 0.0)
    frame = pd.concat([frame, SF.simple_methods(frame, SF.cumsum_rows(unscheduled), items)], axis=1)
    tier = criticality(inp, items)
    frame["tier"] = frame["item"].map(tier)
    frame["item_class"] = frame["item"].map(attrs["item_class"])
    frame["family"] = frame["item"].map(inp["item_family"].set_index("canonical_item_number")["family"])

    wi = SF.week_index(weeks)
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


# ── training ────────────────────────────────────────────────────────────────
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
    return SF.RUNGS.index(base) >= SF.RUNGS.index(ref)


def _rows(frame, rung):
    """The rows a rung trains and scores on, with S4b's history rules applied."""
    s4b = RUNGS_AT_LEAST(rung, "S4b")
    f = frame[frame["is_reference_row"] | (frame["split"] == "train")] if s4b else frame[frame["is_reference_row"]]
    f = f.copy()
    if s4b:
        f.loc[f["hist_wks"] < 52, SF.NULLABLE_52] = np.nan
    cold = (f["hist_wks"] < 13) if s4b else pd.Series(False, index=f.index)
    return f, cold


def run_rung(frame: pd.DataFrame, rung: str, target_change: bool = True, n_trials: int = N_TRIALS,
             lag_order_book: str | None = None, fixed: dict | None = None) -> tuple[dict, pd.DataFrame]:
    """One rung. rung is a name from SF.RUNGS or "S1-alt" (the S1 features, the total target).
    target_change: from S1 on, learn uncovered demand and add firm_h back (the ladder's choice
    after S1 against S1-alt). Candidates are tuned and chosen on validation total demand.
    lag_order_book: None, "inputs" or "inputs_and_total" (the shuffle test); with fixed =
    {"kind": ..., "params": ...} the given model is refit without tuning."""
    feats = SF.features_for("S1" if rung == "S1-alt" else rung)
    s1 = RUNGS_AT_LEAST(rung, "S1") and target_change and rung != "S1-alt"
    s3, s4b = RUNGS_AT_LEAST(rung, "S3"), RUNGS_AT_LEAST(rung, "S4b")
    fr = frame
    if lag_order_book:
        fr = frame.copy(); g = frame.groupby("item")
        same = (g["t"].shift(4) == frame["t"] - 4).to_numpy()
        for c in SF.FORWARD_LOOKING:
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
    tr._CAP = cap
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
    groups = imp.groupby([SF.group_of(c) for c in imp.index]).sum().sort_values(ascending=False)
    return {"top15": {k: float(v) for k, v in imp.head(15).items()},
            "top15_group": {k: SF.group_of(k) for k in imp.head(15).index},
            "by_group": {k: float(v) for k, v in groups.items()}, "rows": len(X)}


def choose_final(results: dict, chain: list) -> dict:
    """The rung with the lowest validation total-demand WAPE for its winner; a rung within 0.3
    points of a smaller feature set loses to the smaller set."""
    v = {r: results[r]["candidates"][results[r]["winner"]]["val_wape"] for r in chain}
    best = min(v.values())
    eligible = [r for r in chain if v[r] <= best + 0.003]
    chosen = min(eligible, key=lambda r: (results[r]["n_features"], chain.index(r)))
    return {"validation_wape": v, "lowest": min(v, key=v.get), "chosen": chosen}


# ── edges: results out ──────────────────────────────────────────────────────
def _save(res, test, rung, out=None):
    out = out or OUT
    test[["item", "t", "week", "h", "target", "firm_h", "bf_window", "segment", "abc", "tier", "item_class"]
         + [c for c in test.columns if c.startswith("pred")]].to_parquet(out / f"pred_{rung}.parquet", index=False)
    slim = {k: v for k, v in res.items() if k != "models"}
    (out / f"metrics_{rung}.json").write_text(json.dumps(slim, indent=1, default=float))
    c = res["candidates"][res["winner"]]
    print(f"  {rung:<9} {res['winner']:<12} val {c['val_wape']*100:6.2f}%  test {c['test_wape']*100:6.2f}%"
          f"  corrected {c['test_wape_corrected']*100:6.2f}%  bias {res['scores_winner']['bias']*100:+6.1f}%", flush=True)


def run_selected(rungs: list, out: Path):
    """Only the named rungs, with the target change kept (the production path: the reference
    and S1 for the policy), written to out."""
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    out.mkdir(parents=True, exist_ok=True)
    frame, ctx = prepare_frame(load_inputs())
    frame.to_parquet(out / "frame.parquet", index=False)
    for rung in rungs:
        res, test = run_rung(frame, rung)
        _save(res, test, rung, out)


def main():
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.glob("*"):
        if p.is_file():
            p.unlink()
    print("loading inputs and building the frame ...", flush=True)
    frame, ctx = prepare_frame(load_inputs())
    frame.to_parquet(OUT / "frame.parquet", index=False)
    results, tests = {}, {}
    for rung in ["reference", "S1", "S1-alt"]:
        results[rung], tests[rung] = run_rung(frame, rung)
        _save(results[rung], tests[rung], rung)
    # S1-alt matching or beating S1 on validation drops the target change
    v = lambda r: results[r]["candidates"][results[r]["winner"]]["val_wape"]
    target_change = v("S1") < v("S1-alt")
    print(f"  target change {'kept' if target_change else 'dropped'} (S1 {v('S1')*100:.2f}% vs S1-alt {v('S1-alt')*100:.2f}% on validation)", flush=True)
    for rung in ["S2", "S3", "S4a", "S4b", "S5", "S6"]:
        results[rung], tests[rung] = run_rung(frame, rung, target_change=target_change)
        _save(results[rung], tests[rung], rung)
    s1_key = "S1" if target_change else "S1-alt"
    chain = ["reference", s1_key, "S2", "S3", "S4a", "S4b", "S5", "S6"]
    final = choose_final(results, chain)
    extra = {"target_change": target_change, "final_rule": final,
             "s1_diagnostics": s1_diagnostics(tests["S1"]), "shuffle": {}, "shap": {}}
    for rung in sorted({final["chosen"], "S6"}, key=chain.index):
        r = results[rung]
        fixed = {"kind": r["winner"], "params": r["candidates"][r["winner"]]["params"]}
        real = r["candidates"][r["winner"]]["test_wape"]
        for mode in ["inputs", "inputs_and_total"]:
            if mode == "inputs_and_total" and not r["target_change"] and rung != "reference":
                pass
            lag, _ = run_rung(frame, rung, target_change=target_change, lag_order_book=mode, fixed=fixed)
            extra["shuffle"][f"{rung}_{mode}"] = {"lagged": lag["candidates"][fixed["kind"]]["test_wape"], "real": real}
        extra["shap"][rung] = shap_summary(r, tests[rung])
    (OUT / "ladder_extra.json").write_text(json.dumps(extra, indent=1, default=float))
    print(f"  final rung by the rule: {final['chosen']} (lowest validation: {final['lowest']})", flush=True)
    return results, extra


if __name__ == "__main__":
    # python -m ml.src.signal_ladder                                   the full ladder into runs/ladder
    # python -m ml.src.signal_ladder --rungs reference S1 --out DIR    selected rungs into DIR
    if "--rungs" in sys.argv:
        a = sys.argv[sys.argv.index("--rungs") + 1:]
        rungs = [x for x in a[:a.index("--out")]] if "--out" in a else a
        out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else OUT
        run_selected(rungs, out)
    else:
        main()
