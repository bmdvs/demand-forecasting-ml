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
M = [p for p in P if p["matured"]]                       # months judged on accuracy
mnames = [pd.Timestamp(p["period"] + "-01").strftime("%b %Y") for p in M]
mshort = [pd.Timestamp(p["period"] + "-01").strftime("%b") for p in M]


LEVEL = {0: "Pass", 1: "Investigate", 2: "Retrain"}


def model_rule(p):
    """Overall model rules for a matured month: forecast error and bias."""
    return LEVEL[max(p["model_levels"]["overall_wape"], p["model_levels"]["overall_bias"])]


RULE_STYLE = {"Pass": (GREEN, "&#10003;"), "Investigate": (AMBER, "&#9680;"), "Retrain": (ACCENT_RED, "&#9888;")}
ref_wape = summ["reference_wape"]
ret_wape = ref_wape + TH["wape_overall_tol"]
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
    for sg, lv in p["pattern_levels"].items():
        if max(lv.values()) == 2:
            flag_pats.setdefault(sg, []).append((p["period"], p["pattern_wape"][sg], p["pattern_bias"][sg], lv))
inv_overall = [p for p in matured if p["model_levels"]["overall_wape"] == 1]
svc_months = [p for p in P if p["primary"]["service"]]
out_months = [p for p in P if p["primary"]["outcomes"]]


# ── charts ──────────────────────────────────────────────────────────────────
def _mat_color(p, c):
    return c if p["matured"] else LIGHT_GREY


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


