"""The reorder policy on a demand-signal model, for the forward window.

The model forecasts the demand the order book does not already cover (uncovered demand
over its horizon). The ERP nets firm requirements itself through the order book, so the
point the buyer works to carries only the rest:

    level = uncovered forecast over the lead time + buffer

There is no scheduled-share netting and no shrink of the forecast error for scheduled
demand. Each monthly retrain re-estimates, from the trailing 52 weeks of out-of-sample
uncovered-demand errors (the ladder's 2025 test predictions to start, then the forward
predictions as their targets complete):
  - the bias correction by demand pattern (criticality enters through the fill targets)
  - each item's forecast-error standard deviation (pattern and tier as the fallback)
  - the loss function of the standardized errors by ABC class, for the fill-rate buffer
The buffer formula, the fill-rate targets, lot sizing and the 20% hysteresis band are the
weekly model's. The lead time is the corrected master ("static") or the point-in-time
pooled supplier lead time at the origin ("pooled").

build_schedule is pure; main reads the frame and writes rop_schedule.json.
Run:  python -m ml.src.signal_policy <rung> <static|pooled> <out_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from data_source.generate import config as C
from . import signal_ladder as L
from . import signal_features as SF
from .demand_model import (FILL_TARGET, K_MAX, HYSTERESIS, ORDER_LINE_COST, HOLDING_RATE, LOT_DAYS,
                           SERVICE, Z_BY_ABC, _monday)

REPO = Path(__file__).resolve().parents[2]


def lead_time_sd(po: pd.DataFrame, xw: dict, item_class: dict):
    """Supplier lead-time sd per item from 2024-25 non-rush receipts, class sd below four
    receipts (the weekly model's buffer input, unchanged)."""
    p = po[(~po["rush"].astype(bool)) & po["received_date"].notna() & (po["order_date"] >= "2024-01-01")
           & (po["order_date"] < C.FORWARD_START.isoformat())].copy()
    p["canon"] = p["item_number"].map(lambda n: xw.get(n, n))
    p["lt"] = (pd.to_datetime(p["received_date"]) - pd.to_datetime(p["order_date"])).dt.days
    g = p.groupby("canon")["lt"]
    sd_item, n_item = g.std(), g.count()
    sd_cls = p.assign(cls=p["canon"].map(item_class)).groupby("cls")["lt"].std()

    def lt_sd(item):
        if n_item.get(item, 0) >= 4 and not np.isnan(sd_item.get(item, np.nan)):
            return float(sd_item[item])
        return float(sd_cls.get(item_class.get(item), p["lt"].std()))
    return lt_sd


def _error_stats(pool: pd.DataFrame):
    """Bias factors by demand pattern, per-item error sd, and standardized-error loss curves by
    ABC from out-of-sample uncovered predictions (columns ua, pu, item, segment, tier, abc).
    The factors are by pattern only, as in the weekly model: a pattern x tier cell is too
    small to hold its estimate from one year to the next."""
    g = pool.groupby("segment")
    factor = (g["ua"].sum() / g["pu"].sum().replace(0, np.nan)).fillna(1.0).clip(0.2, 5.0).to_dict()
    pool = pool.assign(pc=pool["pu"] * pool["segment"].map(factor).fillna(1.0))
    err = pool["ua"] - pool["pc"]
    sd_item = err.groupby(pool["item"]).std()
    sd_grp = err.groupby([pool["segment"], pool["tier"]]).std()
    z = (err / pool["item"].map(sd_item)).replace([np.inf, -np.inf], np.nan)
    k_grid = np.round(np.arange(0.0, 6.001, 0.01), 2)
    loss = {}
    for a in SERVICE:
        zz = z[pool["abc"] == a].dropna().to_numpy()
        loss[a] = np.array([np.maximum(zz - k, 0).mean() for k in k_grid]) if len(zz) else np.zeros(len(k_grid))
    return factor, sd_item.to_dict(), sd_grp.to_dict(), loss, k_grid


def build_schedule(frame: pd.DataFrame, rung: str, result: dict, oos: pd.DataFrame, horizon: str,
                   lt_sd, tier_of: dict, attrs: pd.DataFrame, weeks: pd.DatetimeIndex) -> dict:
    """The forward schedule: {item: [[date, level, ss, total forecast over h, 7h, point, 1.0, lot], ...]}."""
    kind = result["winner"]; params = result["candidates"][kind]["params"]
    feats = result["features"]
    s3 = L.RUNGS_AT_LEAST(rung, "S3"); s4b = L.RUNGS_AT_LEAST(rung, "S4b")
    f, cold = L._rows(frame, rung)
    total = f["target"] + (f["backorder_shift"] if s3 else 0.0)
    f["y_train"] = np.maximum(total - f["firm_h"], 0.0)
    f["w"] = np.where(f["short_in_target"] & (f["tier"] == "line"), 0.5, 1.0)
    wi = SF.week_index(weeks)
    origins = [pd.Timestamp(C.FORWARD_START)] + [w for w in weeks if pd.Timestamp(C.FORWARD_START) < w <= pd.Timestamp(C.END_DATE)]
    pool = oos.copy()
    sched, prev, model, month = {}, {}, None, None
    retrains = []          # what each monthly retrain estimated, for monitoring
    for o in origins:
        t_o = wi[pd.Timestamp(_monday(o.date()))]
        if month != (o.year, o.month):
            fit = f[(f["t"] + f["h"] <= t_o) & ~cold & f["y_train"].notna()]
            cap = float(fit["y_train"].max()) * 4
            model = L._fit(kind, params, fit[feats].astype(float), fit["y_train"], fit["w"].to_numpy() if s3 else None)
            known = pool[(pool["t"] + pool["h"] <= t_o) & (pool["t"] >= t_o - 52)]
            factor, sd_item, sd_grp, loss, k_grid = _error_stats(known)
            month = (o.year, o.month)
            retrains.append({"period": o.strftime("%Y-%m"), "trained_on": o.date().isoformat(), "training_rows": int(len(fit)),
                             "error_rows": int(len(known)),
                             "bias_factors": {s_: float(v) for s_, v in sorted(factor.items())}})
        cur = f[f["t"] == t_o]
        pu = L._predict(kind, model, cur[feats].astype(float), cap)
        if s4b:
            prior = L._cold_start_prior(f, cur)
            pu = np.where(cold.loc[cur.index], np.maximum(prior - cur["firm_h"].to_numpy(), 0.0), pu)
        # this origin's forecasts join the error pool once their targets complete
        pool = pd.concat([pool, pd.DataFrame({"item": cur["item"].to_numpy(), "t": t_o, "h": cur["h"].to_numpy(),
                                              "ua": np.maximum(cur["target"] - cur["firm_h"], 0.0).to_numpy(), "pu": pu,
                                              "segment": cur["segment"].to_numpy(), "tier": cur["tier"].to_numpy(),
                                              "abc": cur["abc"].to_numpy()})], ignore_index=True)
        for r, p_u in zip(cur.itertuples(index=False), pu):
            item = r.item; a = attrs.loc[item]
            tier = tier_of.get(item, "standard"); h = int(r.h)
            fac = factor.get(r.segment, 1.0)
            pc_u = float(p_u) * fac                                       # uncovered, over the model horizon
            Lt = float(a["corrected_lead_days"]) if horizon == "static" else float(r.lt_pooled26w)
            if not np.isfinite(Lt) or Lt <= 0:
                Lt = float(a["corrected_lead_days"])
            d_u = pc_u / (7.0 * h); fc_lead = d_u * Lt
            d_tot = (float(r.firm_h) + pc_u) / (7.0 * h)
            sd_fc = sd_item.get(item, np.nan)
            if not np.isfinite(sd_fc):
                sd_fc = sd_grp.get((r.segment, tier), np.nanmedian(list(sd_item.values())))
            sd_fc = float(sd_fc) * np.sqrt(Lt / (7.0 * h))
            sigma = float(np.sqrt(sd_fc ** 2 + (d_tot * lt_sd(item)) ** 2))
            cost = float(a["standard_cost"]) if pd.notna(a["standard_cost"]) and a["standard_cost"] > 0 else 1.0
            eoq = np.sqrt(2.0 * d_tot * 365.0 * ORDER_LINE_COST / (HOLDING_RATE * cost)) if d_tot > 0 else 1.0
            q_lot = float(max(1.0, np.clip(eoq, d_tot * LOT_DAYS[0], d_tot * LOT_DAYS[1])))
            if sigma > 0:
                allow = (1.0 - FILL_TARGET[tier]) * q_lot / sigma
                ok = np.nonzero(loss.get(a["abc"], loss["C"]) <= allow)[0]
                k = min(float(k_grid[ok[0]]) if len(ok) else float(k_grid[-1]), K_MAX)
            else:
                k = 0.0
            ss = k * sigma
            point = fc_lead + ss
            last = prev.get(item)
            fc_h = float(r.firm_h) + pc_u
            if last is not None and last[5] > 0 and abs(point - last[5]) / last[5] <= HYSTERESIS:
                entry = [o.date().isoformat(), last[1], last[2], round(fc_h, 3), 7 * h, last[5], 1.0, last[7]]
            else:
                entry = [o.date().isoformat(), round(point, 2), round(ss, 2), round(fc_h, 3), 7 * h,
                         round(point, 2), 1.0, round(q_lot, 1)]
            prev[item] = entry
            sched.setdefault(item, []).append(entry)
    return sched, retrains


def oos_pool(pred: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Out-of-sample uncovered predictions from a ladder rung's 2025 test predictions."""
    return pd.DataFrame({"item": pred["item"], "t": pred["t"], "h": pred["h"],
                         "ua": np.maximum(pred["target"] - pred["firm_h"], 0.0), "pu": pred[f"predu_{kind}"],
                         "segment": pred["segment"], "tier": pred["tier"], "abc": pred["abc"]})


def main(rung: str, horizon: str, out_dir: str, ladder_dir: str | None = None):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    lad = Path(ladder_dir) if ladder_dir else REPO / "runs" / "ladder"
    result = json.loads((lad / f"metrics_{rung}.json").read_text())
    inp = L.load_inputs()
    frame, ctx = L.prepare_frame(inp)
    attrs = inp["attrs"]
    tier_of = L.criticality(inp, ctx["items"])
    po = pd.read_csv(L.RAW / "erp" / "purchase_orders.csv", low_memory=False)
    lt_sd = lead_time_sd(po, inp["xw"], attrs["item_class"].to_dict())
    oos = oos_pool(pd.read_parquet(lad / f"pred_{rung}.parquet"), result["winner"])
    sched, retrains = build_schedule(frame, rung, result, oos, horizon, lt_sd, tier_of, attrs, ctx["weeks"])
    (out / "retrain_log.json").write_text(json.dumps(retrains, indent=1))
    origins = sorted({e[0] for es in sched.values() for e in es})
    meta = {"origins": origins, "hysteresis": HYSTERESIS, "model": f"{rung} {result['winner']}", "horizon": horizon,
            "fill_rate_target": FILL_TARGET, "criticality": tier_of, "order_line_cost": ORDER_LINE_COST,
            "holding_rate": HOLDING_RATE, "lot_days": list(LOT_DAYS), "buyer_lot_days": C.ORDER_COVER_DAYS,
            "normal_z": Z_BY_ABC,
            "entry_fields": ["date", "level", "safety_stock", "forecast_over_horizon", "horizon_days",
                             "reorder_point", "unscheduled_share", "order_qty"]}
    (out / "rop_schedule.json").write_text(json.dumps({**meta, "items": sched}, indent=1))
    print(f"  {rung} {horizon}: {len(sched):,} items, {len(origins)} origins -> {out / 'rop_schedule.json'}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
