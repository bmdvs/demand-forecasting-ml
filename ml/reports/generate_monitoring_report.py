"""MLOps Monitoring Report for the demand forecast -> docs/reports/monitoring_report.html

Mirrors Case 02's monitoring report: Status & Retraining Decision, then the monitoring
layers (performance, target drift, prediction drift, feature drift, data quality) and
the business outcomes the reorder policy is accountable for, then the monitoring log.
Monthly over the live window, January to June 2026, from ml/data/monitoring/.

    python -m ml.src.monitor_weekly        (after forward_policy and the forward replay)
    PYTHONIOENCODING=utf-8 "../mfg-oee-maintenance/.venv/Scripts/python.exe" -m ml.reports.generate_monitoring_report
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import brand as B
from .brand import DARK_BLUE, LIGHT_BLUE, ACCENT_RED, AMBER, GREEN, MED_GREY, LIGHT_GREY, BG_GREY, DARK_GREY

REPO = Path(__file__).resolve().parents[2]
MON = REPO / "ml" / "data" / "monitoring"
BACKTEST = REPO / "ml" / "data" / "backtest"
POLICY = REPO / "ml" / "data" / "policy"
TRUTH = REPO / "data_source" / "truth"
OUT = REPO / "docs" / "reports" / "monitoring_report.html"

summ = json.loads((MON / "monitoring_summary.json").read_text(encoding="utf-8"))
fdrift = pd.read_csv(MON / "feature_drift.csv")
rlog = pd.read_csv(MON / "retrain_log.csv")
metrics = json.loads((BACKTEST / "weekly_metrics.json").read_text(encoding="utf-8"))
sched = json.loads((POLICY / "rop_schedule.json").read_text(encoding="utf-8"))
fr = json.loads((TRUTH / "forward_results.json").read_text(encoding="utf-8"))
bt = pd.read_parquet(BACKTEST / "weekly_backtest.parquet")

P = summ["periods"]
TH = summ["thresholds"]
REFP = summ["reference_pattern"]
FT = summ["fill_target"]
names = [pd.Timestamp(p["period"] + "-01").strftime("%b %Y") for p in P]
short = [pd.Timestamp(p["period"] + "-01").strftime("%b") for p in P]
matured = [p for p in P if p["matured"]]
last_m = matured[-1]
last = P[-1]
ref_wape = float(np.abs(bt["actual"] - bt["pred_c"]).sum() / bt["actual"].sum())
SEG = ["smooth", "erratic", "lumpy", "intermittent"]
TIERS = [("line", "Production items"), ("service", "Spare parts"), ("standard", "Shop supplies")]
WIN = {"RandomForest": "Random forest", "XGBoost": "XGBoost", "Linear": "Ridge regression"}[metrics["winner"]]

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


def tag(status):
    c, i, _ = STATUS[status]
    return f'<span style="color:{c};font-weight:700;">{i} {status.title()}</span>'


# what drove the model triggers in the matured months
flag_pats = {}
for p in matured:
    for sg, w_ in p["pattern_wape"].items():
        b_ = p["pattern_bias"][sg]
        if w_ - REFP[sg]["wape"] > TH["wape_tol"] or abs(b_) > TH["bias_tol"]:
            flag_pats.setdefault(sg, []).append((p["period"], w_, b_))
model_months = [p for p in matured if p["primary"]["performance"] or p["primary"]["bias"]]
svc_months = [p for p in P if p["primary"]["service"]]
out_months = [p for p in P if p["primary"]["outcomes"]]


# ── charts ──────────────────────────────────────────────────────────────────
def _mat_color(p, c):
    return c if p["matured"] else LIGHT_GREY


def chart_wape():
    fig, ax = B.make_fig(3.2)
    vals = [p["wape"] * 100 for p in P]
    bars = ax.bar(names, vals, color=[_mat_color(p, STATUS[p["status"]][0]) for p in P], width=0.55)
    ax.axhline(ref_wape * 100, color=MED_GREY, ls="--", lw=1.4, label=f"Held-out 2025 reference {ref_wape * 100:.1f}%")
    for b_, v, p in zip(bars, vals, P):
        ax.text(b_.get_x() + b_.get_width() / 2, v + 0.6, f"{v:.1f}%" + ("" if p["matured"] else "\n(maturing)"),
                ha="center", va="bottom", fontsize=8.5)
    ax.set_ylabel("WAPE, bias-corrected (%)"); ax.set_ylim(0, max(vals) * 1.25); ax.legend(loc="lower left", fontsize=8.5)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_pattern():
    fig, ax = B.make_fig(3.2)
    x = np.arange(len(P)); w = 0.2
    cols = {"smooth": DARK_BLUE, "erratic": LIGHT_BLUE, "lumpy": MED_GREY, "intermittent": AMBER}
    for i, sg in enumerate(SEG):
        vals = [(p["pattern_bias"].get(sg, np.nan) * 100) if p["matured"] else np.nan for p in P]
        ax.bar(x + (i - 1.5) * w, vals, w, color=cols[sg], label=sg.capitalize())
    for y in (TH["bias_tol"] * 100, -TH["bias_tol"] * 100):
        ax.axhline(y, color=ACCENT_RED, ls="--", lw=1.2)
    ax.axhline(0, color=DARK_GREY, lw=0.8)
    ax.set_xticks(x); ax.set_xticklabels([n + ("" if p["matured"] else "\n(maturing)") for n, p in zip(names, P)], fontsize=8.5)
    ax.set_ylabel("Forecast bias (%)"); ax.legend(ncol=4, fontsize=8.5, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_drift(key):
    fig, ax = B.make_fig(3.0)
    vals = [p[key] for p in P]
    colors = [LIGHT_GREY if (key == "target_drift" and not p["matured"]) else (ACCENT_RED if v >= TH["drift"] else GREEN)
              for v, p in zip(vals, P)]
    bars = ax.bar(names, vals, color=colors, width=0.55)
    ax.axhline(TH["drift"], color=ACCENT_RED, ls="--", lw=1.3, label=f"Threshold {TH['drift']:.2f}")
    for b_, v, p in zip(bars, vals, P):
        note = "\n(maturing)" if key == "target_drift" and not p["matured"] else ""
        ax.text(b_.get_x() + b_.get_width() / 2, v + 0.004, f"{v:.3f}{note}", ha="center", va="bottom", fontsize=8.5)
    ax.set_ylabel("Jensen-Shannon distance"); ax.set_ylim(0, max(TH["drift"] * 1.4, max(vals) * 1.35)); ax.legend()
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_pred_dist():
    live_fc = []
    for item, entries in sched["items"].items():
        for e in entries:
            if e[0][:7] == last["period"]:
                live_fc.append(e[3])
    fig, ax = B.make_fig(3.2)
    bins = np.linspace(0, np.log1p(np.quantile(bt["pred_c"], 0.995)), 40)
    ax.hist(np.log1p(bt["pred_c"]), bins=bins, density=True, alpha=0.55, color=MED_GREY, label="Held-out 2025 reference")
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
    sq = fr["monthly"]
    for ax, key, ref, title in [(axes[0], "stockout_events", summ["ref_events"], "Stockout events"),
                                (axes[1], "jobs_held", summ["ref_held"], "Jobs held for material")]:
        vals = [p[key] for p in P]
        sqv = [sq[p["period"]]["dirty"]["stockout_episodes" if key == "stockout_events" else "jobs_delayed"] for p in P]
        ax.bar(short, vals, color=[ACCENT_RED if v > ref else DARK_BLUE for v in vals], width=0.55, label="With the model")
        ax.plot(short, sqv, "o--", color=MED_GREY, lw=1.4, label="Status quo")
        ax.axhline(ref, color=AMBER, ls="--", lw=1.3, label=f"2025 monthly average ({ref:.0f})")
        ax.set_title(title, fontsize=10, color=DARK_GREY)
        B.chart_style(ax)
    from matplotlib.patches import Patch
    h, l = axes[0].get_legend_handles_labels()
    l = [x.replace(f" ({summ['ref_events']:.0f})", "") for x in l]
    i = l.index("With the model")
    h[i], l[i] = Patch(color=DARK_BLUE), "With the model (red where above the 2025 average)"
    fig.legend(h, l, loc="lower center", ncol=3, fontsize=8.5, frameon=False, bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    return B.b64(fig)


charts = {"wape": chart_wape(), "pattern": chart_pattern(), "target": chart_drift("target_drift"),
          "pred": chart_drift("prediction_drift"), "pdist": chart_pred_dist(), "heat": chart_feat_heat(),
          "fill": chart_fill(), "outcomes": chart_outcomes()}


# ── tables and blocks ───────────────────────────────────────────────────────
def reasons():
    r = []
    for sg, hits in flag_pats.items():
        months = " and ".join(pd.Timestamp(h[0] + "-01").strftime("%B") for h in hits)
        parts = []
        if any(h[1] - REFP[sg]["wape"] > TH["wape_tol"] for h in hits):
            parts.append(f"forecast error up to {max(h[1] for h in hits) * 100:.0f}% against "
                         f"{REFP[sg]['wape'] * 100:.0f}% in 2025")
        if any(abs(h[2]) > TH["bias_tol"] for h in hits):
            parts.append(f"bias up to {max((h[2] for h in hits), key=abs) * 100:+.0f}%")
        r.append(f"{sg.capitalize()} items: {' and '.join(parts)} ({months})")
    if svc_months:
        r.append(f"Fill rate below target by more than {TH['fill_tol'] * 100:.0f} point in {len(svc_months)} of "
                 f"{len(P)} months (largest gap {max(p['fill_gap'] for p in P) * 100:.1f} points): recalibrate the "
                 f"safety buffers")
    if out_months:
        r.append("Stockout events or held jobs above the 2025 monthly average in "
                 + " and ".join(pd.Timestamp(p["period"] + "-01").strftime("%B") for p in out_months)
                 + " (the transition months)")
    return r


def _worst_pat(p):
    sg = max(p["pattern_bias"], key=lambda k: abs(p["pattern_bias"][k]))
    return f"{sg.capitalize()}: {p['pattern_wape'][sg] * 100:.0f}% WAPE, {p['pattern_bias'][sg] * 100:+.0f}% bias"


worst_pat_txt = _worst_pat(last_m)


def status_block():
    rs = reasons()
    reason_html = "<ul class='trigger-list'>" + "".join(f"<li>{x}</li>" for x in rs) + "</ul>" if rs else \
        "<p style='margin:8px 0 0;color:#8093A4;'>No triggers met.</p>"
    def c(cond):
        return ACCENT_RED if cond else GREEN
    return f"""<div class="status-block" style="border-color:{rec_color};">
      <div class="status-header" style="background:{rec_color};">
        <span class="status-icon">{rec_icon}</span><span class="status-label">{rec_label}</span>
        <span style="margin-left:auto;font-size:13px;opacity:0.9;">As of {names[-1]}</span></div>
      <div class="status-body">
        <div class="status-meta">
          <div><span class="meta-label">Model</span><span class="meta-val">demand_forecaster ({WIN}), retrained monthly</span></div>
          <div><span class="meta-label">Periods Monitored</span><span class="meta-val">{names[0]} to {names[-1]}</span></div>
          <div><span class="meta-label">Latest Matured Month</span><span class="meta-val">{pd.Timestamp(last_m['period'] + '-01').strftime('%B %Y')}</span></div>
          <div><span class="meta-label">WAPE (latest matured)</span><span class="meta-val" style="color:{c(last_m['wape'] - ref_wape > TH['wape_tol'])};">{pct(last_m['wape'])} overall (2025: {pct(ref_wape)})</span></div>
          <div><span class="meta-label">Bias (latest matured)</span><span class="meta-val" style="color:{c(abs(last_m['bias']) > TH['bias_tol'])};">{last_m['bias'] * 100:+.1f}% overall</span></div>
          <div><span class="meta-label">Worst Pattern</span><span class="meta-val" style="color:{c(last_m['primary']['performance'] or last_m['primary']['bias'])};">{worst_pat_txt}</span></div>
          <div><span class="meta-label">Target Drift</span><span class="meta-val" style="color:{c(last_m['secondary']['target_drift'])};">{last_m['target_drift']:.3f}</span></div>
          <div><span class="meta-label">Prediction Drift</span><span class="meta-val" style="color:{c(last['secondary']['prediction_drift'])};">{last['prediction_drift']:.3f}</span></div>
          <div><span class="meta-label">Features Drifted</span><span class="meta-val" style="color:{c(last['secondary']['feature_drift'])};">{last['n_features_drifted']} / {last['n_features']}</span></div>
        </div>
        <div><div style="font-size:12px;font-weight:700;color:{MED_GREY};text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px;">Trigger Reasons</div>{reason_html}</div>
      </div></div>"""


def rules_table():
    rows_spec = [
        ("Model", f"Forecast error for any demand pattern more than {TH['wape_tol'] * 100:.0f} points above its 2025 level", "performance", "Retrain if met in two consecutive matured months"),
        ("Model", f"Forecast bias for any demand pattern outside &plusmn;{TH['bias_tol'] * 100:.0f}%", "bias", "Retrain if met in two consecutive matured months"),
        ("Policy", f"Fill rate more than {TH['fill_tol'] * 100:.0f} point below target for a criticality group", "service", "Recalibrate safety buffers"),
        ("Guardrail", "Stockout events or jobs held for material above the 2025 monthly average", "outcomes", "Investigate"),
        ("Secondary", f"Target drift (distance &ge; {TH['drift']:.2f})", "target_drift", "Investigate with another secondary"),
        ("Secondary", f"Prediction drift (distance &ge; {TH['drift']:.2f})", "prediction_drift", "Investigate with another secondary"),
        ("Secondary", f"More than {TH['max_feats']} input features drifted", "feature_drift", "Investigate with another secondary"),
    ]
    head = "".join(f'<th style="text-align:center;">{s_}</th>' for s_ in short)
    rows = ""
    for tier, rule, key, action in rows_spec:
        cells = ""
        for p in P:
            v = {**p["primary"], **p["secondary"]}[key]
            if key in ("performance", "bias", "target_drift") and not p["matured"]:
                cells += f'<td style="text-align:center;color:{MED_GREY};">&middot;</td>'
            else:
                cells += (f'<td style="text-align:center;color:{ACCENT_RED if v else GREEN};font-weight:700;">'
                          f'{"&#9888;" if v else "&#10003;"}</td>')
        rows += (f'<tr><td><span style="font-size:11px;font-weight:700;color:{DARK_GREY};">{tier}</span></td>'
                 f'<td>{rule}</td><td style="font-size:12.5px;">{action}</td>{cells}</tr>')
    status_row = "".join(f'<td style="text-align:center;font-size:11px;color:{STATUS[p["status"]][0]};font-weight:700;'
                         f'line-height:1.3;">{STATUS[p["status"]][1]}<br>{p["status"].title()}</td>' for p in P)
    rows += f'<tr style="font-weight:700;"><td></td><td>Status</td><td></td>{status_row}</tr>'
    return widths(f'<table class="data-table"><thead><tr><th>Tier</th><th>Rule</th><th>Action</th>{head}</tr></thead>'
                  f'<tbody>{rows}</tbody></table>', [9, 29, 14] + [8] * len(P))


def perf_table():
    rows = [[n, f"{p['n_forecasts']:,}", pct(p["n_scored"] / p["n_forecasts"], 0), pct(p["wape"]), pct(p["base_wape"]),
             f"{p['bias'] * 100:+.1f}%", tag(p["status"])] for n, p in zip(names, P)]
    return widths(B.data_table(["Month", "Forecasts", "Matured", "WAPE", "Best simple method", "Bias", "Status"], rows,
                               right=[1, 2, 3, 4, 5]), [15, 13, 11, 12, 18, 11, 20])


def pattern_table():
    rows = []
    for sg in SEG:
        r = [sg.capitalize(), pct(REFP[sg]["wape"], 0)]
        for p in P:
            if not p["matured"] or sg not in p["pattern_wape"]:
                r.append(f'<span style="color:{MED_GREY};">&middot;</span>')
                continue
            w_, b_ = p["pattern_wape"][sg], p["pattern_bias"][sg]
            bad = w_ - REFP[sg]["wape"] > TH["wape_tol"] or abs(b_) > TH["bias_tol"]
            r.append(f'<span style="white-space:nowrap;color:{ACCENT_RED if bad else "inherit"};{"font-weight:700;" if bad else ""}">'
                     f'{w_ * 100:.0f}% / {b_ * 100:+.0f}%</span>')
        rows.append(r)
    return widths(B.data_table(["Demand pattern", "2025 WAPE"] + short, rows, right=list(range(1, len(P) + 2))),
                  [18, 12] + [70 / len(P)] * len(P))


def dq_table():
    rows = [[n, f"{p['usage_rows']:,}", f"{p['items_scored']:,}", pct(p["null_feature_share"]), f"{p['negative_usage']}",
             f"{p['unseen_items']}", f"{p['missing_attributes']}", f"{p['max_week_usage_vs_ref']:.2f}&times;"]
            for n, p in zip(names, P)]
    return widths(B.data_table(["Month", "Usage rows", "Items scored", "Rows with a missing feature", "Negative usage",
                                "Unseen items", "Missing attributes", "Largest week vs history"], rows,
                               right=[1, 2, 3, 4, 5, 6, 7]), [12, 11, 11, 16, 11, 11, 13, 15])


def feat_table():
    d = fdrift[fdrift["period"] == last["period"]].sort_values("drift_score", ascending=False)
    rows = [[f'<span style="font-family:monospace;font-size:13px;">{r.feature}</span>', f"{r.drift_score:.3f}",
             f"{TH['drift']:.2f}", f'<span style="color:{ACCENT_RED if r.drift_detected else GREEN};font-weight:700;">'
             f'{"&#9888; Drift" if r.drift_detected else "&#10003; Stable"}</span>'] for r in d.itertuples()]
    return widths(B.data_table(["Feature", "Distance", "Threshold", "Status"], rows, right=[1, 2]), [34, 22, 22, 22])


def log_table():
    rows = []
    for r in rlog.itertuples():
        p = next((x for x in P if x["period"] == r.period), None)
        rows.append([pd.Timestamp(r.period + "-01").strftime("%b %Y"), r.trained_on, r.history_through, f"{r.training_rows:,}",
                     WIN, pct(p["wape"]) + ("" if p and p["matured"] else " (maturing)") if p else "-"])
    return widths(B.data_table(["Month", "Retrained on", "History through", "Training rows", "Model", "Month's WAPE"], rows,
                               right=[3, 5]), [14, 16, 17, 15, 17, 21])


_others = [sg for sg in flag_pats if sg != max(flag_pats, key=lambda k: max(abs(h[2]) for h in flag_pats[k]))]
_ok = [sg for sg in SEG if sg not in flag_pats]
other_pats_txt = " ".join(
    [f"{sg.capitalize()} items also crossed the bias tolerance in "
     + " and ".join(pd.Timestamp(h[0] + "-01").strftime("%B") for h in flag_pats[sg]) + "." for sg in _others]
    + [(" and ".join(_ok).capitalize() + " items stay within tolerance.") if _ok else ""])
worst = max(flag_pats.items(), key=lambda kv: max(abs(h[2]) for h in kv[1])) if flag_pats else None
toc = ('<a href="#status">1 &middot; Status &amp; Decision</a>'
       '<a href="#summary">2 &middot; MLOps Monitoring Summary</a>'
       '<a href="#perf" class="sub">Performance</a>'
       '<a href="#target" class="sub">Target Drift</a>'
       '<a href="#prediction" class="sub">Prediction Drift</a>'
       '<a href="#feature" class="sub">Feature Drift</a>'
       '<a href="#quality" class="sub">Data Quality</a>'
       '<a href="#outcomes" class="sub">Business Outcomes</a>'
       '<a href="#log">3 &middot; Monitoring Log</a>')

body = f"""
{B.section("status", "Section 1", "Status &amp; Retraining Decision")}
<p>The demand forecasting model has been monitored monthly across its live window, January to June 2026. Forecast
error and bias are the primary model triggers (i.e., when these fail in two consecutive months, the model must be
retrained), while target, prediction and feature drift are leading indicators.</p>
<p>A forecast can only be scored once its lead-time window has closed, so each month is judged on accuracy once at
least {TH['matured'] * 100:.0f}% of its forecasts have matured. By June 30 that covers January to April; May and June
are shown but not yet judged on accuracy.</p>
<p>The flag reads {rec_label}. While the model is refit on new data every month as a matter of course, this
recommendation is for a full re-tune, refreshing the bias corrections and hyperparameters on data through June. This
is because {worst[0] + ' items' if worst else 'one demand pattern'} drifted outside tolerance in two consecutive
matured months. Separately, the safety buffers should be recalibrated: achieved fill rates ran below their targets
through most of the half.</p>
{status_block()}
<p>The monitoring rules are presented below across four tiers and evaluated every month. Model rules determine when
retraining is needed, the
Policy rule determines when recalibrating the safety buffers is needed, the Guardrail rule sets business KPI targets,
and the Secondary rules manage leading indicators that warrant investigation.</p>
{rules_table()}

