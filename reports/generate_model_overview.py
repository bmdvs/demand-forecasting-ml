"""ML Model Overview and Performance Report -> docs/reports/model_overview.html

Plain-language report on the demand model and on what six months of running the shop on it delivered.
January to June 2026 is compared two ways: against 2025 as the shop recorded it (the two halves averaged
to a six-month basis), and against the same six months of demand replayed under the status quo and under
manual reordering on the cleaned records. Every figure is read from the gold snapshot (reports/sources.py),
the parity reference archive, or the truth files.

    PYTHONIOENCODING=utf-8 .venv/Scripts/python -m reports.generate_model_overview

Also writes docs/screenshots/model_outcomes.png, the summary results chart (2025 against the baseline and the
model), for the README.
"""
import base64
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import brand as B
from . import sources as SR
from .brand import DARK_BLUE, LIGHT_BLUE, MED_GREY, GREEN, DARK_GREY
from .generate_reorder_queue import build_queue

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data_source" / "raw"
OUT = REPO / "docs" / "reports" / "model_overview.html"
OUTCOMES_PNG = REPO / "docs" / "screenshots" / "model_outcomes.png"

# ── data ──────────────────────────────────────────────────────────────────────
fr = SR.forward_results()
REC = fr["as_recorded"]
H1, H2 = REC["1H25"], REC["2H25"]
F = fr["forward"]["1H26"]
VARIANTS = [("dirty", "Status quo"), ("clean_rule", "Baseline"), ("model", "The model")]
VAR_COL = {"dirty": MED_GREY, "clean_rule": LIGHT_BLUE, "model": DARK_BLUE}
# the summary chart: 2025 as recorded (halves averaged), the baseline (manual reordering on the cleaned
# records) and the model, January to June 2026
SUMMARY = [("rec25", "1H/2H '25 avg."), ("clean_rule", "Baseline"), ("model", "Demand forecasting model")]
SUMMARY_COL = {"rec25": MED_GREY, "clean_rule": LIGHT_BLUE, "model": DARK_BLUE}
SEG_ORDER = ["smooth", "erratic", "lumpy", "intermittent"]

# the champion's training run (version 1): its S1 rung result, as the parity reference archived it
S1 = json.loads((SR.REFERENCE / "runs" / "seq" / "ladder" / "metrics_S1.json").read_text(encoding="utf-8"))
tags = SR.version_tags()
champ = SR.champion_version()
champ_val = float(tags[(tags["version"] == champ) & (tags["key"] == "beats_baseline_model")]["value"].iloc[0])
assert abs(S1["candidates"][S1["winner"]]["val_wape"] - champ_val) < 5e-7, "archive S1 result is not the champion's"

attrs = SR.item_attributes()
monthly = SR.consumption_monthly()
queue_items = SR.reorder_queue()["canonical_item_number"]
n_items = len(attrs)
n_scored_items = queue_items.nunique()
unscored = sorted(set(attrs["canonical_item_number"]) - set(queue_items))
sup = SR.supersessions()
assert set(unscored) <= set(sup["superseded_by"]), "an unscored item is not a successor part"


def money(x):
    return f"${x:,.0f}"


def k(x):
    return f"${x/1e6:.2f}M" if abs(x) >= 1e6 else f"${x/1e3:.0f}K"


def pct(x, d=1):
    return f"{x*100:.{d}f}%"


def widths(table_html, w):
    cols = "".join(f'<col style="width:{v}%;">' for v in w)
    return table_html.replace('<table class="data-table">',
                              f'<table class="data-table" style="table-layout:fixed;"><colgroup>{cols}</colgroup>', 1)


def half(key):
    """2025 on a six-month basis: the two halves averaged."""
    return (H1[key] + H2[key]) / 2


def fall(a_, b_):
    return f"{(a_ - b_) / a_ * 100:.0f}%"


def chg(a_, b_):
    return f"{(b_ - a_) / a_ * 100:+.0f}%"


# ── charts ────────────────────────────────────────────────────────────────────
def _variant_panels(panels, h=3.4, series=None, colors=None, legend_bottom=False):
    """One panel per measure, one bar per series, the change against the first series above the others."""
    import matplotlib.pyplot as plt
    series, colors = series or VARIANTS, colors or VAR_COL
    fig, axes = plt.subplots(1, len(panels), figsize=(B.CHART_W, h))
    keys = [v for v, _ in series]
    for ax, (title, vals, fmt) in zip(axes, panels):
        bars = ax.bar(range(len(keys)), vals, color=[colors[v] for v in keys], width=0.7)
        for i, (b_, v) in enumerate(zip(bars, vals)):
            c_ = (v - vals[0]) / vals[0] * 100
            lab = fmt.format(v) + ("" if i == 0 else "\n(0%)" if round(c_) == 0 else f"\n({c_:+.0f}%)")
            ax.text(b_.get_x() + b_.get_width() / 2, v * 1.02, lab, ha="center", fontsize=8, fontweight="bold")
        ax.set_title(title, fontsize=9.5, color=DARK_GREY, pad=8)
        ax.set_ylim(0, max(vals) * 1.32); ax.set_yticks([]); ax.set_xticks([])
        B.chart_style(ax)
        ax.spines["left"].set_visible(False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=colors[v]) for v in keys]
    if legend_bottom:
        fig.legend(handles, [n for _, n in series], loc="lower center", ncol=len(keys), frameon=False, fontsize=9,
                   bbox_to_anchor=(0.5, 0.0))
        fig.tight_layout(w_pad=1.4, rect=(0, 0.1, 1, 1))
    else:
        fig.legend(handles, [n for _, n in series], loc="upper center", ncol=len(keys), frameon=False, fontsize=9,
                   bbox_to_anchor=(0.5, 1.0))
        fig.tight_layout(w_pad=1.4, rect=(0, 0, 1, 0.9))
    return fig


