"""MLOps Monitoring Report for the demand forecast -> docs/reports/monitoring_report.html

Status and retraining decision, then the monitoring layers (performance, drift, data quality), the business
KPIs the reorder policy is accountable for, the supplier lead-time review, and the monitoring log. Monthly over
the live window, January to June 2026, from the gold snapshot's monitoring tables (ml/reports/sources.py), with
the champion's 2025 predictions from the parity reference and the replay's monthly results.

    PYTHONIOENCODING=utf-8 .venv/Scripts/python -m ml.reports.generate_monitoring_report
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import brand as B
from . import sources as SR
from .brand import DARK_BLUE, LIGHT_BLUE, ACCENT_RED, AMBER, GREEN, MED_GREY, BG_GREY, DARK_GREY

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data_source" / "raw"
TRUTH = REPO / "data_source" / "truth"
SEQ = SR.REFERENCE / "runs" / "seq" / "ladder"
OUT = REPO / "docs" / "reports" / "monitoring_report.html"

summ = SR.monitoring_summary()
fdrift = SR.feature_drift()
rlog = SR.retrain_log()
bfac = SR.monitoring_table("bias_factors")
ltr = SR.monitoring_table("lead_time_reviews")
C = json.loads((SEQ / "metrics_S1.json").read_text(encoding="utf-8"))
pred25 = pd.read_parquet(SEQ / "pred_S1.parquet", columns=["item", f"predc_{C['winner']}"])
sched = SR.rop_schedule()
fr = SR.forward_results()

P = summ["periods"]
TH = summ["thresholds"]
REFP = summ["reference_pattern"]
FT = summ["fill_target"]
names = [pd.Timestamp(p["period"] + "-01").strftime("%b %Y") for p in P]
short = [pd.Timestamp(p["period"] + "-01").strftime("%b") for p in P]
M = [p for p in P if p["matured"]]                       # months judged on accuracy
last_m = M[-1]
last = P[-1]
mnames = [pd.Timestamp(p["period"] + "-01").strftime("%b %Y") for p in M]


def mon(period):
    return pd.Timestamp(period + "-01").strftime("%B")


def months(ps):
    return " and ".join(mon(x) for x in ps) if len(ps) <= 2 else ", ".join(mon(x) for x in ps[:-1]) + " and " + mon(ps[-1])


def _series(xs):
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


NUM = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}
LEVEL = {0: "Pass", 1: "Investigate", 2: "Retrain"}
LV_COLOR = {0: GREEN, 1: AMBER, 2: ACCENT_RED}
RULE_STYLE = {"Pass": (GREEN, "&#10003;"), "Investigate": (AMBER, "&#9680;"), "Retrain": (ACCENT_RED, "&#9888;")}
ref_wape = summ["reference_wape"]
ret_wape = ref_wape + TH["wape_overall_tol"]
SEG = ["smooth", "erratic", "lumpy", "intermittent"]
TIERS = [("line", "Production items"), ("service", "Spare parts"), ("standard", "Shop supplies")]
WIN = {"RandomForest": "Random forest", "XGBoost": "XGBoost", "Linear": "Ridge regression"}[C["winner"]]

STATUS = {"HEALTHY": (GREEN, "&#10003;", "NO ACTION REQUIRED"),
          "INVESTIGATE": (AMBER, "&#9680;", "INVESTIGATE"),
          "RETRAIN": (ACCENT_RED, "&#9888;", "RETRAIN RECOMMENDED")}
rec = last_m["status"] if last_m["status"] == "RETRAIN" else last["status"]
rec_color, rec_icon, rec_label = STATUS[rec]


def pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def widths(table_html, w):
    cols = "".join(f'<col style="width:{v}%;">' for v in w)
    return table_html.replace('<table class="data-table">',
                              f'<table class="data-table" style="table-layout:fixed;"><colgroup>{cols}</colgroup>', 1)


def pat_levels(p):
    """Per-pattern levels for a matured month, by the monitor's rule: error above the 2025 level is Investigate,
    more than the tolerance above it Retrain; bias outside the tolerance is Retrain."""
    out = {}
    for sg, w_ in p["pattern_wape"].items():
        r = REFP[sg]["wape"]
        out[sg] = {"wape": 2 if w_ > r + TH["wape_tol"] else 1 if w_ > r else 0,
                   "bias": 2 if abs(p["pattern_bias"][sg]) > TH["bias_tol"] else 0}
    return out


def model_rule(p):
    return LEVEL[max(p["model_levels"]["overall_wape"], p["model_levels"]["overall_bias"])]


# what drove the triggers
bias_hits = {}                                            # pattern -> [(period, bias)]
wape_inv = {}                                             # pattern -> [period]
for p in M:
    for sg, lv in pat_levels(p).items():
        if lv["bias"] == 2:
            bias_hits.setdefault(sg, []).append((p["period"], p["pattern_bias"][sg]))
        if lv["wape"] >= 1:
            wape_inv.setdefault(sg, []).append(p["period"])
factor_hits = [p["period"] for p in M if p["model_levels"]["bias_factors"] == 2]
svc_months = [p["period"] for p in P if p["primary"]["service"]]
out_months = [p["period"] for p in P if p["primary"]["outcomes"]]
drifted = [p["n_features_drifted"] for p in P]

# KPIs in stockout days: the replay's monthly results (model) against 2025's monthly average as recorded
MON26 = fr["monthly"]
MON25 = fr["monthly_2025"]
days26 = [MON26[p["period"]]["model"]["stockout_days"] for p in P]
held26 = [p["jobs_held"] for p in P]
days25 = float(np.mean([v["stockout_days"] for v in MON25.values()]))
held25 = float(np.mean([v["jobs_delayed"] for v in MON25.values()]))

# unit of measure: the ledger as booked against the physical count, on the parts whose receipts were booked in a
# purchase unit (the monitor's 47 parts)
_uom = summ["uom_gap"]
_cv = pd.read_csv(RAW / "remediation" / "uom_conversions.csv")
_cv = _cv[_cv["stock_uom"] != _cv["purchase_uom"]]
_tx = pd.read_csv(RAW / "erp" / "inventory_transactions.csv", low_memory=False)
_rc = _tx[_tx["type"] == "RECEIPT"].merge(_cv[["item_number", "purchase_uom"]], left_on=["item_number", "uom"],
                                          right_on=["item_number", "purchase_uom"])
_xw = SR.item_crosswalk().set_index("item_number")["canonical_item_number"].to_dict()
_uom_items = set(_rc["item_number"].map(lambda n: _xw.get(n, n)))
assert len(_uom_items) == _uom["items"], (len(_uom_items), _uom["items"])
_phys = json.loads((TRUTH / "physical_on_hand_end.json").read_text())
_attrs = SR.item_attributes().set_index("canonical_item_number")
_ph = {}
for k, v in _phys.items():
    c = _xw.get(k, k)
    if c in _uom_items:
        _ph[c] = max(0.0, float(v))
uom_physical = float(sum(_ph[c] * _attrs.loc[c, "standard_cost"] for c in _ph))
uom_booked = _uom["on_hand_value_as_booked"]


# ── charts ──────────────────────────────────────────────────────────────────
def chart_wape():
    fig, ax = B.make_fig(3.2)
    vals = [p["wape"] * 100 for p in M]
    bars = ax.bar(mnames, vals, color=[RULE_STYLE[model_rule(p)][0] for p in M], width=0.5)
    ax.axhline(ref_wape * 100, color=AMBER, ls="--", lw=1.4, label=f"Investigate above {ref_wape * 100:.1f}% (2025 reference)")
    ax.axhline(ret_wape * 100, color=ACCENT_RED, ls="--", lw=1.4, label=f"Retrain above {ret_wape * 100:.1f}%")
    for b_, v in zip(bars, vals):
        ax.text(b_.get_x() + b_.get_width() / 2, v - 2, f"{v:.1f}%", ha="center", va="top", fontsize=9,
                color="white", fontweight="bold")
    ax.set_ylabel("WAPE, bias-corrected (%)"); ax.set_ylim(0, max(max(vals), ret_wape * 100) * 1.15)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, fontsize=8.5, frameon=False)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_overall_bias():
    fig, ax = B.make_fig(3.0)
    vals = [p["bias"] * 100 for p in M]
    bars = ax.bar(mnames, vals, color=[LV_COLOR[p["model_levels"]["overall_bias"]] for p in M], width=0.5)
    for y in (TH["bias_tol"] * 100, -TH["bias_tol"] * 100):
        ax.axhline(y, color=ACCENT_RED, ls="--", lw=1.3)
    ax.plot([], [], color=ACCENT_RED, ls="--", lw=1.3, label=f"Retrain outside ±{TH['bias_tol'] * 100:.0f}%")
    ax.axhline(0, color=DARK_GREY, lw=0.8)
    for b_, v in zip(bars, vals):
        ax.text(b_.get_x() + b_.get_width() / 2, v + (0.5 if v >= 0 else -0.5), f"{v:+.1f}%",
                ha="center", va="bottom" if v >= 0 else "top", fontsize=9)
    lim = TH["bias_tol"] * 100 * 1.4
    ax.set_ylim(-lim, lim); ax.set_ylabel("Forecast bias (%)")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), fontsize=8.5, frameon=False)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def _pattern_bars(ax, series):
    """Grouped bars by month, one per demand pattern, each labelled with its value."""
    x = np.arange(len(M)); w = 0.2
    cols = {"smooth": DARK_BLUE, "erratic": LIGHT_BLUE, "lumpy": MED_GREY, "intermittent": AMBER}
    handles = []
    for i, sg in enumerate(SEG):
        vals = series(sg)
        bars = ax.bar(x + (i - 1.5) * w, vals, w, color=cols[sg], label=sg.capitalize())
        handles.append(bars)
        for b_, v in zip(bars, vals):
            if np.isnan(v):
                continue
            ax.text(b_.get_x() + b_.get_width() / 2, v + (0.3 if v >= 0 else -0.3), f"{v:+.1f}",
                    ha="center", va="bottom" if v >= 0 else "top", fontsize=7, color=DARK_GREY)
    ax.set_xticks(x); ax.set_xticklabels(mnames); ax.set_xlim(-0.5, len(M) - 0.5)
    return handles


def _two_legends(fig, ax, pattern_handles, threshold_handles):
    fig.legend(handles=threshold_handles, ncol=len(threshold_handles), fontsize=8.5, loc="upper center",
               bbox_to_anchor=(0.5, 1.0), frameon=False)
    fig.legend(handles=pattern_handles, ncol=4, fontsize=8.5, loc="lower center", bbox_to_anchor=(0.5, 0.0),
               frameon=False)
    fig.tight_layout(rect=(0, 0.07, 1, 0.92))


def chart_pattern():
    fig, ax = B.make_fig(3.5)
    hs = _pattern_bars(ax, lambda sg: [p["pattern_bias"].get(sg, np.nan) * 100 for p in M])
    ret = None
    for y in (TH["bias_tol"] * 100, -TH["bias_tol"] * 100):
        ret = ax.axhline(y, color=ACCENT_RED, ls="--", lw=1.3, label=f"Retrain outside ±{TH['bias_tol'] * 100:.0f}%")
    ax.axhline(0, color=DARK_GREY, lw=0.8)
    ax.set_ylabel("Forecast bias (%)")
    lo, hi = ax.get_ylim(); ax.set_ylim(lo - 1, hi + 1.5)
    B.chart_style(ax)
    _two_legends(fig, ax, hs, [ret])
    return B.b64(fig)


def chart_pattern_wape():
    fig, ax = B.make_fig(3.5)
    hs = _pattern_bars(ax, lambda sg: [(p["pattern_wape"][sg] - REFP[sg]["wape"]) * 100 if sg in p["pattern_wape"]
                                       else np.nan for p in M])
    inv = ax.axhline(0, color=AMBER, ls="--", lw=1.3, label="Investigate above 2025 level")
    ret = ax.axhline(TH["wape_tol"] * 100, color=ACCENT_RED, ls="--", lw=1.3,
                     label=f"Retrain above +{TH['wape_tol'] * 100:.0f} points")
    ax.set_ylabel("Points above 2025 level")
    lo, hi = ax.get_ylim(); ax.set_ylim(lo - 0.6, hi + 0.8)
    B.chart_style(ax)
    _two_legends(fig, ax, hs, [inv, ret])
    return B.b64(fig)


def chart_drift(key):
    fig, ax = B.make_fig(3.0)
    PP = M if key == "target_drift" else P
    labels = [pd.Timestamp(p["period"] + "-01").strftime("%b %Y") for p in PP]
    vals = [p[key] for p in PP]
    colors = [ACCENT_RED if v >= TH["drift"] else GREEN for v in vals]
    bars = ax.bar(labels, vals, color=colors, width=0.55)
    ax.axhline(TH["drift"], color=ACCENT_RED, ls="--", lw=1.3, label=f"Threshold {TH['drift']:.2f}")
    for b_, v in zip(bars, vals):
        ax.text(b_.get_x() + b_.get_width() / 2, v + 0.004, f"{v:.3f}", ha="center", va="bottom", fontsize=8.5)
    ax.set_ylabel("Jensen-Shannon distance"); ax.set_ylim(0, max(TH["drift"] * 1.4, max(vals) * 1.35)); ax.legend()
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_pred_dist():
    live_fc = [e[3] for entries in sched["items"].values() for e in entries if e[0][:7] == last["period"]]
    ref_fc = pred25[f"predc_{C['winner']}"]
    fig, ax = B.make_fig(3.2)
    bins = np.linspace(0, np.log1p(np.quantile(ref_fc, 0.995)), 40)
    ax.hist(np.log1p(ref_fc), bins=bins, density=True, alpha=0.55, color=MED_GREY, label="Held-out 2025 reference")
    ax.hist(np.log1p(live_fc), bins=bins, density=True, alpha=0.6, color=DARK_BLUE, label=f"Current ({names[-1]})")
    ticks = [0, 1, 10, 100, 1000, 10000]
    ax.set_xticks([np.log1p(t) for t in ticks if np.log1p(t) <= bins[-1]])
    ax.set_xticklabels([f"{t:,}" for t in ticks if np.log1p(t) <= bins[-1]])
    ax.set_xlabel("Forecast usage over the lead time (units, log scale)"); ax.set_ylabel("Density"); ax.legend()
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_feat_heat():
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    mat = fdrift.pivot(index="feature", columns="period", values="drift_score")
    mat = mat.loc[mat.mean(axis=1).sort_values().index]
    cmap = LinearSegmentedColormap.from_list("d", [BG_GREY, "#FFA3A3", ACCENT_RED])
    fig, ax = plt.subplots(figsize=(B.CHART_W, max(3.6, len(mat) * 0.3)))
    im = ax.imshow(mat.values, aspect="auto", cmap=cmap, vmin=0, vmax=max(TH["drift"], float(np.nanmax(mat.values))))
    ax.set_xticks(range(mat.shape[1])); ax.set_xticklabels([pd.Timestamp(c + "-01").strftime("%b %Y") for c in mat.columns])
    ax.set_yticks(range(len(mat))); ax.set_yticklabels(mat.index, fontsize=8.5)
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat.values[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7.5, color="white" if v >= TH["drift"] else DARK_GREY)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02); cb.set_label("Drift distance", fontsize=9)
    plt.tight_layout()
    return B.b64(fig)


def chart_fill():
    fig, ax = B.make_fig(3.2)
    cols = {"line": DARK_BLUE, "service": LIGHT_BLUE, "standard": MED_GREY}
    for t, lab in TIERS:
        ax.plot(short, [p["fill_by_tier"][t] * 100 for p in P], "o-", color=cols[t], lw=2,
                label=f"{lab} (target {round(FT[t] * 100, 1):g}%)")
        ax.axhline(FT[t] * 100, color=cols[t], ls=":", lw=1)
    ax.set_ylabel("Fill rate (%)"); ax.legend(fontsize=8.5, loc="lower right")
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_outcomes():
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(B.CHART_W, 3.1))
    for ax, vals, ref, title in [(axes[0], days26, days25, "Stockout days"), (axes[1], held26, held25, "Jobs held for material")]:
        bars = ax.bar(short, vals, color=[ACCENT_RED if v > ref else DARK_BLUE for v in vals], width=0.55)
        for b_, v in zip(bars, vals):
            ax.text(b_.get_x() + b_.get_width() / 2, v + max(max(vals), ref) * 0.015, f"{v:,.0f}", ha="center",
                    va="bottom", fontsize=9, color=DARK_GREY, fontweight="bold")
        ax.axhline(ref, color=AMBER, ls="--", lw=1.3)
        ax.text(len(P) - 0.45, ref, f"2025 monthly avg. {ref:,.1f}", ha="right", va="bottom", fontsize=8.5,
                color=DARK_GREY, fontweight="bold")
        ax.set_xlim(-0.6, len(P) - 0.4); ax.set_ylim(0, max(max(vals), ref) * 1.2)
        ax.set_title(title, fontsize=10, color=DARK_GREY)
        B.chart_style(ax)
    fig.tight_layout()
    return B.b64(fig)


ltr_n = ltr[ltr["level"] == "item"].groupby("period").size().reindex([p["period"] for p in P], fill_value=0)
ltr_s = ltr[ltr["level"] == "supplier"].groupby("period").size().reindex([p["period"] for p in P], fill_value=0)


def chart_reviews():
    fig, ax = B.make_fig(3.0)
    bars = ax.bar(short, ltr_n.values, color=DARK_BLUE, width=0.55)
    for b_, v in zip(bars, ltr_n.values):
        ax.text(b_.get_x() + b_.get_width() / 2, v + max(ltr_n.values) * 0.015, f"{v:,}", ha="center", va="bottom",
                fontsize=9, color=DARK_GREY, fontweight="bold")
    ax.set_ylabel("Parts flagged for review"); ax.set_ylim(0, max(ltr_n.values) * 1.2)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


charts = {"wape": chart_wape(), "obias": chart_overall_bias(), "pwape": chart_pattern_wape(), "pattern": chart_pattern(),
          "target": chart_drift("target_drift"), "pred": chart_drift("prediction_drift"), "pdist": chart_pred_dist(),
          "heat": chart_feat_heat(), "fill": chart_fill(), "outcomes": chart_outcomes(), "reviews": chart_reviews()}


# ── tables and blocks ───────────────────────────────────────────────────────
def reasons():
    r = []
    for sg, hits in bias_hits.items():
        r.append(f"{sg.capitalize()} items: corrected bias {' and '.join(f'{b * 100:+.0f}%' for _, b in hits)} against "
                 f"&plusmn;{TH['bias_tol'] * 100:.0f}% ({months([h[0] for h in hits])}); the bias-correction factor for "
                 f"the pattern is flagged with it")
    if wape_inv:
        parts = [f"{sg}{' items' if i == 0 else ''} ({', '.join(mon(x) for x in ps)})"
                 for i, (sg, ps) in enumerate(wape_inv.items())]
        r.append(f"Forecast error above its 2025 level for {_series(parts)}: Investigate, below the Retrain threshold in "
                 f"each case")
    if svc_months:
        r.append(f"Fill rate more than {TH['fill_tol'] * 100:.0f} point below target for a criticality group in "
                 f"{months(svc_months)}: recalibrate the safety buffers")
    if out_months:
        r.append(f"Stockout episodes or held jobs above the 2025 monthly average in {months(out_months)}")
    return r


def _worst_pat(p):
    sg = max(p["pattern_bias"], key=lambda k: abs(p["pattern_bias"][k]))
    return f"{sg.capitalize()}: {p['pattern_wape'][sg] * 100:.0f}% WAPE, {p['pattern_bias'][sg] * 100:+.0f}% bias"


def status_block():
    rs = reasons()
    reason_html = "<ul class='trigger-list'>" + "".join(f"<li>{x}</li>" for x in rs) + "</ul>" if rs else \
        "<p style='margin:8px 0 0;color:#8093A4;'>No triggers met.</p>"

    def c(cond):
        return ACCENT_RED if cond else GREEN
    lc = {0: GREEN, 1: AMBER, 2: ACCENT_RED}
    ml = last_m["model_levels"]
    return f"""<div class="status-block" style="border-color:{rec_color};">
      <div class="status-header" style="background:{rec_color};">
        <span class="status-icon">{rec_icon}</span><span class="status-label">{rec_label}</span>
        <span style="margin-left:auto;font-size:13px;opacity:0.9;">As of {names[-1]}</span></div>
      <div class="status-body">
        <div class="status-meta">
          <div><span class="meta-label">Model</span><span class="meta-val">demand_forecaster ({WIN}), retrained monthly</span></div>
          <div><span class="meta-label">Periods Monitored</span><span class="meta-val">{names[0]} to {names[-1]}</span></div>
          <div><span class="meta-label">Latest Matured Month</span><span class="meta-val">{pd.Timestamp(last_m['period'] + '-01').strftime('%B %Y')}</span></div>
          <div><span class="meta-label">WAPE (latest matured)</span><span class="meta-val" style="color:{lc[ml['overall_wape']]};">{pct(last_m['wape'])} overall (2025: {pct(ref_wape)})</span></div>
          <div><span class="meta-label">Bias (latest matured)</span><span class="meta-val" style="color:{lc[ml['overall_bias']]};">{last_m['bias'] * 100:+.1f}% overall</span></div>
          <div><span class="meta-label">Worst Pattern</span><span class="meta-val" style="color:{lc[max(ml['pattern_wape'], ml['pattern_bias'])]};">{_worst_pat(last_m)}</span></div>
          <div><span class="meta-label">Target Drift</span><span class="meta-val" style="color:{c(last_m['secondary']['target_drift'])};">{last_m['target_drift']:.3f}</span></div>
          <div><span class="meta-label">Prediction Drift</span><span class="meta-val" style="color:{c(last['secondary']['prediction_drift'])};">{last['prediction_drift']:.3f}</span></div>
          <div><span class="meta-label">Features Drifted</span><span class="meta-val" style="color:{c(last['secondary']['feature_drift'])};">{last['n_features_drifted']} / {last['n_features']}</span></div>
        </div>
        <div><div style="font-size:12px;font-weight:700;color:{MED_GREY};text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px;">Trigger Reasons</div>{reason_html}</div>
      </div></div>"""


def rules_table():
    rows_spec = [
        ("Model", f"Overall forecast error above the 2025 reference ({pct(ref_wape)})", "overall_wape",
         f"Investigate; Retrain if above {pct(ret_wape)}"),
        ("Model", "Forecast error for any demand pattern above its 2025 level", "pattern_wape",
         f"Investigate; Retrain if more than {TH['wape_tol'] * 100:.0f} points above"),
        ("Model", f"Forecast bias, overall or for any demand pattern, outside &plusmn;{TH['bias_tol'] * 100:.0f}%", "bias", "Retrain"),
        ("Model", f"A bias-correction factor whose pattern's corrected bias is outside &plusmn;{TH['bias_tol'] * 100:.0f}%, or "
                  f"that moved more than {TH['bias_tol'] * 100:.0f}% since the last retrain", "bias_factors", "Retrain; Investigate if it moved"),
        ("Secondary", f"Target drift (distance &ge; {TH['drift']:.2f})", "target_drift", "Investigate with another secondary"),
        ("Secondary", f"Prediction drift (distance &ge; {TH['drift']:.2f})", "prediction_drift", "Investigate with another secondary"),
        ("Secondary", f"More than {TH['max_feats']} input features drifted", "feature_drift", "Investigate with another secondary"),
        ("Policy", f"Fill rate more than {TH['fill_tol'] * 100:.0f} point below target for a criticality group", "service", "Recalibrate safety buffers"),
        ("Policy", "Stockout episodes or jobs held for material above the 2025 monthly average", "outcomes", "Investigate"),
    ]
    icon = {0: (GREEN, "&#10003;"), 1: (AMBER, "&#9680;"), 2: (ACCENT_RED, "&#9888;")}
    head = "".join(f'<th style="text-align:center;">{s_}</th>' for s_ in short)
    rows = ""
    for tier, rule, key, action in rows_spec:
        cells = ""
        for p in P:
            if ((tier == "Model" and key != "bias_factors") or key == "target_drift") and not p["matured"]:
                cells += f'<td style="text-align:center;color:{MED_GREY};">&middot;</td>'
                continue
            if tier == "Model":
                ml = p["model_levels"]
                v = max(ml["overall_bias"], ml["pattern_bias"]) if key == "bias" else ml[key]
            else:
                v = 2 if {**p["primary"], **p["secondary"]}[key] else 0
            c_, i_ = icon[v]
            cells += f'<td style="text-align:center;color:{c_};font-weight:700;">{i_}</td>'
        rows += (f'<tr><td><span style="font-weight:700;color:{DARK_GREY};">{tier}</span></td>'
                 f'<td>{rule}</td><td>{action}</td>{cells}</tr>')
    return widths(f'<table class="data-table"><thead><tr><th>Tier</th><th>Rule</th><th>Action</th>{head}</tr></thead>'
                  f'<tbody>{rows}</tbody></table>', [12, 24, 18] + [46 / len(P)] * len(P))


def _val(text, level):
    return f'<span style="color:{LV_COLOR[level]};font-weight:700;">{text}</span>'


def _flag(level):
    c_, i_ = RULE_STYLE[LEVEL[level]]
    return f'<span style="color:{c_};font-weight:700;">{i_} {LEVEL[level]}</span>'


def perf_table():
    rows = []
    for n, p in zip(mnames, M):
        ml = p["model_levels"]
        rows.append([n, _val(pct(p["wape"]), ml["overall_wape"]), _val(f"{p['bias'] * 100:+.1f}%", ml["overall_bias"]),
                     _flag(max(ml["overall_wape"], ml["overall_bias"]))])
    return widths(B.data_table(["Month", "Forecast error (WAPE)", "Bias", "Model rules"], rows, right=[1, 2]),
                  [28, 24, 24, 24])


def pattern_table():
    th = 'style="text-align:right;"'
    top = ('<th rowspan="2">Month</th>'
           + "".join(f'<th colspan="2" style="text-align:center;">{sg.capitalize()}</th>' for sg in SEG)
           + '<th rowspan="2">Model rules</th>')
    sub = "".join(f"<th {th}>Error (pts)</th><th {th}>Bias (%)</th>" for sg in SEG)
    body = ""
    for n, p in zip(mnames, M):
        lv = pat_levels(p)
        cells = ""
        for sg in SEG:
            if sg in lv:
                b_txt = f"{p['pattern_bias'][sg] * 100:+.1f}%"
                e_txt = f"{(p['pattern_wape'][sg] - REFP[sg]['wape']) * 100:+.1f}"
                cells += (f'<td {th}>{_val(e_txt, lv[sg]["wape"])}</td>'
                          f'<td {th}>{_val(b_txt, lv[sg]["bias"])}</td>')
            else:
                cells += "<td></td><td></td>"
        flag = _flag(max(p["model_levels"]["pattern_wape"], p["model_levels"]["pattern_bias"]))
        body += f"<tr><td>{n}</td>{cells}<td>{flag}</td></tr>"
    cols = "".join(f'<col style="width:{v}%;">' for v in [10] + [9.25] * 8 + [16])
    return (f'<table class="data-table" style="table-layout:fixed;"><colgroup>{cols}</colgroup>'
            f'<thead><tr>{top}</tr><tr>{sub}</tr></thead><tbody>{body}</tbody></table>')


def dq_table():
    rows = [[n, f"{p['n_forecasts']:,}", f"{p['n_scored']:,}", pct(p["data_quality"]["null_feature_share"]),
             f"{p['data_quality']['unseen_items']}"] for n, p in zip(names, P)]
    return widths(B.data_table(["Month", "Forecasts", "Scored by June 30", "Rows with a missing feature", "Items with no training rows"],
                               rows, right=[1, 2, 3, 4]), [16, 18, 20, 24, 22])


def dq2_table():
    rows = [[n, pct(p["data_quality"]["short_week_share"]), pct(p["data_quality"]["active_short_share"])]
            for n, p in zip(names, P)]
    return widths(B.data_table(["Month", "Short weeks (share of item-weeks)", "Active short weeks"], rows, right=[1, 2]),
                  [24, 38, 38])


def log_table():
    rows = []
    for r in rlog.itertuples():
        p = next((x for x in P if x["period"] == r.period), None)
        f = bfac[bfac["period"] == r.period].set_index("factor_cell")["factor"]
        facs = ", ".join(f"{sg} &times;{f[sg]:.2f}" for sg in SEG if sg in f.index)
        rows.append([pd.Timestamp(r.period + "-01").strftime("%b %Y"), r.trained_on, f"{r.training_rows:,}", facs,
                     pct(p["wape"]) if p and p["matured"] else "Not yet matured"])
    return widths(B.data_table(["Month", "Retrained on", "Training rows", "Bias-correction factors", "Month's WAPE"], rows,
                               right=[2, 4]), [11, 13, 12, 46, 18])


TIER_NAME = {"line": "production items", "service": "spare parts", "standard": "shop supplies"}
_gaps = [(t, p, FT[t] - p["fill_by_tier"][t]) for p in P for t in FT]
n_cells = len(_gaps)
n_below = sum(g > 0 for _, _, g in _gaps)
days_above = [p["period"] for p, d in zip(P, days26) if d > days25]
held_above = [p["period"] for p, h in zip(P, held26) if h > held25]
int_bias = bias_hits.get("intermittent", [])
toc = ('<a href="#status">1 &middot; Status &amp; Decision</a>'
       '<a href="#summary">2 &middot; MLOps Monitoring Summary</a>'
       '<a href="#perf" class="sub">Performance</a>'
       '<a href="#drift" class="sub">Drift</a>'
       '<a href="#quality" class="sub">Data Quality</a>'
       '<a href="#outcomes" class="sub">Business KPIs</a>'
       '<a href="#leadtime" class="sub">Supplier Lead-Time Review</a>'
       '<a href="#log">3 &middot; Monitoring Log</a>')

RETRAIN_TXT = (f"This is because, after bias correction, the forecasts for intermittent items ran high in "
               f"{months([h[0] for h in int_bias])} ({' and '.join(f'{b * 100:+.0f}%' for _, b in int_bias)}), outside "
               f"the &plusmn;{TH['bias_tol'] * 100:.0f}% Retrain threshold: the correction factors, fit on the prior "
               f"year's errors, over-correct intermittent items." if int_bias else "")
SVC_TXT = (f" Separately, the safety buffers should be recalibrated, because the fill rate achieved ran more than "
           f"{TH['fill_tol'] * 100:.0f} point below target for a criticality group in {months(svc_months)}."
           if svc_months else "")

body = f"""
{B.section("status", "Section 1", "Status &amp; Retraining Decision")}
<p>The demand forecasting model has been monitored monthly across its live window, January to June 2026. Forecast
error and bias are the primary model triggers, while target, prediction and feature drift are leading
indicators. Business KPIs including fill rates,
stockout days and jobs held are also monitored against target levels.</p>
<p>A forecast can only be scored once its lead-time window has closed, so each month is judged on accuracy once at
least {TH['matured'] * 100:.0f}% of its forecasts have matured. By June 30th that covers {months([p['period'] for p in M][:1])}
to {mon(last_m['period'])}; {months([p['period'] for p in P if not p['matured']])} are shown but not yet judged on
accuracy.</p>
<p>The flag reads {rec_label}, meaning the model should be fully retrained on data through June. {RETRAIN_TXT}{SVC_TXT}</p>
{status_block()}
<p>The monitoring rules are presented below across three tiers and evaluated every month. Model rules determine when
retraining is needed, Secondary rules manage leading indicators that warrant investigation, and Policy rules set
business KPI targets.</p>
{rules_table()}
<p>The same measures are also profiled by the platform's data profiling on the reorder schedule, the feature frame
and the forecast-error table, with the thresholds above kept as the rule.</p>