{B.section("summary", "Section 2", "MLOps Monitoring Summary")}
<p>The layers below track the model every month. Performance is measured against the held-out 2025 year, drift
against the rows the model was trained on, and outcomes against the shop's 2025 results.</p>

{B.section("perf", "Section 2.1", "Performance")}
<p>Forecast error each month for the bias-corrected forecasts the reorder points use, against the
{pct(ref_wape)} reference from the held-out 2025 year. <strong>Across the matured months, overall error stays close
to the reference ({pct(min(p['wape'] for p in matured))} to {pct(max(p['wape'] for p in matured))}) and overall
bias stays within {max(abs(p['bias']) for p in matured) * 100:.0f}%, so the model as a whole has not degraded.</strong>
The later months' figures come from the few forecasts already matured, mostly items with short lead times, so they
are not comparable yet.</p>
{B.chart("Forecast Error (WAPE) by Month", charts["wape"])}
{perf_table()}
<p>By demand pattern the picture is less even. Each cell shows the month's error and bias.
{('<strong>' + worst[0].capitalize() + ' items were over-forecast in ' + ' and '.join(pd.Timestamp(h[0] + '-01').strftime('%B') for h in worst[1]) + ', with error rising above the 2025 level and bias beyond the tolerance. This is the trigger behind the recommendation: the bias correction set on 2025 is now too strong for these items, which leads to excess stock on them rather than shortages.</strong>') if worst else ''}
{other_pats_txt}</p>
{pattern_table()}
{B.chart("Forecast Bias by Demand Pattern and Month (tolerance &plusmn;" + f"{TH['bias_tol'] * 100:.0f}" + "%)", charts["pattern"])}