def chart_outcomes():
    """2025 as recorded (the two halves averaged) against the baseline and the model, January to June 2026:
    stockout days, held jobs, rush spend, average inventory. Also saved as docs/screenshots/model_outcomes.png."""
    def vals(key, scale=1):
        return [(half(key) if v == "rec25" else F[v][key]) / scale for v, _ in SUMMARY]
    fig = _variant_panels([
        ("Stockout days", vals("stockout_days"), "{:,.0f}"),
        ("Jobs held for material", vals("jobs_delayed"), "{:,.0f}"),
        ("Rush spend ($000)", vals("rush_spend", 1000), "${:,.0f}K"),
        ("Average inventory ($M)", vals("avg_inventory_value", 1e6), "${:,.2f}M")],
        series=SUMMARY, colors=SUMMARY_COL, legend_bottom=True)
    b64 = B.b64(fig)
    OUTCOMES_PNG.parent.mkdir(parents=True, exist_ok=True)
    OUTCOMES_PNG.write_bytes(base64.b64decode(b64))
    return b64


def chart_inventory_months():
    """Average inventory value by month under each variant, against 2025's monthly average as recorded."""
    fig, ax = B.make_fig(3.4)
    ends = {}
    for v, name in VARIANTS:
        mm = F[v]["inventory_by_month"]
        xs = [pd.Timestamp(m_) for m_ in sorted(mm)]
        ys = [mm[m_] / 1e6 for m_ in sorted(mm)]
        ax.plot(xs, ys, marker="o", color=VAR_COL[v], linewidth=2.2 if v == "model" else 1.6, label=name)
        ends[v] = (xs[-1], ys[-1])
    # end labels, nudged apart where two lines end within a few hundredths of a million of each other
    placed = []
    for v in sorted(ends, key=lambda v_: ends[v_][1], reverse=True):
        x_, y_ = ends[v]
        ly = y_
        while any(abs(ly - p) < 0.045 for p in placed):
            ly -= 0.045
        placed.append(ly)
        ax.text(x_ + pd.Timedelta(days=4), ly, f"${y_:.2f}M", fontsize=8.5, va="center", color=VAR_COL[v],
                fontweight="bold" if v == "model" else "normal")
    ax.axhline(avg25 / 1e6, color=DARK_GREY, linestyle="--", linewidth=1)
    ax.text(pd.Timestamp("2026-01-01"), avg25 / 1e6 + 0.02, "2025 monthly average, as recorded", fontsize=8, color=DARK_GREY)
    ax.set_ylabel("Average inventory ($M)")
    ax.xaxis.set_major_formatter(__import__("matplotlib.dates", fromlist=["DateFormatter"]).DateFormatter("%b"))
    ax.set_xlim(pd.Timestamp("2025-12-20"), pd.Timestamp("2026-07-10"))
    B.chart_style(ax)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False, ncol=3, fontsize=9)
    return B.b64(fig)


# the buyers' queue across the Monday refreshes of January to June 2026, from the replay of the window
STATUS = ["ORDER NOW", "ORDER SOON", "OK"]
STATUS_COL = {"ORDER NOW": B.ACCENT_RED, "ORDER SOON": B.AMBER, "OK": GREEN}
_sw = fr["status_weekly"]
status_tot = {st: sum(w.get(st, 0) for w in _sw.values()) for st in STATUS}
n_weeks = len(_sw)
n_calls = sum(status_tot.values())
# the queue as of June 30, 2026, as the ERP page shows it
q_now = build_queue()["status"].value_counts().to_dict()


