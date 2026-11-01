"""ML Model Technical Overview for the demand forecast and reorder policy -> docs/reports/technical_report.html

Model card, training data, model selection and performance, the feature study, feature importance, how a
usage forecast becomes a reorder point and an order quantity, known limitations, deployment and operations,
and an appendix of the feature study's tables. Figures come from the champion's training run as the parity
reference archived it (S1 result, 2025 test predictions and feature frame), the feature-study ladder in
docs/data/feature_study/, and the gold snapshot (schedule, monitoring tables, registry): docs/build/sources.py.

    PYTHONIOENCODING=utf-8 .venv/Scripts/python -m docs.build.generate_technical_report
"""
import json
from math import erf, exp, pi, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

from . import brand as B
from . import sources as SR
from .brand import DARK_BLUE, LIGHT_BLUE, MED_GREY, LIGHT_GREY, GREEN, AMBER, ACCENT_RED

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data_source" / "raw"
SEQ = SR.REFERENCE / "runs" / "seq" / "ladder"
OUT = REPO / "docs" / "reports" / "technical_report.html"

# ── the champion's training run (registered version 1) ───────────────────────
C = json.loads((SEQ / "metrics_S1.json").read_text(encoding="utf-8"))
WIN = C["winner"]
cand = C["candidates"]
P_WIN = cand[WIN]["params"]
FEATS = C["features"]
tags = SR.version_tags()
champ = SR.champion_version()
assert abs(cand[WIN]["val_wape"] - float(tags[(tags["version"] == champ) & (tags["key"] == "beats_baseline_model")]["value"].iloc[0])) < 5e-7
frame = pd.read_parquet(SEQ / "frame.parquet")
REF = frame[frame["is_reference_row"]].copy()
REF["net"] = np.maximum(REF["target"] - REF["firm_h"], 0.0)
SPLITS = [("Train", "train"), ("Validation", "val"), ("Test", "test")]
assert {k: int((REF["split"] == k).sum()) for _, k in SPLITS} == {"train": C["rows"]["train"], "val": C["rows"]["val"],
                                                                  "test": C["rows"]["test"]}
pred = pd.read_parquet(SEQ / "pred_S1.parquet")                      # 2025 test rows
pred["fc"] = pred[f"predc_{WIN}"]                                    # bias-corrected total forecast

# ── the feature study (docs/data/feature_study/) ─────────────────────────────────────────
LADDER = [("reference", "Reference (usage history)"), ("S1", "Order book"), ("S2", "Product families"),
          ("S3", "Shortage history"), ("S4a", "Lifecycle"), ("S4b", "Lifecycle, longer history"),
          ("S5", "Supply"), ("S6", "Calendar")]
RUNG_NAME = {"reference": "Reference", "S1": "Order book", "S2": "Families", "S3": "Shortage", "S4a": "Lifecycle",
             "S4b": "Lifecycle on longer history", "S5": "Supply", "S6": "Calendar"}
LM = {r: json.loads((SR.LADDER / f"metrics_{r}.json").read_text(encoding="utf-8")) for r, _ in LADDER}
LX = json.loads((SR.LADDER / "ladder_extra.json").read_text(encoding="utf-8"))

# ── live use, January to June 2026: every forecast whose window closed by June 30 ──
fe = SR.monitoring_table("forecast_errors")
live = fe[fe["scored"]].copy()
live["week"] = pd.to_datetime(live["origin_week"])
_fr = REF.assign(week=pd.to_datetime(REF["week"]))[["item", "week", "firm_h", "u_ma4", "u_ma13", "u_ma52", "u_snaive"]]
live = live.merge(_fr, left_on=["canonical_item_number", "week"], right_on=["item", "week"], how="left")
_meth = C["simple"]["firm_best_by_segment"]
live["base"] = live["firm_h"] + np.array([live.at[i, _meth.get(s, "u_ma13")] for i, s in zip(live.index, live["segment"])],
                                         dtype=float)
summ = SR.monitoring_summary()
P = summ["periods"]
last_m = [p for p in P if p["matured"]][-1]
matured = [p for p in P if p["matured"]]

sched = SR.rop_schedule()
attrs = SR.item_attributes().set_index("canonical_item_number")
weekly = SR.consumption_weekly()
FT = sched["fill_rate_target"]
fr = SR.forward_results()
MOD = fr["forward"]["1H26"]["model"]

LABEL = {"Linear": "Linear regression (ridge)", "RandomForest": "Random forest", "XGBoost": "XGBoost"}
SEG_ORDER = ["smooth", "erratic", "lumpy", "intermittent"]
from data_source.generate import config as _GC  # noqa: E402
SEASONAL_SHARE = _GC.SEASONAL_ITEM_SHARE


def pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def tgt(x):
    return f"{round(x * 100, 1):g}%"


def wape(a, f):
    a, f = np.asarray(a, float), np.asarray(f, float)
    return float(np.abs(a - f).sum() / a.sum())


def widths(table_html, w):
    cols = "".join(f'<col style="width:{v}%;">' for v in w)
    return table_html.replace('<table class="data-table">',
                              f'<table class="data-table" style="table-layout:fixed;"><colgroup>{cols}</colgroup>', 1)


def k_(x):
    return f"${x / 1000:,.1f}K" if x >= 1000 else f"${x:,.0f}"


# ── figures quoted in the text ────────────────────────────────────────────────
S_W, S_C = C["scores_winner"], C["scores_winner"]["corrected"]
test_w, test_w_c, test_bias_c = S_W["wape"], S_C["wape"], S_C["bias"]
val_w = cand[WIN]["val_wape"]
simple_best, firm_best = C["simple"]["best_reference_method"], C["simple"]["firm_best"]
live_w, live_b = wape(live["actual"], live["forecast"]), wape(live["actual"], live["base"])
live_bias = (live["forecast"].sum() - live["actual"].sum()) / live["actual"].sum()
n_unscored = len(set(attrs.index) - set(SR.reorder_queue()["canonical_item_number"]))
NUM = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}

# booked requirements against total usage and against backflush, on parts that sit on a bill
_xw = SR.item_crosswalk().set_index("item_number")["canonical_item_number"].to_dict()
_on_bill = set(pd.read_csv(RAW / "erp" / "bill_of_materials.csv")["component_item"].map(lambda n: _xw.get(n, n)))
_pb, _po_ = pred[pred["item"].isin(_on_bill)], pred[~pred["item"].isin(_on_bill)]
share_bill, share_off = float(_pb["firm_h"].sum() / _pb["target"].sum()), float(_po_["firm_h"].sum() / _po_["target"].sum())
book_err = float((_pb["firm_h"] - _pb["bf_window"]).abs().sum() / _pb["bf_window"].sum())

# measured order-book visibility
_jobs = pd.read_csv(RAW / "erp" / "production_orders.csv")
_bk = (pd.to_datetime(_jobs["release_date"]) - pd.to_datetime(_jobs["booked_date"])).dt.days
_rq = (pd.to_datetime(_jobs["required_date"]) - pd.to_datetime(_jobs["release_date"])).dt.days
_vis = (pd.to_datetime(_jobs["required_date"]) - pd.to_datetime(_jobs["booked_date"])).dt.days
BK, RQ, VIS = (int(_bk.min()), int(_bk.max())), (int(_rq.min()), int(_rq.max())), (int(_vis.min()), int(_vis.max()))