def chart_pattern():
    fig, ax = B.make_fig(3.2)
    x = np.arange(len(M)); w = 0.2
    cols = {"smooth": DARK_BLUE, "erratic": LIGHT_BLUE, "lumpy": MED_GREY, "intermittent": AMBER}
    for i, sg in enumerate(SEG):
        vals = [p["pattern_bias"].get(sg, np.nan) * 100 for p in M]
        ax.bar(x + (i - 1.5) * w, vals, w, color=cols[sg], label=sg.capitalize())
    for y in (TH["bias_tol"] * 100, -TH["bias_tol"] * 100):
        ax.axhline(y, color=ACCENT_RED, ls="--", lw=1.2)
    ax.axhline(0, color=DARK_GREY, lw=0.8)
    ax.set_xticks(x); ax.set_xticklabels(mnames)
    ax.set_ylabel("Forecast bias (%)"); ax.legend(ncol=4, fontsize=8.5, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_drift(key):
    fig, ax = B.make_fig(3.0)
    PP = M if key == "target_drift" else P
    labels = [pd.Timestamp(p["period"] + "-01").strftime("%b %Y") for p in PP]
    vals = [p[key] for p in PP]
    colors = [LIGHT_GREY if (key == "target_drift" and not p["matured"]) else (ACCENT_RED if v >= TH["drift"] else GREEN)
              for v, p in zip(vals, PP)]
    bars = ax.bar(labels, vals, color=colors, width=0.55)
    ax.axhline(TH["drift"], color=ACCENT_RED, ls="--", lw=1.3, label=f"Threshold {TH['drift']:.2f}")
    for b_, v in zip(bars, vals):
        ax.text(b_.get_x() + b_.get_width() / 2, v + 0.004, f"{v:.3f}", ha="center", va="bottom", fontsize=8.5)
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
    mon = lambda ps: " and ".join(pd.Timestamp(x + "-01").strftime("%B") for x in ps)
    for sg, hits in flag_pats.items():
        parts = []
        wh = [h for h in hits if h[3]["wape"] == 2]
        bh = [h for h in hits if h[3]["bias"] == 2]
        if wh:
            parts.append(f"forecast error {' and '.join(f'{h[1] * 100:.0f}%' for h in wh)} against a Retrain threshold of "
                         f"{(REFP[sg]['wape'] + TH['wape_tol']) * 100:.0f}% ({mon([h[0] for h in wh])})")
        if bh:
            parts.append(f"bias {' and '.join(f'{h[2] * 100:+.0f}%' for h in bh)} against &plusmn;{TH['bias_tol'] * 100:.0f}% "
                         f"({mon([h[0] for h in bh])})")
        r.append(f"{sg.capitalize()} items: {'; '.join(parts)}")
    if inv_overall:
        r.append(f"Overall forecast error above the 2025 reference of {pct(ref_wape)} in {mon([p['period'] for p in inv_overall])} "
                 f"(Investigate), below the Retrain threshold of {pct(ret_wape)}")
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
    lc = {0: GREEN, 1: AMBER, 2: ACCENT_RED}
    return f"""<div class="status-block" style="border-color:{rec_color};">
      <div class="status-header" style="background:{rec_color};">
        <span class="status-icon">{rec_icon}</span><span class="status-label">{rec_label}</span>
        <span style="margin-left:auto;font-size:13px;opacity:0.9;">As of {names[-1]}</span></div>
      <div class="status-body">
        <div class="status-meta">
          <div><span class="meta-label">Model</span><span class="meta-val">demand_forecaster ({WIN}), retrained monthly</span></div>
          <div><span class="meta-label">Periods Monitored</span><span class="meta-val">{names[0]} to {names[-1]}</span></div>
          <div><span class="meta-label">Latest Matured Month</span><span class="meta-val">{pd.Timestamp(last_m['period'] + '-01').strftime('%B %Y')}</span></div>
          <div><span class="meta-label">WAPE (latest matured)</span><span class="meta-val" style="color:{lc[last_m['model_levels']['overall_wape']]};">{pct(last_m['wape'])} overall (2025: {pct(ref_wape)})</span></div>
          <div><span class="meta-label">Bias (latest matured)</span><span class="meta-val" style="color:{lc[last_m['model_levels']['overall_bias']]};">{last_m['bias'] * 100:+.1f}% overall</span></div>
          <div><span class="meta-label">Worst Pattern</span><span class="meta-val" style="color:{lc[max(last_m['model_levels']['pattern_wape'], last_m['model_levels']['pattern_bias'])]};">{worst_pat_txt}</span></div>
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
        ("Secondary", f"Target drift (distance &ge; {TH['drift']:.2f})", "target_drift", "Investigate with another secondary"),
        ("Secondary", f"Prediction drift (distance &ge; {TH['drift']:.2f})", "prediction_drift", "Investigate with another secondary"),
        ("Secondary", f"More than {TH['max_feats']} input features drifted", "feature_drift", "Investigate with another secondary"),
        ("Policy", f"Fill rate more than {TH['fill_tol'] * 100:.0f} point below target for a criticality group", "service", "Recalibrate safety buffers"),
        ("Policy", "Stockout events or jobs held for material above the 2025 monthly average", "outcomes", "Investigate"),
    ]
    icon = {0: (GREEN, "&#10003;"), 1: (AMBER, "&#9680;"), 2: (ACCENT_RED, "&#9888;")}
    head = "".join(f'<th style="text-align:center;">{s_}</th>' for s_ in short)
    rows = ""
    for tier, rule, key, action in rows_spec:
        cells = ""
        for p in P:
            if (tier == "Model" or key == "target_drift") and not p["matured"]:
                cells += f'<td style="text-align:center;color:{MED_GREY};">&middot;</td>'
                continue
            if tier == "Model":
                ml = p["model_levels"]
                v = max(ml["overall_bias"], ml["pattern_bias"]) if key == "bias" else ml[key]
            else:
                v = 2 if {**p["primary"], **p["secondary"]}[key] else 0
            c_, i_ = icon[v]
            cells += f'<td style="text-align:center;color:{c_};font-weight:700;">{i_}</td>'
        rows += (f'<tr><td><span style="font-size:11px;font-weight:700;color:{DARK_GREY};">{tier}</span></td>'
                 f'<td>{rule}</td><td style="font-size:12.5px;">{action}</td>{cells}</tr>')
    status_row = "".join(f'<td style="text-align:center;font-size:11px;color:{STATUS[p["status"]][0]};font-weight:700;'
                         f'line-height:1.3;">{STATUS[p["status"]][1]}<br>{p["status"].title()}</td>' for p in P)
    rows += f'<tr style="font-weight:700;"><td></td><td>Overall status</td><td></td>{status_row}</tr>'
    return widths(f'<table class="data-table"><thead><tr><th>Tier</th><th>Rule</th><th>Action</th>{head}</tr></thead>'
                  f'<tbody>{rows}</tbody></table>', [9, 29, 14] + [8] * len(P))


LV_COLOR = {0: GREEN, 1: AMBER, 2: ACCENT_RED}


def _val(text, level):
    return f'<span style="color:{LV_COLOR[level]};font-weight:700;">{text}</span>'


def _flag(level):
    c_, i_ = RULE_STYLE[LEVEL[level]]
    return f'<span style="color:{c_};font-weight:700;">{i_} {LEVEL[level]}</span>'


def _th(text):
    return f'<span style="color:{MED_GREY};font-style:italic;">{text}</span>'


def perf_table():
    rows = [[_th("Investigate threshold"), _th(f"above {pct(ref_wape)}"), _th("none"), ""],
            [_th("Retrain threshold"), _th(f"above {pct(ret_wape)}"), _th(f"outside &plusmn;{TH['bias_tol'] * 100:.0f}%"), ""]]
    for n, p in zip(mnames, M):
        ml = p["model_levels"]
        rows.append([n, _val(pct(p["wape"]), ml["overall_wape"]), _val(f"{p['bias'] * 100:+.1f}%", ml["overall_bias"]),
                     _flag(max(ml["overall_wape"], ml["overall_bias"]))])
    return widths(B.data_table(["Month", "Forecast error (WAPE)", "Bias", "Model rules"], rows, right=[1, 2]),
                  [28, 24, 24, 24])


def pattern_table():
    rows = [[_th("Investigate threshold")] + [_th(f"above {pct(REFP[sg]['wape'])}") for sg in SEG] + [""],
            [_th("Retrain threshold")] + [_th(f"above {pct(REFP[sg]['wape'] + TH['wape_tol'])}") for sg in SEG] + [""]]
    for n, p in zip(mnames, M):
        lv = p["pattern_levels"]
        rows.append([n] + [_val(pct(p["pattern_wape"][sg]), lv[sg]["wape"]) if sg in lv else "" for sg in SEG]
                    + [_flag(p["model_levels"]["pattern_wape"])])
    return widths(B.data_table(["Month"] + [sg.capitalize() for sg in SEG] + ["Model rules"], rows, right=[1, 2, 3, 4]),
                  [20, 14, 14, 14, 14, 24])


def pattern_bias_table():
    rows = [[_th("Retrain threshold")] + [_th(f"outside &plusmn;{TH['bias_tol'] * 100:.0f}%") for sg in SEG] + [""]]
    for n, p in zip(mnames, M):
        lv = p["pattern_levels"]
        rows.append([n] + [_val(f"{p['pattern_bias'][sg] * 100:+.1f}%", lv[sg]["bias"]) if sg in lv else "" for sg in SEG]
                    + [_flag(p["model_levels"]["pattern_bias"])])
    return widths(B.data_table(["Month"] + [sg.capitalize() for sg in SEG] + ["Model rules"], rows, right=[1, 2, 3, 4]),
                  [20, 14, 14, 14, 14, 24])


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
                     WIN, pct(p["wape"]) if p and p["matured"] else "Not yet matured"])
    return widths(B.data_table(["Month", "Retrained on", "History through", "Training rows", "Model", "Month's WAPE"], rows,
                               right=[3, 5]), [14, 16, 17, 15, 17, 21])


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
error and bias are the primary model triggers (i.e., when these exceed their Retrain thresholds, the model must be
retrained), while target, prediction and feature drift are leading indicators. Business KPIs including fill rates,
stockout events and jobs held are also tracked in this report.</p>
<p>A forecast can only be scored once its lead-time window has closed, so each month is judged on accuracy once at
least {TH['matured'] * 100:.0f}% of its forecasts have matured. By June 30th that covers January to April; May and June
are shown but not yet judged on accuracy.</p>
<p>The flag reads {rec_label}, meaning the model should be fully retrained on data through June. This is because
the model's forecast error on intermittent items rose above its Retrain threshold in March and April. Separately, the safety buffers should be recalibrated: achieved fill rates ran more than 1 point below their
targets for the five months between January and May.</p>
{status_block()}
<p>The monitoring rules are presented below across three tiers and evaluated every month. Model rules determine when
retraining is needed, Secondary rules manage leading indicators that warrant investigation, and Policy rules set
business KPI targets.</p>
{rules_table()}

{B.section("summary", "Section 2", "MLOps Monitoring Summary")}
<p>The layers below track the model every month. Performance is measured against the held-out 2025 year, drift
against the rows the model was trained on, and outcomes against the shop's 2025 results.</p>

{B.section("perf", "Section 2.1", "Performance")}
<p>Forecast error for each complete month of data is presented below against the {pct(ref_wape)} reference from
the held-out 2025 year. <strong>From January to April, overall error stays close to the reference
({pct(min(p['wape'] for p in M))} to {pct(max(p['wape'] for p in M))}) and overall bias stays within
{max(abs(p['bias']) for p in M) * 100:.0f}%, meaning the model as a whole has not degraded.</strong> March and April sit slightly above the reference, so both
are flagged to Investigate, but stay well below the Retrain threshold of {pct(ret_wape)}. Recall, May and
June's forecasts haven't matured yet, so they're not included in this chart.</p>
{B.chart("Forecast Error (WAPE) by Month", charts["wape"])}
{perf_table()}
<p>Examining forecast error by demand pattern, <strong>intermittent items were over-forecast in March and April,
with error rising above the Retrain threshold and bias beyond the tolerance. This is the trigger behind the retraining
recommendation: the bias correction set on 2025 is now too strong for these items, which leads to excess stock on
them rather than shortages.</strong> Each pattern is judged against its own 2025 level: above it flags Investigate,
and more than {TH['wape_tol'] * 100:.0f} points above flags Retrain. Smooth, erratic and lumpy items stay below their
Retrain thresholds, though some ran slightly above their 2025 levels (Investigate), most often smooth items.</p>
{pattern_table()}
<p>Bias by demand pattern is judged against the same &plusmn;{TH['bias_tol'] * 100:.0f}% threshold. Intermittent
items crossed it in March and April, and erratic items in April.</p>
{pattern_bias_table()}
{B.chart("Forecast Bias by Demand Pattern and Month (Retrain threshold &plusmn;" + f"{TH['bias_tol'] * 100:.0f}" + "%)", charts["pattern"])}

{B.section("target", "Section 2.2", "Target Drift")}
<p>Distance between each month's actual lead-time usage and the training rows (Jensen-Shannon, flagged at
{TH['drift']:.2f}). A shift would mean demand itself has moved away from what the model learned. <strong>Across the
matured months target drift stays well under the threshold ({min(p['target_drift'] for p in matured):.3f} to
{max(p['target_drift'] for p in matured):.3f}): the shop's usage looks like the usage the model was trained
on.</strong></p>
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