{B.section("target", "Section 2.2", "Target Drift")}
<p>Distance between each month's actual lead-time usage and the training rows (Jensen-Shannon, flagged at
{TH['drift']:.2f}). A shift would mean demand itself has moved away from what the model learned. <strong>Across the
matured months target drift stays well under the threshold ({min(p['target_drift'] for p in matured):.3f} to
{max(p['target_drift'] for p in matured):.3f}): the shop's usage looks like the usage the model was trained
on.</strong> The higher readings for May and June reflect the short-lead-time items that make up their few matured
forecasts, not a shift in demand.</p>
{B.chart("Target Drift Distance by Month", charts["target"])}

{B.section("prediction", "Section 2.3", "Prediction Drift")}
<p>Distance between each month's forecasts and the forecasts from the held-out 2025 year. A label-free early
warning, available as soon as forecasts are made. <strong>Prediction drift stays under the threshold every month
(at most {max(p['prediction_drift'] for p in P):.3f}), so the model is producing forecasts on the same scale and
spread as in 2025.</strong></p>
{B.chart("Prediction Drift Distance by Month", charts["pred"])}
{B.chart(f"Forecast Distribution: Held-out 2025 Reference vs {names[-1]}", charts["pdist"])}

{B.section("feature", "Section 2.4", "Feature Drift")}
<p>Per-feature distance between each month's inputs and the training rows; calendar features are excluded, since
they change with the date by design. <strong>{'No input feature crosses the threshold in any month' if max(p['n_features_drifted'] for p in P) == 0 else 'A few features cross the threshold'}, so
the item-level over-forecasting above is not explained by a shift in the inputs.</strong></p>
{B.chart("Per-Feature Drift Distance (feature by month)", charts["heat"])}
<p>Latest-month detail ({names[-1]}), ordered by distance:</p>
{feat_table()}