# receipts per item in 2025 (purchase-order lines received), 25th to 90th percentile
_pol = pd.read_csv(RAW / "erp" / "purchase_orders.csv", low_memory=False)
_rcpt = _pol[pd.to_datetime(_pol["received_date"], errors="coerce").dt.year == 2025].groupby("item_number").size()
RCPT_LO, RCPT_HI = int(_rcpt.quantile(0.25)), int(_rcpt.quantile(0.90))

# Optuna trials per candidate, from the package
import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "src"))
from dfm.training import N_TRIALS  # noqa: E402

# standardized 2025 errors of the bias-corrected forecast, as the buffer calibration uses them
_res = pred["target"] - pred["fc"]
z_err = (_res / _res.groupby(pred["item"]).transform("std")).replace([np.inf, -np.inf], np.nan).dropna()

# the latest schedule entry per item: lot size in days of forecast usage
_last = []
for item, entries in sched["items"].items():
    e = entries[-1]
    d = e[3] / max(1.0, e[4])
    if d > 0 and e[7] and item in attrs.index:
        _last.append((attrs.loc[item, "abc"], e[7] / d))
lots = pd.DataFrame(_last, columns=["abc", "lot_days"])

_m25 = SR.consumption_monthly()
_u25 = _m25[(_m25["month"] >= "2025-01-01") & (_m25["month"] < "2026-01-01")].groupby("canonical")["consumption"].sum()
_v = attrs.join(_u25.rename("u25")).fillna({"u25": 0})
_v["v25"] = _v["u25"] * _v["standard_cost"]
ABCV = _v.groupby("abc").agg(med_val=("v25", "median"), p10=("v25", lambda x: x.quantile(0.1)),
                              med_cost=("standard_cost", "median"))

# feature correlations with the net target, on the training rows (Spearman)
_trn = REF[REF["split"] == "train"]
fcorr = _trn[FEATS].corrwith(_trn["net"], method="spearman")
cmat = _trn[FEATS].corr(method="spearman")


# the learning curve: the champion's tuned model on growing random shares of train + validation,
# scored on total demand (booked requirements plus the forecast remainder) on the held-out 2025 rows
def _learning_curve():
    import sys
    sys.path.insert(0, str(REPO / "src"))
    from dfm import training as T
    tv = REF[REF["split"].isin(["train", "val"])]
    tst = REF[REF["split"] == "test"]
    cap = float(tv["net"].max()) * 4
    rng = np.random.default_rng(11)
    rows = []
    for frac in [0.1, 0.25, 0.5, 0.75, 1.0]:
        sub = tv.iloc[rng.choice(len(tv), size=int(len(tv) * frac), replace=False)]
        m_ = T._fit(WIN, P_WIN, sub[FEATS].astype(float), sub["net"], None)
        fit_in = sub["firm_h"].to_numpy() + T._predict(WIN, m_, sub[FEATS].astype(float), cap)
        fit_out = tst["firm_h"].to_numpy() + T._predict(WIN, m_, tst[FEATS].astype(float), cap)
        rows.append({"train_rows": len(sub), "train_wape": wape(sub["target"], fit_in), "test_wape": wape(tst["target"], fit_out)})
    return pd.DataFrame(rows)


lc = _learning_curve()