{B.section("summary", "Section 2", "MLOps Monitoring Summary")}

{B.section("perf", "Section 2.1", "Performance")}
<p>Forecast error for each complete month of data is presented below against the {pct(ref_wape)} Investigate
threshold (the model's bias-corrected WAPE on 2025 data). <strong>From {mon(M[0]['period'])} to {mon(last_m['period'])},
overall error stays below the reference ({pct(min(p['wape'] for p in M))} to {pct(max(p['wape'] for p in M))}) and
overall bias stays within {max(abs(p['bias']) for p in M) * 100:.0f}%, meaning the model as a whole has not
degraded.</strong></p>
{B.chart("Overall Forecast Error (WAPE) by Month", charts["wape"])}
{B.chart("Overall Forecast Bias by Month", charts["obias"])}
{perf_table()}
<p>Examining by demand pattern, <strong>bias for intermittent items exceeded the Retrain threshold in
{months([h[0] for h in int_bias])}. This is the primary trigger behind this report's retraining
recommendation.</strong> Forecast error stays below the Retrain threshold for every pattern, though
{_series([f"{sg} items in {months(ps)}" for sg, ps in wape_inv.items()])} ran above their 2025 level
(Investigate).</p>
{B.chart("Forecast Error by Demand Pattern, Points Above 2025 Level", charts["pwape"])}
{B.chart("Forecast Bias by Demand Pattern, % Above or Below Actual", charts["pattern"])}
{pattern_table()}

{B.section("drift", "Section 2.2", "Drift")}
<p>Drift compares each month's data with a fixed reference calculated using the Jensen-Shannon distance, flagged at
{TH['drift']:.2f}. This calculation checks for statistical similarity: whether this month's values are similar to the
reference data (the training rows for usage and features, and the held-out 2025 forecasts for the model's forecasts),
where 0 means the two are identical and 1 means they do not overlap at all. It is checked three ways: on the targets
(usage over the lead-time window), on the model's forecasts, and on the model's features.</p>
<p><strong>Target drift.</strong> Distance between each month's actual usage over the lead-time window and the
training rows. <strong>Target drift stays well under the threshold ({min(p['target_drift'] for p in M):.3f} to
{max(p['target_drift'] for p in M):.3f}), meaning monthly usage over the lead-time window resembles the usage the
model was trained on.</strong></p>
{B.chart("Target Drift Distance by Month", charts["target"])}
<p><strong>Prediction drift.</strong> Distance between each month's forecasts and the forecasts from the held-out
2025 year. <strong>Prediction drift stays under the threshold every month (at most
{max(p['prediction_drift'] for p in P):.3f}), meaning the model is producing forecasts on the same scale and spread as
in 2025.</strong></p>
{B.chart("Prediction Drift Distance by Month", charts["pred"])}
{B.chart(f"Forecast Distribution: Held-out 2025 Reference vs {names[-1]}", charts["pdist"])}
<p><strong>Feature drift.</strong> Per-feature distance between each month's inputs and the training rows, for the
{last['n_features']} features other than the calendar ones, which change with the date by design. <strong>Between
{min(drifted)} and {max(drifted)} of the {last['n_features']} features cross the threshold in any month, within the
rule's allowance of {TH['max_feats']}, meaning the model's monthly inputs resemble the inputs that the model was
trained on.</strong></p>
{B.chart("Per-Feature Drift Distance (feature by month)", charts["heat"])}

{B.section("quality", "Section 2.3", "Data Quality")}
<p>Checks on each month's inputs: the forecasts made and scored, rows with a missing feature, and scored items with
no rows in the training data. <strong>The inputs arrive complete every month: about
{min(p['data_quality']['null_feature_share'] for p in P) * 100:.0f}% of rows carry a missing feature, and
{NUM.get(last['data_quality']['unseen_items'], last['data_quality']['unseen_items'])} scored items have no training
rows.</strong></p>
{dq_table()}
<p>Two checks read the stock records themselves. A short week is an item-week in which the ledger balance reaches zero; an active short week is one in which the part also had usage, a held job or a service backorder, so
recorded usage may understate demand. On the {_uom['items']} parts whose receipts were booked in a purchase unit, the
ledger as booked carries ${uom_booked / 1000:,.1f}K of stock against ${uom_physical / 1000:,.1f}K on the physical
count: receipts booked in purchase units inflate the book until the next count corrects them.</p>
{dq2_table()}

{B.section("outcomes", "Section 2.4", "Business KPIs")}
<p><strong>Over the past six months, fill rate measured below target in {n_below} of {n_cells} months across the
three item types</strong>, and by more than {TH['fill_tol'] * 100:.0f} point for a criticality group in
{months(svc_months)}, the rule that calls for the safety buffers to be recalibrated on the January to June errors.</p>
{B.chart("Fill Rate by Item Type and Month", charts["fill"])}
<p>Stockout days sit above the 2025 monthly average in {months(days_above) if days_above else 'no month'} and below it
from {mon(P[len(days_above)]['period']) if days_above and len(days_above) < len(P) else mon(P[0]['period'])} onward; held
jobs stay {'above the 2025 average in ' + months(held_above) if held_above else 'below the 2025 average every month'}.</p>
{B.chart("Stockout Days and Held Jobs by Month", charts["outcomes"])}

{B.section("leadtime", "Section 2.5", "Supplier Lead-Time Review")}
<p>The review compares each part's pooled 26-week lead time with its corrected master lead time at each month-end,
and flags a part when the pooled figure runs more than {(TH['lead_review_ratio'] - 1) * 100:.0f}% above the master for
{TH['lead_review_months']} month-ends running; suppliers are checked the same way. A flagged master goes to
purchasing for review; the reorder point keeps using it until it is changed. Parts flagged rose from
{ltr_n.iloc[0]} in {mon(P[0]['period'])} to {ltr_n.iloc[-1]} in {mon(P[-1]['period'])}, with
{int(ltr_s.sum())} supplier flags over the six months.</p>
{B.chart("Parts Flagged for Lead-Time Review by Month", charts["reviews"])}

{B.section("log", "Section 3", "Monitoring Log")}
<p>The model is refit at the start of each month on every forecast date whose outcome is known, with its tuned
hyperparameters held fixed, and its bias-correction factors are re-estimated from the trailing 52 weeks of
out-of-sample errors. The log below records each refit, for traceability.</p>
{log_table()}
<p>Planned actions from this review: a full re-tune on data through June 2026, with the bias correction for
intermittent items reviewed; recalibration of the safety-buffer multiples on the January to June errors; a review of
the masters flagged by the lead-time review; and a check at the end of July of the May and June forecasts once they
have matured.</p>
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(B.page("MLOps Monitoring Report: Demand Forecasting", "", toc, body, credit="Created by Brian Davis, 2026"), encoding="utf-8")
print(f"Monitoring report written to {OUT}")