def chart_actions():
    """Item-weeks by reorder action across the weekly refreshes, January to June 2026."""
    vals = [status_tot[st] for st in STATUS]
    fig, ax = B.make_fig(3.4)
    bars = ax.bar(STATUS, vals, color=[STATUS_COL[st] for st in STATUS], width=0.55)
    for b_, v in zip(bars, vals):
        ax.text(b_.get_x() + b_.get_width() / 2, v + n_calls * 0.005, f"{v:,}\n({v / n_calls:.0%})",
                ha="center", va="bottom", fontsize=10)
    ax.set_ylabel("Predictions")
    ax.set_ylim(0, max(vals) * 1.18)
    ax.yaxis.set_major_formatter(__import__("matplotlib.ticker", fromlist=["FuncFormatter"]).FuncFormatter(lambda v, _: f"{v:,.0f}"))
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_actions_by_month():
    """Average weekly predictions by reorder action, by month (months have four or five Monday refreshes)."""
    months = sorted({d_[:7] for d_ in _sw})
    x = np.arange(len(months)); w = 0.26
    fig, ax = B.make_fig(3.4)
    n_mon = {m_: sum(1 for d_ in _sw if d_[:7] == m_) for m_ in months}
    vals = {st: [sum(v.get(st, 0) for d_, v in _sw.items() if d_[:7] == m_) / n_mon[m_] for m_ in months] for st in STATUS}
    top = max(max(v) for v in vals.values())
    for i, st in enumerate(STATUS):
        bars = ax.bar(x + (i - 1) * w, vals[st], w, color=STATUS_COL[st], label=st)
        for b_, v in zip(bars, vals[st]):
            ax.text(b_.get_x() + b_.get_width() / 2, v + top * 0.012, f"{v:,.0f}", ha="center", va="bottom",
                    fontsize=7.5, color=DARK_GREY)
    ax.set_xticks(x); ax.set_xticklabels([pd.Timestamp(m_ + "-01").strftime("%b %Y") for m_ in months])
    ax.set_ylabel("Predictions per week"); ax.set_ylim(0, top * 1.15)
    ax.yaxis.set_major_formatter(__import__("matplotlib.ticker", fromlist=["FuncFormatter"]).FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), frameon=False, ncol=3, fontsize=9)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


# ── tables ────────────────────────────────────────────────────────────────────
CAND_LABEL = {"Linear": "Linear regression (ridge)", "RandomForest": "Random forest", "XGBoost": "XGBoost"}
cand = S1["candidates"]
WIN = S1["winner"]


def candidate_table():
    order = [WIN] + [c for c in ["RandomForest", "XGBoost", "Linear"] if c != WIN]
    rows = [[CAND_LABEL[c], pct(cand[c]["val_wape"]), pct(cand[c]["test_wape"]),
             f'<span style="color:{GREEN};font-weight:700;">&#10004;</span> Selected' if c == WIN else ""]
            for c in order]
    return widths(B.data_table(["Candidate", "Validation error (WAPE)", "Held-out 2025 error (WAPE)", ""], rows, right=[1, 2]),
                  [34, 24, 24, 18])


def compare_table():
    """The same six months of demand three ways; the change of the last two against the status quo."""
    d_, r_, m_ = F["dirty"], F["clean_rule"], F["model"]

    def change(key, x):
        a_ = d_[key]
        if a_ == 0:
            return ""
        c_ = (x[key] - a_) / a_ * 100
        return "0%" if round(c_) == 0 else f"{c_:+.0f}%"

    spec = [
        ("Fill rate", lambda x: pct(x["fill_rate"]), lambda x: f"{(x['fill_rate'] - d_['fill_rate']) * 100:+.1f} pts"),
        ("Stockout days", lambda x: f"{x['stockout_days']:,}", lambda x: change("stockout_days", x)),
        ("Jobs held for material", lambda x: f"{x['jobs_delayed']:,}", lambda x: change("jobs_delayed", x)),
        ("Rush freight and premiums", lambda x: money(x["rush_spend"]), lambda x: change("rush_spend", x)),
        ("Average inventory value", lambda x: money(x["avg_inventory_value"]), lambda x: change("avg_inventory_value", x)),
        ("Inventory at the end of June", lambda x: money(x["end_inventory_value"]), lambda x: change("end_inventory_value", x)),
        ("Days of usage", lambda x: f"{x['days_of_supply']:.0f}", lambda x: f"{x['days_of_supply'] - d_['days_of_supply']:+.0f} days"),
        ("Order lines placed", lambda x: f"{x['order_lines']:,}", lambda x: change("order_lines", x)),
        ("Purchases", lambda x: money(x["purchases"]), lambda x: change("purchases", x)),
    ]
    rows = [[label, fn(d_), fn(r_), ch(r_), fn(m_), ch(m_)] for label, fn, ch in spec]
    return widths(B.data_table(["Measure", "Status quo", "Baseline", "Change",
                                "Demand Forecasting Model", "Change"], rows, right=[1, 2, 3, 4, 5]), [26, 14, 18, 11, 14, 11])