{B.section("quality", "Section 2.5", "Data Quality")}
<p>Checks on each month's inputs: usage records, items scored, missing features, negative usage, items the model
has not seen, missing item attributes, and the largest weekly usage against the largest in the training history.
<strong>The inputs arrive complete every month, with {'no' if max(p['negative_usage'] for p in P) == 0 else 'some'}
negative usage, {'no' if max(p['unseen_items'] for p in P) == 0 else 'some'} unseen items and
{'no' if max(p['missing_attributes'] for p in P) == 0 else 'some'} missing attributes, which rules out broken
inputs as a cause of the pattern-level drift.</strong></p>
{dq_table()}

{B.section("outcomes", "Section 2.6", "Business Outcomes")}
<p>The outcomes the reorder policy is accountable for, from the live replay. Fill rate is measured against each
criticality group's target. <strong>At least one group ran more than {TH['fill_tol'] * 100:.0f} point below its
target in {len(svc_months)} of {len(P)} months, by as much as {max(p['fill_gap'] for p in P) * 100:.1f} points,
narrowing to {P[-1]['fill_gap'] * 100:.1f} points by {names[-1]}. Overall forecast bias is small, so the shortfall
points to the safety buffers: calibrated on 2025 errors, they are not quite reaching the targets, and should be
recalibrated on the January to June errors.</strong> The early months also carry the handover from the manual
stock levels.</p>
{B.chart("Fill Rate by Criticality Group and Month", charts["fill"])}
<p>Stockout events and held jobs sit above the 2025 monthly average only in
{' and '.join(pd.Timestamp(p['period'] + '-01').strftime('%B') for p in out_months) or 'no month'}, the transition
months, and below it from March onward. <strong>They run below the status quo replay in every month.</strong></p>
{B.chart("Stockout Events and Held Jobs by Month", charts["outcomes"])}

{B.section("log", "Section 3", "Monitoring Log")}
<p>The model is refit at the start of each month on every forecast date whose outcome is known, with its tuned
hyperparameters held fixed. The log below records each refit, for traceability.</p>
{log_table()}
<p>Planned actions from this review: a full re-tune on data through June 2026, with the bias corrections refreshed
by demand pattern; recalibration of the safety-buffer multiples on the January to June errors; and a check at the
end of July of the May and June forecasts once they have matured.</p>
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(B.page("MLOps Monitoring Report: Demand Forecasting", "", toc, body), encoding="utf-8")
print(f"Monitoring report written to {OUT}")