# ── charts ──────────────────────────────────────────────────────────────────
def chart_volume():
    """Total weekly usage across all items, shaded by the window each week's forecasts feed."""
    import matplotlib.dates as mdates
    from matplotlib.patches import Patch
    tot = weekly.groupby("week")["consumption"].sum()
    tot = tot[tot.index < pd.Timestamp("2026-06-29")] / 1000
    wk = pd.to_datetime(REF["week"])
    bounds = {k: (wk[REF["split"] == k].min(), wk[REF["split"] == k].max()) for _, k in SPLITS}

    def col(w):
        if w < bounds["train"][0]:
            return LIGHT_GREY, "History only (feature warm-up)"
        if w <= bounds["train"][1]:
            return DARK_BLUE, "Train"
        if w <= bounds["val"][1]:
            return LIGHT_BLUE, "Validation"
        if w < pd.Timestamp("2026-01-01"):
            return AMBER, "Held-out test (2025)"
        return GREEN, "Live (1H 2026)"
    fig, ax = B.make_fig(3.1)
    ax.bar(tot.index, tot.values, width=6, color=[col(w)[0] for w in tot.index])
    ax.set_ylabel("Units used (000 / week)")
    ax.xaxis.set_major_locator(mdates.YearLocator()); ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    seen = {}
    for w in tot.index:
        c, l = col(w); seen[l] = c
    ax.legend(handles=[Patch(color=c, label=l) for l, c in seen.items()], fontsize=8, ncol=5,
              loc="upper center", bbox_to_anchor=(0.5, -0.12), frameon=False)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_target():
    fig, ax = B.make_fig(3.1)
    bins = np.linspace(0, np.log1p(REF["net"].quantile(0.995)), 40)
    for (name, k), c in zip(SPLITS, [DARK_BLUE, LIGHT_BLUE, AMBER]):
        ax.hist(np.log1p(REF.loc[REF["split"] == k, "net"]), bins=bins, density=True, histtype="step", linewidth=2,
                color=c, label=name if k != "test" else "Test (2025)")
    ticks = [0, 1, 10, 100, 1000, 10000]
    ax.set_xticks([np.log1p(t) for t in ticks if np.log1p(t) <= bins[-1]])
    ax.set_xticklabels([f"{t:,}" for t in ticks if np.log1p(t) <= bins[-1]])
    ax.set_xlabel("Units used over the lead time, net of booked requirements (log scale)"); ax.set_ylabel("Density")
    ax.legend()
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_corr():
    from matplotlib.colors import LinearSegmentedColormap
    feats = list(cmat.columns)
    cmap = LinearSegmentedColormap.from_list("brand_div", [DARK_BLUE, "#FFFFFF", ACCENT_RED])
    fig, ax = B.make_fig(5.8)
    im = ax.imshow(cmat.values, cmap=cmap, vmin=-1, vmax=1)
    ax.set_xticks(range(len(feats))); ax.set_yticks(range(len(feats)))
    ax.set_xticklabels(feats, rotation=90, fontsize=7.5); ax.set_yticklabels(feats, fontsize=7.5)
    ax.set_xticks(np.arange(-.5, len(feats), 1), minor=True); ax.set_yticks(np.arange(-.5, len(feats), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=0.6); ax.tick_params(which="minor", length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    cb = fig.colorbar(im, fraction=0.046, pad=0.04); cb.ax.tick_params(labelsize=7)
    fig.tight_layout()
    return B.b64(fig)


def chart_learning():
    fig, ax = B.make_fig(3.1)
    ax.plot(lc["train_rows"], lc["train_wape"] * 100, "o-", color=DARK_BLUE, lw=2, label="Training rows (in sample)")
    ax.plot(lc["train_rows"], lc["test_wape"] * 100, "s-", color=LIGHT_BLUE, lw=2, label="Held-out 2025")
    ax.set_xlabel("Training rows"); ax.set_ylabel("WAPE on total demand (%)"); ax.legend()
    ax.xaxis.set_major_formatter(__import__("matplotlib.ticker", fromlist=["FuncFormatter"]).FuncFormatter(lambda v, _: f"{v:,.0f}"))
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_calibration():
    """Mean actual against mean forecast within forecast deciles, held-out 2025 and live 1H26."""
    fig, ax = B.make_fig(3.5)
    top = 0
    for df, a_, f_, c, lab in [(pred, "target", "fc", MED_GREY, "Held-out 2025"),
                               (live, "actual", "forecast", DARK_BLUE, "Live 1H 2026")]:
        d = df[df[f_] > 0].copy()
        d["bin"] = pd.qcut(d[f_].rank(method="first"), 10, labels=False)
        g = d.groupby("bin")[[f_, a_]].mean()
        ax.plot(g[f_], g[a_], "o-", color=c, lw=2, label=lab)
        top = max(top, g[f_].max(), g[a_].max())
    ax.plot([0.5, top * 1.1], [0.5, top * 1.1], color=ACCENT_RED, ls="--", lw=1.2, label="Perfectly calibrated")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Mean forecast in decile (units, log scale)"); ax.set_ylabel("Mean actual usage (units, log scale)")
    ax.legend(loc="upper left")
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_by_pattern():
    fig, ax = B.make_fig(3.1)
    x = np.arange(len(SEG_ORDER)); w = 0.36
    m_ = [wape(live.loc[live.segment == s, "actual"], live.loc[live.segment == s, "forecast"]) * 100 for s in SEG_ORDER]
    b_ = [wape(live.loc[live.segment == s, "actual"], live.loc[live.segment == s, "base"]) * 100 for s in SEG_ORDER]
    for off, vals, c, lab in [(-w / 2, b_, MED_GREY, "Order book + best simple method"), (w / 2, m_, DARK_BLUE, "Model")]:
        bars = ax.bar(x + off, vals, w, color=c, label=lab)
        for bb, v in zip(bars, vals):
            ax.text(bb.get_x() + bb.get_width() / 2, v + 1, f"{v:.0f}%", ha="center", fontsize=8.5)
    ax.set_xticks(x); ax.set_xticklabels([s.capitalize() for s in SEG_ORDER])
    ax.set_ylabel("WAPE, live 1H 2026 (%)"); ax.set_ylim(0, max(b_ + m_) * 1.2); ax.legend(ncol=2)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_pred_actual():
    import matplotlib.pyplot as plt
    d = live[(live["actual"] > 0) & (live["forecast"] > 0)]
    d = d.sample(n=min(6000, len(d)), random_state=3)
    fig, ax = plt.subplots(figsize=(5.2, 4.0))
    ax.scatter(d["actual"], d["forecast"], s=6, alpha=0.18, color=DARK_BLUE, edgecolors="none")
    lo, hi = 0.8, max(d["actual"].max(), d["forecast"].max()) * 1.2
    ax.plot([lo, hi], [lo, hi], color=ACCENT_RED, ls="--", lw=1.2)
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
    ax.set_xlabel("Actual usage over the lead time (units)"); ax.set_ylabel("Forecast (units)")
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_ladder():
    """Held-out 2025 WAPE on total demand by rung of the feature study, raw and bias-corrected."""
    fig, ax = B.make_fig(3.4)
    x = np.arange(len(LADDER)); w = 0.38
    raw = [LM[r]["scores_winner"]["wape"] * 100 for r, _ in LADDER]
    cor = [LM[r]["scores_winner"]["corrected"]["wape"] * 100 for r, _ in LADDER]
    for off, vals, c, lab in [(-w / 2, raw, DARK_BLUE, "Raw forecast"), (w / 2, cor, LIGHT_BLUE, "Bias-corrected")]:
        bars = ax.bar(x + off, vals, w, color=c, label=lab)
        for bb, v in zip(bars, vals):
            ax.text(bb.get_x() + bb.get_width() / 2, v + 0.3, f"{v:.1f}", ha="center", fontsize=7.5)
    wrap = {"Reference (usage history)": "Reference\n(usage history)", "Product families": "Product\nfamilies",
            "Shortage history": "Shortage\nhistory", "Lifecycle, longer history": "Lifecycle,\nlonger history"}
    ax.set_xticks(x); ax.set_xticklabels([wrap.get(n, n) for _, n in LADDER], fontsize=7.5)
    ax.set_ylabel("Held-out 2025 WAPE (%)"); ax.set_ylim(min(raw + cor) - 4, max(raw + cor) + 2.5)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, frameon=False, fontsize=9)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


SHAP = pd.Series(LX["shap"]["S1"]["top15"]).sort_values(ascending=False)


def chart_shap():
    d = SHAP.head(14).iloc[::-1]
    names = [FEAT_DESC.get(f, (f, ""))[0] for f in d.index]
    fig, ax = B.make_fig(4.2)
    ax.barh(names, d.values, color=DARK_BLUE, height=0.66)
    for i, v in enumerate(d.values):
        ax.text(v + d.max() * 0.01, i, f"{v:.2f}", va="center", fontsize=8.5, color=MED_GREY)
    ax.set_xlabel("Mean |SHAP| (effect on log usage)")
    ax.tick_params(axis="y", labelsize=8.5)
    B.chart_style(ax); ax.xaxis.grid(True, color=LIGHT_GREY); ax.yaxis.grid(False)
    fig.tight_layout()
    return B.b64(fig)


def _normal_loss(k):
    phi = exp(-k * k / 2) / sqrt(2 * pi)
    return phi - k * (1 - 0.5 * (1 + erf(k / sqrt(2))))


def chart_loss():
    ks = np.linspace(0, 3.5, 71)
    zs = z_err.to_numpy()
    emp = [np.maximum(zs - k, 0).mean() for k in ks]
    fig, ax = B.make_fig(3.2)
    ax.plot(ks, [_normal_loss(k) for k in ks], color=MED_GREY, lw=2, ls="--", label="Normal distribution (textbook)")
    ax.plot(ks, emp, color=DARK_BLUE, lw=2.2, label="The model's actual 2025 errors")
    ax.set_yscale("log")
    ax.set_xlabel("Safety buffer, in standard errors of the forecast (k)")
    ax.set_ylabel("Expected shortfall per cycle\n(standard errors, log scale)")
    ax.legend()
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_lots():
    fig, ax = B.make_fig(3.0)
    bins = np.linspace(sched["lot_days"][0], sched["lot_days"][1], 22)
    for ab, c in [("A", DARK_BLUE), ("B", LIGHT_BLUE), ("C", MED_GREY)]:
        ax.hist(lots.loc[lots.abc == ab, "lot_days"], bins=bins, histtype="step", lw=2, color=c,
                label=f"{ab} items (median {lots.loc[lots.abc == ab, 'lot_days'].median():.0f} days)")
    ax.axvline(sched["buyer_lot_days"], color=ACCENT_RED, ls="--", lw=1.3)
    ax.text(sched["buyer_lot_days"] - 2, ax.get_ylim()[1] * 0.9, "buyers' manual lot", ha="right", fontsize=8, color=ACCENT_RED)
    ax.set_xlabel("Order quantity, in days of forecast usage"); ax.set_ylabel("Items"); ax.legend(fontsize=8.5)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


# ── tables ──────────────────────────────────────────────────────────────────
FEAT_DESC = {
    "s4": ("Usage, last 4 weeks", "Rolling usage"), "s13": ("Usage, last 13 weeks", "Rolling usage"),
    "s26": ("Usage, last 26 weeks", "Rolling usage"), "s52": ("Usage, last 52 weeks", "Rolling usage"),
    "nz13": ("Weeks with usage, last 13", "Rolling usage"), "nz52": ("Weeks with usage, last 52", "Rolling usage"),
    "since_nz": ("Weeks since last usage", "Rolling usage"), "cv13": ("Week-to-week variability, last 13 weeks", "Rolling usage"),
    "trend": ("Recent trend (4-week rate less 13-week rate)", "Rolling usage"),
    "ly": ("Usage in the same weeks last year", "Rolling usage"), "mean_all": ("Average weekly usage since history began", "Rolling usage"),
    "woy": ("Week of year", "Calendar"), "month": ("Month", "Calendar"),
    "std_cost": ("Standard unit cost", "Item attribute"), "lead": ("Supplier lead time (days)", "Item attribute"),
    "annual": ("Annual usage", "Item attribute"), "seg_code": ("Demand pattern", "Item attribute"),
    "abc_code": ("Value class (ABC)", "Item attribute"), "cls_code": ("Item category", "Item attribute"),
    "h": ("Forecast horizon (lead time, weeks)", "Item attribute"),
    "firm_h": ("Component requirements of booked jobs due inside the lead-time window", "Order book"),
    "firm_rel_h": ("Of those, the requirements of jobs already released", "Order book"),
    "firm_next4": ("Requirements of booked jobs due in the four weeks after the window", "Order book"),
    "open_jobs": ("Open booked jobs drawing the item", "Order book"),
    "book_cover": ("Booked requirements as a share of average usage over the window", "Order book"),
    "fam_backlog": ("Product-family backlog of booked jobs", "Order book"),
}
assert list(FEAT_DESC) == FEATS or set(FEAT_DESC) == set(FEATS), set(FEATS) ^ set(FEAT_DESC)
TCOL = {"Rolling usage": DARK_BLUE, "Calendar": AMBER, "Item attribute": LIGHT_BLUE, "Order book": GREEN}


def feature_table():
    rows = ""
    for f in FEATS:
        desc, typ = FEAT_DESC[f]
        c = fcorr.get(f, np.nan)
        rows += (f'<tr><td style="font-family:monospace;font-size:13px;">{f}</td><td>{desc}</td>'
                 f'<td>{B.badge(typ, TCOL[typ])}</td>'
                 f'<td style="text-align:right;">{"-" if pd.isna(c) else f"{c:+.2f}"}</td></tr>')
    return (f'<table class="data-table"><thead><tr><th>Feature</th><th>Description</th><th>Type</th>'
            f'<th style="text-align:right;">Corr. with target</th></tr></thead><tbody>{rows}</tbody></table>')


def split_table():
    rows = []
    for name, k in SPLITS:
        g = REF[REF["split"] == k]
        wk = pd.to_datetime(g["week"])
        rows.append([name, f"{wk.min():%Y-%m-%d} to {wk.max():%Y-%m-%d}", f"{len(g):,}", f"{g['item'].nunique():,}",
                     f"{g['target'].median():,.0f}", pct((g['target'] == 0).mean(), 0)])
    lw = live["week"]
    rows.append(["Live", f"{lw.min():%Y-%m-%d} to {lw.max():%Y-%m-%d}", f"{len(live):,}", f"{live['canonical_item_number'].nunique():,}",
                 f"{live['actual'].median():,.0f}", pct((live['actual'] == 0).mean(), 0)])
    return widths(B.data_table(["Split", "Forecast dates", "Forecasts", "Items", "Median target (units)", "Zero-usage share"],
                               rows, right=[2, 3, 4, 5]), [16, 28, 13, 10, 18, 15])


def known_table():
    rows = [["Parts on a bill of materials", f"{_pb['item'].nunique():,}", pct(share_bill, 0)],
            ["Parts on no bill", f"{_po_['item'].nunique():,}", pct(share_off, 0)]]
    return widths(B.data_table(["Parts", "Items", "Share of lead-time usage covered by booked jobs"], rows, right=[1, 2]),
                  [44, 16, 40])


def candidate_table():
    order = [WIN] + [c for c in ["RandomForest", "XGBoost", "Linear"] if c != WIN]
    rows = ""
    for c in order:
        r = cand[c]
        sel = c == WIN
        tick = f' <span style="color:{GREEN};font-weight:700;">&#10004; Selected</span>' if sel else ""
        bg = ' style="font-weight:700;"' if sel else ""
        params = ", ".join(f"{k} {v:.3g}" if isinstance(v, float) else f"{k} {v}" for k, v in r["params"].items())
        rows += (f'<tr{bg}><td>{LABEL[c]}{tick}</td><td style="text-align:right;">{pct(r["val_wape"])}</td>'
                 f'<td style="text-align:right;">{pct(r["test_wape"])}</td><td style="font-size:12.5px;">{params}</td></tr>')
    return widths(f'<table class="data-table"><thead><tr><th>Model</th><th style="text-align:right;">Validation WAPE</th>'
                  f'<th style="text-align:right;">Held-out 2025 WAPE</th><th>Tuned hyperparameters</th></tr></thead>'
                  f'<tbody>{rows}</tbody></table>', [26, 16, 18, 40])


def metrics_table():
    lm = last_m
    lmn = pd.Timestamp(lm["period"] + "-01").strftime("%b %Y")
    rows = [["Order book + best simple method by pattern, WAPE", "n/a", f"<strong>{pct(firm_best)}</strong>", pct(lm["base_wape"])],
            ["Model, raw forecast, WAPE", pct(val_w), pct(test_w), "n/a"],
            ["Model, bias-corrected forecast (used for reorder points), WAPE", "n/a", pct(test_w_c), f"<strong>{pct(lm['wape'])}</strong>"],
            ["Best simple method by pattern (usage history only), WAPE", "n/a", pct(simple_best), "n/a"],
            ["Forecast bias, after correction", "n/a", f"{test_bias_c * 100:+.1f}%", f"{lm['bias'] * 100:+.1f}%"],
            ["Forecasts scored", f"{C['rows']['val']:,}", f"{C['rows']['test']:,}", f"{lm['n_scored']:,}"]]
    return widths(B.data_table(["Metric", "Validation", "Held-out 2025", f"Live, {lmn}"], rows, right=[1, 2, 3]),
                  [46, 18, 18, 18])


def pattern_table():
    tst = REF[REF["split"] == "test"]
    rows = []
    for s in SEG_ORDER:
        g, t_ = live[live.segment == s], tst[tst.segment == s]
        b25 = wape(t_["target"], t_["firm_h"] + t_[_meth.get(s, "u_ma13")])
        lb = (g["forecast"].sum() - g["actual"].sum()) / g["actual"].sum()
        rows.append([s.capitalize(), pct(S_C["by_segment"][s]["wape"], 0), pct(b25, 0),
                     pct(wape(g["actual"], g["forecast"]), 0), pct(wape(g["actual"], g["base"]), 0), f"{lb * 100:+.0f}%"])
    return widths(B.data_table(["Demand pattern", "Model, 2025", "Order book + simple, 2025", "Model, 1H26",
                                "Order book + simple, 1H26", "Bias, 1H26"], rows, right=[1, 2, 3, 4, 5]),
                  [18, 15, 19, 15, 19, 14])


def bias_table():
    bf = SR.monitoring_table("bias_factors")
    first = bf[bf["period"] == bf["period"].min()].set_index("factor_cell")["factor"]
    pm = SR.monitoring_table("pattern_metrics")
    pm = pm[pm["matured"]]
    months = sorted(pm["period"].unique())
    rows = []
    for s in SEG_ORDER:
        b = pm[pm["segment"] == s].set_index("period")["bias"]
        rows.append([s.capitalize(), f"&times;{first[s]:.2f}"] + [f"{b[m] * 100:+.0f}%" if m in b.index else "" for m in months])
    head = ["Demand pattern", f"Factor, {pd.Timestamp(bf['period'].min() + '-01'):%b %Y} retrain"] + \
           [f"Corrected bias, {pd.Timestamp(m + '-01'):%b}" for m in months]
    return B.data_table(head, rows, right=list(range(1, len(head))))


def policy_table():
    rows = [
        ["Reorder point", "The component requirements of booked jobs plus the forecast of remaining usage over the lead "
                          "time, plus safety buffer; the ERP nets the booked requirements against released jobs"],
        ["Fill-rate targets", f"Production items {tgt(FT['line'])}, spare parts {tgt(FT['service'])}, shop supplies {tgt(FT['standard'])}"],
        ["Safety buffer", "k &times; &sigma;, with k the smallest multiple whose expected shortfall per cycle, on the "
                          "model's own error distribution, fits (1 - fill target) &times; order quantity"],
        ["&sigma; (uncertainty, in units)", "The typical size of the gap between the usage forecast and actual usage "
                                            "over the item's lead time (one standard deviation): &radic;(forecast error&sup2; + "
                                            "(daily usage &times; lead-time standard deviation)&sup2;). The forecast error is the "
                                            "standard deviation of the item's own forecast misses, scaled to its lead time; "
                                            "the second term is the variability of the supplier's delivery time"],
        ["Order-book visibility", f"Customer orders are booked {BK[0]} to {BK[1]} days before their jobs are released, and "
                                  f"jobs require their components {RQ[0]} to {RQ[1]} days after release, so the order "
                                  f"book shows a component requirement {VIS[0]} to {VIS[1]} days ahead (about "
                                  f"{VIS[0] / 7:.0f} to {VIS[1] / 7:.0f} weeks)"],
        ["Order quantity", f"Economic lot: &radic;(2 &times; annual usage &times; ${sched['order_line_cost']:.0f} per order line "
                           f"&divide; ({sched['holding_rate'] * 100:.0f}% holding &times; unit cost)), kept between "
                           f"{sched['lot_days'][0]} and {sched['lot_days'][1]} days of usage.<br>"
                           f"<em>Annual usage:</em> the model's usage forecast, at a yearly rate. "
                           f"<em>Unit cost:</em> standard cost from the item master. "
                           f"<em>${sched['order_line_cost']:.0f} per order line (assumption):</em> the fully loaded cost of "
                           f"placing and processing one line (buyer time, receiving and inspection, putaway, invoice "
                           f"matching); published estimates for manufacturers run roughly $20 to $100+ per purchase order, "
                           f"less per line. <em>{sched['holding_rate'] * 100:.0f}% holding (assumption):</em> the usual "
                           f"20 to 30% rule of thumb covering cost of capital, storage, handling, insurance and "
                           f"obsolescence. <em>{sched['lot_days'][0]} to {sched['lot_days'][1]} days (judgment):</em> no "
                           f"item ordered more often than about every two weeks, and no more than four months of a cheap "
                           f"item at once, below the buyers' manual {sched['buyer_lot_days']}-day lot. Supplier minimum "
                           f"order quantities, price breaks and freight are not modeled."],
        ["Change threshold", f"A reorder point moves only when the new value differs by more than {sched['hysteresis'] * 100:.0f}%"],
        ["Lead times", "The corrected supplier lead time from the item master, refreshed from receipts; a supplier-level "
                       "lead-time review in monitoring flags masters that have drifted"],
        ["Inbound orders", "Pushed back when not yet needed; never on production items"],
    ]
    return widths(B.data_table(["Element", "Rule"], rows), [24, 76])


TASK_MIN = {"pipeline_update": (203, 263), "train": (1904, 2105), "score": (853, 881), "monitor": (133, 143)}


def ops_table():
    t = {k: (round(a / 60), round(b / 60)) for k, (a, b) in TASK_MIN.items()}
    span = {k: (f"about {a}" if a == b else f"{a} to {b}") for k, (a, b) in t.items()}
    rows = [
        ["Scoring cadence", f"Weekly (Monday): a usage forecast, reorder point and order quantity for all "
                            f"{len(sched['items']):,} scored items; the ERP checks every item against its point daily"],
        ["Retraining", "Monthly, on a Lakeflow job (pipeline_update &rarr; train &rarr; promote &rarr; score &rarr; monitor). "
                       "Promotion gates: selection, parity, completeness, beats-baseline and bias. A new version moves the "
                       "<code>champion</code> alias in the Unity Catalog model registry only when every gate passes"],
        ["Run time", f"One single-node job cluster: pipeline update {span['pipeline_update']} minutes, train "
                     f"{span['train']}, score {span['score']}, monitor {span['monitor']}"],
        ["Outputs", "<code>gold.reorder_schedule</code> (per item and week: the reorder level, safety stock, forecast, "
                    "horizon, reorder point and order quantity) and <code>gold.reorder_queue</code> (the as-of view the "
                    "ERP's reorder queue reads)"],
        ["Data lineage", "Landed extracts &rarr; Lakeflow pipeline (bronze; silver, with the data-quality flags; gold) "
                         "&rarr; the <code>dfm</code> package &rarr; gold tables &rarr; ERP reorder queue. MLflow logs the "
                         "input tables of every model version"],
        ["Retraining triggers", "Judged on matured months (at least 80% of forecasts scored). Investigate when live "
                                "WAPE is above its 2025 level, overall or for any demand pattern. Full re-tune when "
                                "overall WAPE is more than 3 points above the 2025 reference, WAPE for a demand "
                                "pattern is more than 5 points above its 2025 level, or corrected bias, overall or "
                                "for a pattern, is outside &plusmn;10%. Safety buffers are recalibrated when achieved "
                                "fill rate is more than 1 point below target for a criticality group; stockout episodes or "
                                "jobs held for material above the 2025 monthly average call for investigation. The "
                                "promotion's bias gate applies the monitor's bias rule to the schedule in force. See the "
                                "<a href=\"monitoring_report.html\">monitoring report</a>"],
    ]
    return widths(B.data_table(["Specification", "Detail"], rows), [22, 78])


# ── appendix tables (the feature study) ──────────────────────────────────────
def _rung_table(key, labels, title_col):
    rows = []
    for lab in labels:
        cells = [lab]
        for r, _ in LADDER:
            sw = LM[r]["scores_winner"]
            raw = sw[key].get(lab, {}).get("wape")
            cor = sw["corrected"].get(key, {}).get(lab, {}).get("wape") if key in sw["corrected"] else None
            cells.append(f"{pct(raw, 1)} / {pct(cor, 1)}" if raw is not None and cor is not None
                         else (pct(raw, 1) if raw is not None else ""))
        rows.append(cells)
    return B.data_table([title_col] + [RUNG_NAME[r] for r, _ in LADDER], rows, right=list(range(1, len(LADDER) + 1)))


def appendix_tables():
    seg = _rung_table("by_segment", SEG_ORDER, "Demand pattern")
    tier = _rung_table("by_tier", ["line", "service", "standard"], "Criticality")
    cls = _rung_table("by_item_class", sorted(LM["S1"]["scores_winner"]["by_item_class"]), "Item category")
    abc = _rung_table("by_abc", ["A", "B", "C"], "Value class")
    bias_rows = [[RUNG_NAME[r]] + [f"{LM[r]['candidates'][LM[r]['winner']]['bias_factors'][s]:.3f}" for s in SEG_ORDER] for r, _ in LADDER]
    bias = B.data_table(["Rung"] + [s.capitalize() for s in SEG_ORDER], bias_rows, right=[1, 2, 3, 4])
    sm = LM["S1"]["simple"]
    simple_rows = [["4-week rate", pct(sm["ma4"])], ["13-week rate", pct(sm["ma13"])], ["52-week rate", pct(sm["ma52"])],
                   ["Same weeks last year", pct(sm["snaive"])], ["Best of the four by pattern", pct(sm["best_reference_method"])],
                   ["Order book + 13-week rate of the remaining usage", pct(sm["firm_ma13"])],
                   ["Order book + best of the four on the remaining usage, by pattern", pct(sm["firm_best"])]]
    simple = widths(B.data_table(["Simple method (feature-study rows)", "Held-out 2025 WAPE"], simple_rows, right=[1]), [70, 30])
    sh = LX["shuffle"]
    names = {"S1_inputs": "Order book (selected set): inputs", "S1_inputs_and_total": "Order book (selected set): inputs and booked total",
             "S6_inputs": "All groups: order-book inputs", "S6_inputs_and_total": "All groups: order-book inputs and booked total"}
    leak_rows = [[names.get(k, k), pct(v["real"]), pct(v["lagged"]), f"{(v['lagged'] - v['real']) * 100:+.1f} pts"]
                 for k, v in sh.items()]
    leak = widths(B.data_table(["Lagged four weeks", "Held-out WAPE, as observed", "Held-out WAPE, lagged", "Change"],
                               leak_rows, right=[1, 2, 3]), [40, 21, 21, 18])
    return seg, tier, cls, abc, bias, simple, leak


charts = {"volume": chart_volume(), "target": chart_target(), "corr": chart_corr(), "learning": chart_learning(),
          "calib": chart_calibration(), "pattern": chart_by_pattern(), "pva": chart_pred_actual(),
          "ladder": chart_ladder(), "shap": chart_shap(), "loss": chart_loss(), "lots": chart_lots()}
A_SEG, A_TIER, A_CLS, A_ABC, A_BIAS, A_SIMPLE, A_LEAK = appendix_tables()

PROSE = {"ly": "usage in the same weeks last year", "lead": "supplier lead time",
         "book_cover": "the order book's cover of average usage", "annual": "annual usage", "s13": "the last 13 weeks of usage"}
top3 = [PROSE.get(f, FEAT_DESC.get(f, (f, ""))[0].lower()) for f in SHAP.index[:3]]
ob_rest = [f for f in ["firm_h", "firm_rel_h", "firm_next4", "open_jobs", "fam_backlog"] if f in SHAP.index]
k_emp = {kk: (np.maximum(z_err.to_numpy() - kk, 0).mean(), _normal_loss(kk)) for kk in [1.0, 2.0, 3.0]}
n_lumpy_int = int(attrs["segment"].isin(["lumpy", "intermittent"]).sum())
rung_rule = LX["final_rule"]
first_live = pd.Timestamp(min(p["period"] for p in P) + "-01")
hi_int = [p for p in matured if p["pattern_bias"].get("intermittent", 0) > summ["thresholds"]["bias_tol"]]
INT_MONTHS = " and ".join(pd.Timestamp(p["period"] + "-01").strftime("%B") for p in hi_int)
live_lo, live_hi = min(p["wape"] for p in matured), max(p["wape"] for p in matured)


def _deciles(df, a_, f_):
    d = df[df[f_] > 0].copy()
    d["bin"] = pd.qcut(d[f_].rank(method="first"), 10, labels=False)
    return d.groupby("bin")[[f_, a_]].mean()


_cl = _deciles(live, "actual", "forecast")
_c25 = _deciles(pred, "target", "fc")
_close = (_cl["actual"] / _cl["forecast"] - 1).abs() <= 0.10
CAL_FROM = float(_cl.loc[_close[_close].index.min(), "forecast"])          # first decile within 10%
CAL_LO_F, CAL_LO_A = float(_cl["forecast"].iloc[0]), float(_cl["actual"].iloc[0])
CAL_TOP = float(1 - _cl["actual"].iloc[-1] / _cl["forecast"].iloc[-1])
LEAK = {k: (v["lagged"] - v["real"]) * 100 for k, v in LX["shuffle"].items()}
LMN = pd.Timestamp(last_m["period"] + "-01").strftime("%B %Y")

toc = ('<a href="#card">Model Card</a><hr>'
       '<a href="#data">Training Data</a>'
       '<a href="#known" class="sub">Known Demand and the Forecast Target</a><hr>'
       '<a href="#modelperf">Model Selection &amp; Performance</a>'
       '<a href="#selection" class="sub">Model Selection</a>'
       '<a href="#performance" class="sub">Model Performance</a>'
       '<a href="#study" class="sub">Feature Study</a><hr>'
       '<a href="#shap">Feature Importance</a><hr>'
       '<a href="#policy">From Forecast to Reorder Decision</a><hr>'
       '<a href="#limits">Known Limitations</a><hr>'
       '<a href="#ops">Deployment &amp; Operations</a><hr>'
       '<a href="#appendix">Appendix</a>')

body = f"""
{B.section("card", "Section 1", "Model Card")}
<div class="model-card"><div class="model-card-grid">
  <div><div class="mc-label">Model Name</div><div class="mc-value">demand_forecaster (weekly)</div></div>
  <div><div class="mc-label">Model Type</div><div class="mc-value">{LABEL[WIN]} regressor (scikit-learn)</div></div>
  <div><div class="mc-label">Target</div><div class="mc-value">Units an item will use over its supplier lead time, net of the component requirements of jobs booked by the forecast date; the forecast is those requirements plus that remainder</div></div>
  <div><div class="mc-label">Prediction Type</div><div class="mc-value">Regression on log(1 + usage), one forecast per item per week</div></div>
  <div><div class="mc-label">Features</div><div class="mc-value">{len(FEATS)} (rolling usage, calendar, item attributes, order book)</div></div>
  <div><div class="mc-label">Tuning</div><div class="mc-value">Optuna, {N_TRIALS} trials per candidate, validation WAPE on total lead-time demand</div></div>
  <div><div class="mc-label">Cadence</div><div class="mc-value">Refreshed every Monday; retrained monthly</div></div>
  <div><div class="mc-label">Outputs</div><div class="mc-value">Reorder point and order quantity per item, loaded into the ERP</div></div>
  <div><div class="mc-label">Held-out 2025 WAPE, total demand</div><div class="mc-value">{pct(test_w)}</div></div>
  <div><div class="mc-label">Live 1H 2026 WAPE ({LMN})</div><div class="mc-value">{pct(last_m['wape'])}</div></div>
  <div style="grid-column:1/-1;"><div class="mc-label">Purpose</div><div class="mc-value">Forecasts each stocked item's usage over its supplier lead time and turns it into a reorder point and order quantity for the ERP's reorder queue. Intended as decision support for reordering: buyers review the queue and release or override each line.</div></div>
</div></div>

{B.section("data", "Section 2", "Training Data")}
<p>The demand forecasting model learns from the shop's weekly usage of its stocked items. It scores
{len(sched['items']):,} of the {attrs.shape[0]:,} stocked items; the other {NUM.get(n_unscored, n_unscored)} are
successor parts with no usage history yet. Each training row is one item on one forecast date. Its features describe the item's usage and
order book up to that date, and its target is the usage over the following lead time, rounded to whole weeks.</p>
<p>The historical data is split by date and never shuffled. Training rows start at week 52 of the history, because
every forecast needs a full year of usage behind it. A 26-week validation block before 2025 was used to tune and
compare the candidates, and 2025 was held out to score the winner. Each split keeps its whole forecast horizon
before the next window starts, so no training target overlaps a validation week and no validation target overlaps
2025.</p>
<p>The first six months of 2026 are the model's live output; the model is retrained monthly on every forecast date
whose outcome is known.</p>
{split_table()}
{B.chart("Weekly Usage by Split", charts["volume"])}
<p>The model's {len(FEATS)} features fall into four groups. The first is Rolling Usage, including usage windows (4,
13, 26 and 52 weeks), the count of weeks with any usage, the time since the last usage and the recent variability.
The second is Calendar Features, to let the model learn seasonal demand patterns. The third is Item Attributes,
including cost, lead time, demand pattern, value class and category, to tell the model how to read each item's
usage history. The fourth is the Order Book: the component requirements of jobs booked on or before the forecast
date, namely the requirements due inside the lead-time window and in the four weeks after it, the subset already
released, the open job count, the book's cover of average usage, and the product-family backlog. The correlation
figures presented are Spearman rank correlations with the target on the training rows, which suit the skewed,
zero-heavy usage.</p>
{feature_table()}
<p>The rolling usage windows are strongly correlated with one another, since they overlap in time. The
weeks-since-last-usage and variability features move against the usage windows, as expected for intermittent items.
Unit cost runs against usage ({cmat.loc['std_cost', 's13']:+.2f} to {cmat.loc['std_cost', 'mean_all']:+.2f}), because
expensive items are used in smaller quantities. Last year's usage correlates only {cmat.loc['s52', 'ly']:+.2f} with the
52-week total, so its timing adds information beyond the average level. The order-book features correlate weakly
with the target because the target is usage net of booked requirements; their value is in the booked quantity itself,
which enters the forecast directly, and in <code>book_cover</code>, which the model uses to read how much of an item's
usage the book already explains.</p>
{B.chart("Feature Correlation Heatmap (numeric features, Spearman)", charts["corr"])}
<p>The target is heavily right-skewed: most lead-time windows use a few dozen units, while fasteners and
consumables run to thousands. The model is therefore trained on log(1 + usage), so the few very high-volume items do
not dominate the fit and the model learns proportional patterns across items of very different sizes. This
distribution is stable across the three splits, as shown below.</p>
{B.chart("Target Distribution (usage net of booked requirements): Train / Validation / Held-out Test", charts["target"])}

{B.section("known", "Section 2.1", "Known Demand and the Forecast Target")}
<p>Part of an item's usage over its lead time is known on the forecast date: the component requirements of jobs
already booked. On the parts that sit on a bill of materials, those requirements cover {pct(share_bill, 0)} of usage
over the lead time; parts on no bill have none. The order book's own timing error against what the floor actually
backflushed in the window is {pct(book_err, 1)} (WAPE). The model forecasts only the remainder, because the ERP nets
the booked requirements itself: forecasting them too would count them twice.</p>
{known_table()}

{B.section("modelperf", "Section 3", "Model Selection & Performance")}

{B.section("selection", "Section 3.1", "Model Selection")}
<p>Three candidates, a ridge regression, a random forest and an XGBoost gradient-boosted model, were each tuned
with Optuna ({N_TRIALS} trials per model) on the validation weeks, using weighted absolute percentage error (WAPE) on total
lead-time demand (the booked requirements plus the forecast remainder) as the objective. The selection rule picks the
lowest validation WAPE on total demand; the booster is preferred only when it finishes within half a point of the
best, and within 0.3 points the smaller feature set wins. The models were then refit on train plus validation and
scored once on the held-out 2025 year. The {LABEL[WIN].lower()} had the lowest validation error and was selected.</p>
{candidate_table()}
<p>The best {LABEL[WIN].lower()} model has {P_WIN.get('n_estimators')} trees with a maximum depth of
{P_WIN.get('max_depth')} and at least {P_WIN.get('min_samples_leaf')} rows per leaf. The relatively large leaf-size
floor keeps the model from fitting individual spikes and instead learning the items' typical usage patterns.</p>

{B.section("performance", "Section 3.2", "Model Performance")}
<p>Accuracy is measured as WAPE: the total absolute gap between forecast and actual usage across all forecasts,
divided by total actual usage. The fair comparison is the order book plus the best simple method by demand pattern,
which knows the same booked requirements: on the held-out 2025 year it scores {pct(firm_best)}, against
{pct(test_w)} for the model's raw forecast. The reorder points use the bias-corrected forecast (Section 5), which
trades some accuracy ({pct(test_w)} to {pct(test_w_c)} on the held-out year) for forecasts that do not run
systematically low. Live figures are the monitor's latest matured month.</p>
{metrics_table()}
<p>A live WAPE of {pct(last_m['wape'], 0)} means that for every 100 units an item used over its lead time, the
forecast was off by about {last_m['wape'] * 100:.0f} units in either direction. Across the matured months from
{pd.Timestamp(matured[0]['period'] + '-01'):%B} to {pd.Timestamp(matured[-1]['period'] + '-01'):%B} it ran
{pct(live_lo, 1)} to {pct(live_hi, 1)}. That is typical for item-level forecasts of lumpy, job-driven demand, where a
single job or spare-parts order can double an item's usage in a week. The errors largely cancel across items: over all
live forecasts scored by June 30, total forecast usage was within {abs(live_bias) * 100:.1f}% of actual. Most of the
operational improvement comes from how the forecast is used, covered in Section 5.</p>
<p>The learning curve refits the selected model on growing random shares of the training and validation rows. The
held-out error flattens well before the full training set, so more of the same history adds little.</p>
{B.chart("Learning Curve", charts["learning"])}
<p>Calibration compares the mean forecast with the mean actual usage within each tenth of the forecasts, from
smallest to largest. Points on the diagonal mean a forecast of, say, 50 units really does average about 50 units of
usage. After the bias correction described in Section 5, the live forecasts track actual usage within 10% from
about {CAL_FROM:.0f} units up, with the largest tenth running {CAL_TOP * 100:.0f}% high. Below that, actual usage runs
above the forecast: the smallest tenth of live forecasts average {CAL_LO_F:.1f} units against {CAL_LO_A:.1f} used, and
the held-out year shows the same shape more strongly. The safety buffer absorbs that gap on the smallest items.</p>
{B.chart("Calibration: Mean Forecast vs Mean Actual, by Forecast Decile", charts["calib"])}
<p>Error varies by demand pattern. Smooth items are forecast best and intermittent items worst, since an item used
a few times a year at random offers little to learn from. The table compares the model with the order book plus the
best simple method for each pattern, in the held-out year and live. The model's gain over the order book plus the
best simple method is concentrated in lumpy and intermittent items in the held-out year; on smooth items the simple
method is as good.</p>
{pattern_table()}
{B.chart("Live WAPE by Demand Pattern, Model vs Order Book + Best Simple Method", charts["pattern"])}
<p>Plotted against actual usage on log scales, the live forecasts cluster around the diagonal across four orders
of magnitude, meaning the same model tracks items that use a handful of units per lead time as well as those that use
thousands. The spread around the diagonal is the item-level error that the safety buffer absorbs.</p>
<div style="max-width:520px;margin:18px auto;">{B.chart("Forecast vs Actual Usage, Live 1H 2026", charts["pva"])}</div>

{B.section("study", "Section 3.3", "Feature Study")}
<p>Before go-live, groups of candidate features were added one at a time to the usage-history set: the order
book, product families, shortage history, item lifecycle (also on a longer training history), supply, and calendar
effects. Each rung was tuned and scored the same way, on total demand over the lead time. Only the order book improved
held-out accuracy on the raw forecast, and it had the lowest validation error ({pct(rung_rule['validation_wape']['S1'])});
the later groups added features without improving the held-out raw forecast, so the smaller set was kept. The
per-rung tables are in the appendix.</p>
{B.chart("Held-Out 2025 WAPE by Rung of the Feature Study", charts["ladder"])}

{B.section("shap", "Section 4", "Feature Importance (SHAP)")}
<p>SHAP values measure each feature's average contribution to a forecast, here on a sample of the held-out 2025
forecasts and in units of log usage. The model leans most on {top3[0]}, {top3[1]} and {top3[2]}. Last year's usage
over the same weeks is by far the strongest, because it is the only feature measured over exactly the window being
forecast. Lead time comes second, since it sets how long a window the forecast covers. The order book's cover of
average usage comes third; the other order-book inputs, beyond the booked quantity itself, add little.</p>
<p>Calendar and category features contribute little. About {SEASONAL_SHARE:.0%} of items are seasonal, but each peaks
at its own time of year, and last year's same-weeks usage already carries each item's own seasonal timing; a shared
week-of-year or month feature adds little on top of it. Category adds little for a similar reason, since cost, usage
level and demand pattern already capture most of what distinguishes the categories.</p>
{B.chart("Mean Absolute SHAP Value by Feature", charts["shap"])}

{B.section("policy", "Section 5", "From Forecast to Reorder Decision")}
<p>The model makes one prediction: the usage forecast, how many units each item will use over its supplier lead
time. The reorder point and order quantity presented in the ERP are then calculated from that usage forecast using
the rules below.</p>
{policy_table()}
<p><strong>Bias correction.</strong> Trained on log usage, the model's back-transformed forecasts estimate the
median rather than the mean, so they run low. Each demand pattern's forecasts are scaled by a factor re-estimated at
each monthly retrain from the trailing 52 weeks of out-of-sample errors. The table shows the factors at the first
live retrain and the corrected bias by month from the monitor. The correction removes the systematic
under-forecasting for smooth, erratic and lumpy items; intermittent items were over-corrected in {INT_MONTHS}.</p>
{bias_table()}
<p><strong>Order quantity.</strong> The recommended order quantity for each item, calculated from its usage
forecast, balances the cost of placing an order line against the cost of holding stock. Expensive, heavily used items
are ordered every few weeks, and cheap items a few times a year.</p>
<p>The chart below groups items by value class. The classes are set by annual usage value (units used &times; unit
cost): A items are those that together make up the first 80% of usage value, B items the next 15% and C items the
last 5%. In 2025 the typical A item used about {k_(ABCV.loc['A', 'med_val'])} of stock a year (most above
{k_(ABCV.loc['A', 'p10'])}) at a median unit cost of ${ABCV.loc['A', 'med_cost']:,.0f}; a typical B item about
{k_(ABCV.loc['B', 'med_val'])} a year at ${ABCV.loc['B', 'med_cost']:,.0f}; and a typical C item about
{k_(ABCV.loc['C', 'med_val'])} a year at ${ABCV.loc['C', 'med_cost']:,.0f}. The A items, where most of the money sits,
are bought in the smallest lots. See the <a href="model_overview.html">ML Model Overview</a> report for more detail on
this order quantity approach.</p>
{B.chart("Order Quantity in Days of Usage, by Value Class", charts["lots"])}
<p><strong>Safety buffer.</strong> The buffer is calculated as k standard errors of the item's own forecast
error: k &times; &sigma;, where &sigma; combines the forecast's miss over the lead time with the variability of the
supplier's delivery time, and k sets how many of those standard errors to hold. k is not taken from a normal curve.
It is set on the model's actual errors so that the expected shortfall per replenishment cycle stays within the
fill-rate target for the item's criticality group. The errors have much fatter tails than a normal curve: at k = 2 the
expected shortfall is {k_emp[2.0][0] / k_emp[2.0][1]:.1f} times what a normal distribution implies, and at k = 3,
{k_emp[3.0][0] / k_emp[3.0][1]:.1f} times. This is important to ensure an adequate buffer size. Because the shortfall
allowance scales with the order quantity, an item ordered in large lots needs less buffer (its own lot protects most
of the cycle), and an item ordered often needs more.</p>
{B.chart("Expected Shortfall vs Buffer Size: Actual Errors vs Normal", charts["loss"])}

{B.section("limits", "Section 6", "Known Limitations")}
<ul class="limitation-list">
  <li><strong>Irreducible item-level error.</strong> Lumpy and intermittent demand carries randomness no model can
  learn, and about two-fifths of items ({n_lumpy_int:,} of {attrs.shape[0]:,}) are lumpy or intermittent; much of the
  item-level WAPE of {pct(last_m['wape'], 0)} reflects that rather than the fit.</li>
  <li><strong>Accuracy and operating result are not the same measure.</strong> The order book's gain in forecast
  accuracy did not move the forward results by as much, because the ERP already netted released jobs before the
  model saw them.</li>
  <li><strong>Item-level lead times are not observable at low receipt counts.</strong> At {RCPT_LO} to {RCPT_HI} receipts a year, a
  26-week statistic cannot track a drift in an item's lead time; supplier-level pooling can, and is used for review
  rather than for the reorder point.</li>
  <li><strong>Bias on intermittent items in live use.</strong> After bias correction, the forecasts for intermittent
  items ran high in {INT_MONTHS}, which the monitor flagged for retraining; the buffers on those items were larger than
  needed in those months.</li>
  <li><strong>Superseded parts.</strong> The policy sets reorder points on superseded parts until their stock is used
  up; the ERP suppresses the order.</li>
  <li><strong>Fill rate, not stockouts.</strong> The buffer targets the share of units supplied. It does not directly
  target the probability of a stockout or of a job being held, though these important metrics are closely
  monitored.</li>
  <li><strong>Supply is taken as given.</strong> Lead times are refreshed from recent receipts and their variability
  enters the buffer, but late deliveries are not forecast.</li>
  <li><strong>Simulated data.</strong> The model is trained and evaluated on generated ERP data; accuracy on a
  shop's own records depends on the signal in them.</li>
</ul>

{B.section("ops", "Section 7", "Deployment & Operations")}
<p>How the model runs in production and where its inputs come from.</p>
{ops_table()}
<p>Getting the numbers into the ERP takes two planning fields per item per week, the reorder point and the order
quantity. They are written through the ERP's API where it offers one, and otherwise through its import utility after
the purchasing manager reviews the queue; the buyers review the queue in both cases.</p>
<p>Every reported figure comes from a fixed-seed run, archived with a checksum manifest and reproduced on the
platform.</p>

{B.section("appendix", "Appendix", "Feature Study Tables")}
<p>Held-out 2025 WAPE on total demand for the selected model at each rung, raw / bias-corrected.</p>
{A_SEG}
{A_TIER}
{A_CLS}
{A_ABC}
<p>Bias-correction factors by demand pattern for the selected model at each rung, estimated on validation.</p>
{A_BIAS}
<p>Simple methods on the feature-study rows.</p>
{A_SIMPLE}
<p>Leakage tests: the order-book inputs replaced by their values four weeks earlier. A forecast that leaned on
information not yet available on the forecast date would lose much of its accuracy when lagged; these lose
{min(LEAK.values()):.1f} to {max(LEAK.values()):.1f} points.</p>
{A_LEAK}
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(B.page("ML Model Technical Overview: Demand Forecasting", "", toc, body, credit="Created by Brian Davis, 2026"),
               encoding="utf-8")
print(f"Technical report written to {OUT}")