# ── figures quoted in the text ────────────────────────────────────────────────
mod, rule, dirty = F["model"], F["clean_rule"], F["dirty"]
avg25 = float(np.mean(list(H1["inventory_by_month"].values()) + list(H2["inventory_by_month"].values())))
dos25 = half("days_of_supply")
# the model carries more stock than manual reordering on the cleaned records and slightly more than the status quo
assert mod["avg_inventory_value"] > rule["avg_inventory_value"] and mod["avg_inventory_value"] > dirty["avg_inventory_value"]
assert all(mod[x] < min(rule[x], dirty[x]) for x in ("stockout_days", "jobs_delayed", "rush_spend"))

# booked jobs' share of usage over the lead time, on parts that sit on a bill of materials: the champion's
# 2025 test rows (firm_h, the component requirements of booked jobs, over target, total usage)
_pred = pd.read_parquet(SR.REFERENCE / "runs" / "seq" / "ladder" / "pred_S1.parquet", columns=["item", "firm_h", "target"])
_xw = SR.item_crosswalk().set_index("item_number")["canonical_item_number"].to_dict()
_on_bill = set(pd.read_csv(RAW / "erp" / "bill_of_materials.csv")["component_item"].map(lambda n: _xw.get(n, n)))
_b = _pred[_pred["item"].isin(_on_bill)]
_o = _pred[~_pred["item"].isin(_on_bill)]
firm_share_bill = float(_b["firm_h"].sum() / _b["target"].sum())
n_bill_items = _b["item"].nunique()
assert float(_o["firm_h"].sum()) == 0.0, "an off-bill part carries booked requirements"

# the measured booking window: days from a customer order's booking to its job's release
_po = pd.read_csv(RAW / "erp" / "production_orders.csv")
_book = (pd.to_datetime(_po["release_date"]) - pd.to_datetime(_po["booked_date"])).dt.days
BOOK_LO, BOOK_HI = int(_book.min()), int(_book.max())

# intermittent items in live use: corrected bias by month, from the monitor
_pm = SR.monitoring_table("pattern_metrics")
_int = _pm[(_pm["segment"] == "intermittent") & _pm["matured"]].set_index("period")["bias"]
_high = _int[_int > SR.monitoring_summary()["thresholds"]["bias_tol"]]
INT_MONTHS = " and ".join(pd.Timestamp(p + "-01").strftime("%B") for p in _high.index)
INT_BIAS = " and ".join(f"{v * 100:+.0f}%" for v in _high.values)

# ── training data ─────────────────────────────────────────────────────────────
seg_n = attrs["segment"].value_counts().to_dict()
hist = monthly[monthly["month"] < "2026-01-01"].merge(
    attrs[["canonical_item_number", "segment", "abc", "standard_cost"]], left_on="canonical", right_on="canonical_item_number")
hist["value"] = hist["consumption"] * hist["standard_cost"].fillna(attrs["standard_cost"].median())
SEG_COL = {"smooth": DARK_BLUE, "erratic": LIGHT_BLUE, "lumpy": "#8093A4", "intermittent": "#D5DCE1"}
# the item's category, read from its item-number prefix (the class field carries a
# generic MISC placeholder on some records)
PREFIX_CAT = {"MEC": "Mechanical", "ELE": "Electrical", "RM": "Raw material", "FAS": "Fasteners",
              "HDW": "Hardware", "FIT": "Fittings", "CON": "Consumables", "SVC": "Outside service"}
CAT_ORDER = ["Mechanical", "Electrical", "Raw material", "Outside service", "Fittings", "Consumables",
             "Hardware", "Fasteners"]
CAT_COL = dict(zip(CAT_ORDER, [DARK_BLUE, "#5B45C0", LIGHT_BLUE, "#9ADCF2", "#322B4B", "#8093A4", "#B7C2CC",
                               "#D5DCE1"]))
attrs["category"] = attrs["canonical_item_number"].map(lambda n: PREFIX_CAT.get(str(n).split("-")[0], "Other"))
hist["category"] = hist["canonical"].map(attrs.set_index("canonical_item_number")["category"])
cat_seg = pd.crosstab(attrs["category"], attrs["segment"]).reindex(index=CAT_ORDER, columns=SEG_ORDER).fillna(0)
cat_share = cat_seg.div(cat_seg.sum(axis=1), axis=0)


def _avg_box(ax, text):
    ax.text(0.5, 0.97, text, transform=ax.transAxes, ha="center", va="top", fontsize=9.5, color=DARK_GREY,
            linespacing=1.5,
            bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor=DARK_GREY, linestyle="--", linewidth=1.1))


def _chart_by_category(col, scale, ylabel, avg_fmt):
    """Monthly consumption over the three years, stacked by item category, with the trend in a callout."""
    fig, ax = B.make_fig(3.9)
    w = hist.pivot_table(index="month", columns="category", values=col, aggfunc="sum").fillna(0)
    w = w.reindex(columns=[c for c in CAT_ORDER if c in w.columns]) / scale
    ax.stackplot(w.index, [w[c] for c in w.columns], colors=[CAT_COL[c] for c in w.columns],
                 labels=list(w.columns), alpha=0.95)
    tot = w.sum(axis=1); x = np.arange(len(tot)); fit = np.polyfit(x, tot.to_numpy(), 1)
    ax.plot(w.index, np.polyval(fit, x), color=DARK_GREY, linestyle="--", linewidth=1.2)
    growth = fit[0] * 12 / tot.mean() * 100
    ax.set_ylim(0, tot.max() * 1.4)
    ax.set_ylabel(ylabel)
    _avg_box(ax, avg_fmt.format(tot.mean()) + f"\nTrend: {growth:+.1f}% a year")
    B.chart_style(ax)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), frameon=False, ncol=4, fontsize=8.5)
    fig.tight_layout()
    return B.b64(fig)


def chart_value_by_category():
    return _chart_by_category("value", 1000, "Usage in value ($000 / month)",
                              "Average: ${:,.0f}K of items used per month")


def chart_units_by_category():
    return _chart_by_category("consumption", 1000, "Usage in units (000 / month)",
                              "Average: {:,.1f}K units used per month")


# cost and usage by category, 2025
_h25 = hist[(hist["month"] >= "2025-01-01") & (hist["month"] < "2026-01-01")]
# every stocked item counts, including the few with no usage in 2025
_u25 = attrs.set_index("canonical_item_number")[["category", "standard_cost"]].join(
    _h25.groupby("canonical").agg(units=("consumption", "sum"), value=("value", "sum"))).fillna({"units": 0, "value": 0})
cat_tbl = _u25.groupby("category").agg(n=("units", "size"), med_cost=("standard_cost", "median"),
                                       med_units=("units", "median"), units=("units", "sum"), value=("value", "sum"))
cat_tbl = cat_tbl.reindex([c for c in CAT_ORDER if c in cat_tbl.index])
cat_tbl["unit_share"] = cat_tbl["units"] / cat_tbl["units"].sum()
cat_tbl["value_share"] = cat_tbl["value"] / cat_tbl["value"].sum()
cat_tbl["item_share"] = cat_tbl["n"] / cat_tbl["n"].sum()


def category_table():
    rows = [[c, f"{int(r['n'])}", f"${r.med_cost:,.2f}", f"{r.med_units:,.0f}", pct(r.unit_share, 0),
             k(r.value), pct(r.value_share, 0)] for c, r in cat_tbl.iterrows()]
    rows.append(["<strong>All items</strong>", f"<strong>{int(cat_tbl['n'].sum()):,}</strong>", "", "", "<strong>100%</strong>",
                 f"<strong>{k(cat_tbl['value'].sum())}</strong>", "<strong>100%</strong>"])
    return widths(B.data_table(["Category", "Items", "Median unit cost", "Median units used per item (2025)",
                                "Share of units used (2025)", "Usage value (2025)", "Share of value (2025)"], rows,
                               right=[1, 2, 3, 4, 5, 6]), [20, 9, 14, 16, 13, 15, 13])


_hi = cat_tbl.loc[[c for c in ["Mechanical", "Electrical"] if c in cat_tbl.index]]
_lo = cat_tbl.loc[[c for c in ["Fasteners", "Hardware"] if c in cat_tbl.index]]
TBL_TEXT = (f"Item cost and usage move in opposite directions across the categories. Mechanical and electrical items "
            f"(motors, gearboxes, drives, controls) are {pct(_hi['item_share'].sum(), 0)} of items and "
            f"{pct(_hi['value_share'].sum(), 0)} of usage value, with median unit costs of "
            f"${cat_tbl.loc['Mechanical', 'med_cost']:,.0f} and ${cat_tbl.loc['Electrical', 'med_cost']:,.0f}, but only "
            f"{pct(_hi['unit_share'].sum(), 0)} of the units used. Fasteners and hardware are the reverse: "
            f"{pct(_lo['unit_share'].sum(), 0)} of the units used but {pct(_lo['value_share'].sum(), 0)} of the value, "
            f"at median unit costs under ${max(cat_tbl.loc['Fasteners', 'med_cost'], cat_tbl.loc['Hardware', 'med_cost']) + 0.5:,.0f}. "
            f"The shop's working capital is therefore tied up in a few hundred expensive, slower-moving items, not in the "
            f"high-volume floor stock.")


def chart_category_patterns():
    """Number of items in each category, stacked by demand pattern."""
    fig, ax = B.make_fig(3.7)
    bottom = np.zeros(len(cat_seg))
    totals = cat_seg.sum(axis=1).to_numpy()
    for seg in SEG_ORDER:
        vals = cat_seg[seg].to_numpy()
        ax.bar(cat_seg.index, vals, bottom=bottom, color=SEG_COL[seg], width=0.65, label=seg.capitalize())
        # each segment's share of its category, where the segment is tall enough to hold a label
        for i, (v, b0) in enumerate(zip(vals, bottom)):
            if v >= 7:
                ax.text(i, b0 + v / 2, f"{v / totals[i] * 100:.0f}%", ha="center", va="center", fontsize=7.5,
                        color="white" if seg in ("smooth", "lumpy") else DARK_GREY)
        bottom += vals
    for i, tot_ in enumerate(bottom):
        ax.text(i, tot_ + 5, f"{int(tot_)}", ha="center", fontsize=8.5, fontweight="bold")
    ax.set_ylabel("Items")
    ax.set_ylim(0, bottom.max() * 1.18)
    ax.set_xticks(range(len(cat_seg))); ax.set_xticklabels([c.replace(" ", "\n") for c in cat_seg.index])
    ax.tick_params(axis="x", labelsize=8.5)
    B.chart_style(ax)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), frameon=False, ncol=4, fontsize=9)
    fig.tight_layout()
    return B.b64(fig)


def _top(seg, n=2):
    s_ = cat_share[seg].sort_values(ascending=False).head(n)
    return " and ".join(f"{c.lower()} ({v*100:.0f}%)" for c, v in s_.items())


CAT_TEXT = (f"Individual demand patterns are informed by the kind of item, though every category carries all four "
            f"patterns. Smooth demand is most common among {_top('smooth')}, the floor stock used consistently every "
            f"week. Erratic demand is spread widely, and is highest among {_top('erratic')}. Lumpy demand concentrates "
            f"in {_top('lumpy')}. Intermittent demand is highest in {_top('intermittent')}, where just a few of these "
            f"high-cost items are used for a job or sold as occasional spares.")


def chart_examples():
    """One representative item per demand pattern, 36 months of monthly consumption."""
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 4, figsize=(B.CHART_W, 2.6), sharey=False)
    for ax, seg in zip(axes, SEG_ORDER):
        g = hist[hist["segment"] == seg]
        tot = g.groupby("canonical")["consumption"].sum()
        item = tot.sort_values().index[int(len(tot) * 0.6)]          # a typical, not an extreme, item
        sr = g[g["canonical"] == item].set_index("month")["consumption"].reindex(
            pd.date_range("2023-01-01", "2025-12-01", freq="MS"), fill_value=0)
        ax.bar(sr.index, sr.values, width=20, color=SEG_COL[seg] if seg != "intermittent" else "#8093A4")
        ax.set_title(f"{seg.capitalize()}\n{item}", fontsize=9, color=DARK_GREY)
        ax.tick_params(axis="x", labelsize=7, rotation=0); ax.tick_params(axis="y", labelsize=7)
        ax.xaxis.set_major_locator(__import__("matplotlib.dates", fromlist=["YearLocator"]).YearLocator())
        ax.xaxis.set_major_formatter(__import__("matplotlib.dates", fromlist=["DateFormatter"]).DateFormatter("%Y"))
        B.chart_style(ax)
    axes[0].set_ylabel("Units / month", fontsize=8)
    fig.tight_layout(w_pad=1.2)
    return B.b64(fig)


FLOW_HTML = (
    '<div style="display:flex;align-items:stretch;gap:0;margin:22px 0;flex-wrap:wrap;">'
    '<div style="flex:1;min-width:190px;background:#F3F5F7;border-radius:8px;padding:16px 18px;border-top:4px solid #381FA1;">'
    '<div style="font-weight:700;color:#322B4B;margin-bottom:6px;">1. What it reads</div>'
    '<div style="font-size:16px;line-height:1.55;">Three years of cleaned usage history for every stocked item, '
    'with its demand pattern, value class, cost and supplier lead time, and the component requirements of '
    'booked jobs.</div></div>'
    '<div style="align-self:center;font-size:26px;color:#8093A4;padding:0 12px;">&rarr;</div>'
    '<div style="flex:1;min-width:190px;background:#F3F5F7;border-radius:8px;padding:16px 18px;border-top:4px solid #381FA1;">'
    '<div style="font-weight:700;color:#322B4B;margin-bottom:6px;">2. What it predicts</div>'
    '<div style="font-size:16px;line-height:1.55;">Every week, one forecast per item: how many units the shop will use '
    'before a new order placed today could arrive.</div></div>'
    '<div style="align-self:center;font-size:26px;color:#8093A4;padding:0 12px;">&rarr;</div>'
    '<div style="flex:1;min-width:190px;background:#F3F5F7;border-radius:8px;padding:16px 18px;border-top:4px solid #381FA1;">'
    '<div style="font-weight:700;color:#322B4B;margin-bottom:6px;">3. What it produces</div>'
    '<div style="font-size:16px;line-height:1.55;">For every item, when to reorder and how much, loaded into the ERP, '
    'which checks every item daily and flags what to order.</div></div></div>')

_png = REPO / "docs" / "screenshots" / "erp_queue.png"
erp_b64 = base64.b64encode(_png.read_bytes()).decode()

charts = {"outcomes": chart_outcomes(), "actions": chart_actions(),
          "actions_m": chart_actions_by_month(), "invm": chart_inventory_months(), "valcat": chart_value_by_category(),
          "catseg": chart_category_patterns(), "unitcat": chart_units_by_category(), "examples": chart_examples()}

toc = ('<a href="#summary">Executive Summary</a><hr>'
       '<a href="#modeloverview">Model Overview</a>'
       '<a href="#what" class="sub">What This Model Does</a>'
       '<a href="#data" class="sub">Training Data Overview</a><hr>'
       '<a href="#performance">Model Performance</a>'
       '<a href="#scoring" class="sub">Scoring Summary</a>'
       '<a href="#accuracy" class="sub">Accuracy and Validation</a>'
       '<a href="#limits" class="sub">Assumptions &amp; Limitations</a>')


body = f"""
{B.section("summary", "Section 1", "Executive Summary")}
<p>The demand forecasting model sets the reorder decisions for each of the shop's {n_items:,} stocked items. The
model takes the parts that booked jobs will draw as known and forecasts the rest of
each item's usage before a new order could arrive, then turns the total into a reorder point and order quantity. It
is trained using a random forest machine learning algorithm. The model has been live for the past six months, from
January through June 2026.</p>
<p>Before the model, reordering was done manually and ran on data that was messy and couldn't be trusted. Much of
the reordering process was labor-intensive and imprecise: stock levels and lead times were stale, stock on hand was
unverified, safety stock was inflated, and rush orders were relied upon to compensate for shortfalls. The result
was the shop carrying excess inventory, {dos25:.0f} days of usage, yet still logging elevated stockout days,
held jobs for missing material and rush freight spend.</p>
<p>The results below compare the performance of the demand forecasting model and baseline method in January to June
2026 against 2025 as the shop recorded it, with 2025's two halves averaged to a six-month basis. Baseline assumes the
shop continued their manual reordering process as they did in 2025 on the newly cleaned data records. The model achieved
significant improvements in stockout days (<strong>{chg(half('stockout_days'), mod['stockout_days'])}</strong>),
jobs held for material (<strong>{chg(half('jobs_delayed'), mod['jobs_delayed'])}</strong>), and rush spend
(<strong>{chg(half('rush_spend'), mod['rush_spend'])}</strong>), while average inventory fell
<strong>{fall(half('avg_inventory_value'), mod['avg_inventory_value'])}</strong>, to
${mod['avg_inventory_value'] / 1e6:.1f}m, or {mod['days_of_supply']:.0f} days of usage from {dos25:.0f} in 2025.</p>
{B.chart("ML-driven vs. baseline, January to June 2026 against 1H/2H 2025", charts["outcomes"])}

{B.section("modeloverview", "Section 2", "Model Overview")}

{B.section("what", "Section 2.1", "What This Model Does")}
<p>The demand forecasting model is built on an ensemble decision-tree algorithm called a random forest. Every week,
the model predicts which items need to be reordered, and these predictions are then fed directly into the ERP for
each of the {n_scored_items:,} items it scores. The model's reorder decisions are based on the current stock on hand
and on order for each item, the forecasted usage over each supplier's delivery time, and a safety buffer based on
how unpredictable each item's demand and deliveries have been.</p>
{FLOW_HTML}
<p>The model refreshes its forecasts every week and is retrained on the latest history once a month. The reorder
point covers the usage the ERP cannot see ahead; the ERP nets the requirements of booked jobs itself. The model's
predictions are loaded directly into the ERP, which flags when each item should be reordered and how much to order.
To keep working capital low, the recommendations for how much to order are informed by the item's cost: expensive
items are bought every few weeks in small lots, and cheap items a few times a year in larger lots.</p>
<p>The ERP's reorder queue ranks every stocked item against the model's weekly reorder point: items at or below it
are marked "ORDER NOW", items within two weeks of it "ORDER SOON", and items more than two weeks outside of it
"OK". Parts that have been replaced by a successor are marked "PHASE OUT", with the successor named, and carry no
suggested order. Each line also shows the stock on hand, allocated to released jobs, booked over the lead time (the
component requirements of booked jobs, which the model takes as known) and on order, the forecast, the safety stock
and the suggested order quantity, as seen in the screenshot of the ERP system below:</p>
<div class="chart-wrap" style="padding:6px;">
  <img src="data:image/png;base64,{erp_b64}" alt="ERP reorder queue with the demand model's reorder points"
       style="width:100%;height:auto;display:block;border:1px solid #D5DCE1;">
</div>

{B.section("data", "Section 2.2", "Training Data Overview")}
<p>The model learns from the shop's historical usage of every stocked item. It was originally trained on three
years of this usage data (2023 through 2025, as shown below), and is continually trained on every new month
of data.</p>
{B.chart("MONTHLY USAGE IN VALUE, BY ITEM CATEGORY (JAN. 2023 to DEC. 2025)", charts["valcat"])}
{B.chart("MONTHLY USAGE IN UNITS, BY ITEM CATEGORY (JAN. 2023 to DEC. 2025)", charts["unitcat"])}
<p>Demand is steady in aggregate over the three years, but individual items exhibit very different demand patterns.
We've categorized these individual item demand patterns into four groups, which the model is calibrated against:
{seg_n.get('smooth', 0)} smooth (regular and steady), {seg_n.get('erratic', 0)} erratic (regular but variable),
{seg_n.get('lumpy', 0)} lumpy (irregular and variable) and {seg_n.get('intermittent', 0)} intermittent (many months
with no demand at all). One representative item within each pattern is shown below.</p>
{B.chart("Three years of monthly usage, one representative item per demand pattern", charts["examples"])}
<p>Part of each item's usage is known before it happens. On the {n_bill_items:,} parts that sit on a bill of
materials, the component requirements of booked jobs account for about a third
({pct(firm_share_bill, 0)}) of total usage over the item's lead time; floor pulls and service issues are the rest,
and that remainder is what the model forecasts. Parts that sit on no bill are forecast in full.</p>
<p>{CAT_TEXT}</p>
{B.chart("Items in each category, by demand pattern", charts["catseg"])}
<p>{TBL_TEXT}</p>
{category_table()}
{B.section("performance", "Section 3", "Model Performance")}

{B.section("scoring", "Section 3.1", "Scoring Summary")}
<p>Across the {n_weeks} Monday refreshes of the buyers' queue, it made {n_calls:,} predictions: <strong>{status_tot['ORDER NOW']:,}</strong>
({status_tot['ORDER NOW'] / n_calls:.0%}) were marked ORDER NOW and <strong>{status_tot['ORDER SOON']:,}</strong>
({status_tot['ORDER SOON'] / n_calls:.0%}) ORDER SOON, and the rest were OK. In a typical week that is about
{status_tot['ORDER NOW'] / n_weeks:.0f} items to order now and {status_tot['ORDER SOON'] / n_weeks:.0f} to order soon,
a short, ranked list for the buyers to work through. On June 30, 2026 the queue held
{q_now.get('ORDER NOW', 0)} items to order now, {q_now.get('ORDER SOON', 0)} to order soon and
{q_now.get('PHASE OUT', 0)} to phase out: parts replaced by a successor, which the shop runs down rather than
reorders.</p>
{B.chart("Predictions by Reorder Action, January to June 2026", charts["actions"])}
{B.chart("Average Weekly Predictions by Reorder Action, by Month", charts["actions_m"])}

{B.section("accuracy", "Section 3.2", "Accuracy and Validation")}
<p>See the <a href="technical_report.html">ML Model Technical Overview</a> report for more detail on the
model's performance and validation metrics.</p>
<p>The model was chosen and calibrated before go-live on held-out data for the full year of 2025. Three candidate
algorithms were tuned and compared on their forecasts for that year, and the
{CAND_LABEL[WIN].lower() if WIN != 'XGBoost' else 'XGBoost'} model, with the lowest error, was selected. Validation
error is scored on total usage over each item's lead time.</p>
{candidate_table()}
<p>To understand how well the model performed against baseline, we'll compare the performance of the model and
baseline in the 1H 2026 to the same period of time under a status quo scenario. This status quo scenario assumes
the shop operated in 1H 2026 as it did throughout 2025, including manual reordering and with the data errors fully
intact (with stale lead times and reorder points). Baseline assumes the same manual reordering on cleaned
records.</p>
{compare_table()}
<p>The model carries more stock than manual reordering on the cleaned records and slightly more than the status
quo over the same six months.</p>
{B.chart("Average inventory by month, January to June 2026", charts["invm"])}

{B.section("limits", "Section 3.3", "Assumptions &amp; Limitations")}
<ul class="limitation-list">
  <li><strong>It forecasts demand, not supply.</strong> The model predicts how much the shop will use; it takes each
      supplier's lead time from its recent deliveries, refreshed monthly, and does not predict a late delivery. The buffer covers
      the usual spread of deliveries, not a supplier failure.</li>
  <li><strong>Booking visibility.</strong> Customer orders are booked {BOOK_LO} to {BOOK_HI} days before
      their jobs are released.</li>
  <li><strong>Expediting is held constant.</strong> All three replays expedite the same items the purchasing
      manager tracked before go-live, so rush spend reflects how often those items were at risk, not a change in
      how hard the shop chases suppliers.</li>
  <li><strong>Intermittent items ran high in live use.</strong> After bias correction, the forecasts for intermittent
      items ran high in {INT_MONTHS} ({INT_BIAS}), which the monitor flagged for retraining; the buffers on those
      items were larger than needed in those months.</li>
</ul>
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
html = B.page("ML Model Overview and Performance: Demand Forecasting", "", toc, body, credit="Created by Brian Davis, 2026")
html = html.replace("</style></head>", ".section-title-block.sub .section-title{font-size:18px;font-weight:700;}</style></head>", 1)
OUT.write_text(html, encoding="utf-8")
print(f"Model overview written to {OUT}  ({len(html)//1024} KB)")
