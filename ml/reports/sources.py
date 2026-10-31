"""Inputs of the report generators, read from the gold snapshot (exports/gold_snapshot/).

Each function returns its input in the form the generators have always read: the mart files' column names
and types, the reorder schedule as its document, the monitor's summary and CSV tables, the forward results
with their replayed variants. The snapshot's MANIFEST.json says which table, Delta version and job run each
file came from. Inputs the snapshot does not carry stay where they are: the local analyses in ml/data
(weekly model metrics, three-way training, explain outputs, reliability, financials), the extracts and the
truth files in data_source/, and the feature-study ladder in runs/ladder/.

The reorder schedule document's settings (planning origins, fill-rate targets, lot rules, service factors)
are not table columns; they are read from the parity reference's schedule document, and the items from the
snapshot table.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
SNAP = REPO / "exports" / "gold_snapshot"
REFERENCE = REPO / "reference" / "2026-10_post_signal_update"
TRUTH = REPO / "data_source" / "truth"
LADDER = REPO / "runs" / "ladder"


def _read(folder: str, name: str) -> pd.DataFrame:
    return pd.read_parquet(SNAP / folder / f"{name}.parquet")


def _naive(s: pd.Series, unit: str = "ns") -> pd.Series:
    """Snapshot timestamps (UTC) and dates as the naive timestamps the mart files hold."""
    s = pd.to_datetime(s)
    if getattr(s.dt, "tz", None) is not None:
        s = s.dt.tz_convert("UTC").dt.tz_localize(None)
    return s.astype(f"datetime64[{unit}]")


@lru_cache(maxsize=None)
def manifest() -> dict:
    return json.loads((SNAP / "MANIFEST.json").read_text(encoding="utf-8"))


# ── warehouse marts ──────────────────────────────────────────────────────────
def consumption_weekly() -> pd.DataFrame:
    """ml/data/marts/consumption_weekly.parquet: canonical, week, consumption."""
    df = _read("tables", "mart_consumption_weekly").rename(columns={"canonical_item_number": "canonical"})
    df["week"] = _naive(df["week"])
    df["consumption"] = df["consumption"].astype("float64")
    return df[["canonical", "week", "consumption"]].sort_values(["canonical", "week"]).reset_index(drop=True)


def consumption_monthly() -> pd.DataFrame:
    """ml/data/marts/consumption_monthly.parquet (the fully cleaned series): canonical, month, consumption."""
    df = _read("tables", "mart_consumption_fully").rename(columns={"canonical_item_number": "canonical"})
    df["month"] = _naive(df["month"])
    df["consumption"] = df["consumption"].astype("float64")
    return df[["canonical", "month", "consumption"]].sort_values(["canonical", "month"]).reset_index(drop=True)


def item_attributes() -> pd.DataFrame:
    """ml/data/marts/item_attributes.parquet."""
    cols = ["canonical_item_number", "standard_cost", "item_class", "segment", "abc", "corrected_lead_days",
            "annual_consumption"]
    return _read("tables", "mart_item_attributes")[cols].sort_values("canonical_item_number").reset_index(drop=True)


def item_crosswalk() -> pd.DataFrame:
    """ml/data/marts/item_crosswalk.csv: item_number, canonical_item_number."""
    df = _read("tables", "int_item_crosswalk")[["item_number", "canonical_item_number"]]
    return df.sort_values("item_number").reset_index(drop=True)


def error_register() -> list[tuple]:
    """The audit's error register (mart_dq_error_summary): error_no, erp_table, rows_flagged, rows_in_scope."""
    df = _read("tables", "mart_dq_error_summary")
    return [(int(r.error_no), r.erp_table, int(r.rows_flagged), int(r.rows_in_scope)) for r in df.itertuples()]


# ── model tables (the run that issued the schedule in force) ─────────────────
def weekly_backtest() -> pd.DataFrame:
    """ml/data/backtest/weekly_backtest.parquet."""
    df = _read("tables", "weekly_backtest")
    df["week"] = _naive(df["week"])
    return df.sort_values(["item", "t", "h"]).reset_index(drop=True)


def rop_schedule() -> dict:
    """ml/data/policy/rop_schedule.json: the reference document's settings with the snapshot's entries."""
    ref = json.loads((REFERENCE / "ml" / "data" / "policy" / "rop_schedule.json").read_text(encoding="utf-8"))
    tab = _read("tables", "reorder_schedule")
    fields = ref["entry_fields"]
    tab["date"] = pd.to_datetime(tab["date"]).dt.strftime("%Y-%m-%d")
    items: dict = {}
    for item, g in tab.groupby("canonical_item_number", sort=False):
        g = g.sort_values("date")
        items[item] = [[v.item() if hasattr(v, "item") else v for v in row]
                       for row in g[fields].itertuples(index=False, name=None)]
    doc = {k: v for k, v in ref.items() if k != "items"}
    doc["items"] = {k: items[k] for k in ref["items"]} if set(items) == set(ref["items"]) else items
    return doc


def reorder_queue() -> pd.DataFrame:
    """gold.reorder_queue: one row per item, the schedule entry in force on the as-of date."""
    return _read("tables", "reorder_queue")


# ── monitoring (the run that judged the schedule in force) ───────────────────
def monitoring_summary() -> dict:
    """ml/data/monitoring/signals/monitoring_summary.json."""
    return json.loads(_read("monitoring", "monitoring_summary")["summary_json"].iloc[0])


def monitoring_table(name: str) -> pd.DataFrame:
    """A monitoring table without its model_version column (the signals CSVs carry none)."""
    return _read("monitoring", name).drop(columns=["model_version"], errors="ignore")


def feature_drift() -> pd.DataFrame:
    """ml/data/monitoring/signals/feature_drift.csv."""
    return monitoring_table("feature_drift")


def retrain_log() -> pd.DataFrame:
    """ml/data/monitoring/signals/retrain_log.csv."""
    return monitoring_table("retrain_log")


# ── registry ─────────────────────────────────────────────────────────────────
def version_tags() -> pd.DataFrame:
    return _read("registry", "version_tags")


def champion_version() -> int:
    a = _read("registry", "aliases")
    return int(a.loc[a["alias"] == "champion", "version"].iloc[0])


# ── forward replay ───────────────────────────────────────────────────────────
def forward_results() -> dict:
    """data_source/truth/forward_results.json with its replayed variants (forward windows and months) taken
    from the snapshot's replay table; the other sections (2025 as recorded, 2025 by month, weekly status
    counts) stay as the truth file holds them. Values take the truth file's types."""
    doc = json.loads((TRUTH / "forward_results.json").read_text(encoding="utf-8"))
    rep = _read("replay", "forward_replay")
    rebuilt: dict = {"window": {}, "month": {}}
    for r in rep.itertuples(index=False):
        node = rebuilt[r.scope].setdefault(r.period, {}).setdefault(r.variant, {})
        *path, leaf = r.metric.split(".")
        for p in path:
            node = node.setdefault(p, {})
        node[leaf] = r.text if r.text is not None and not (isinstance(r.text, float)) else r.value
    for key, scope in (("forward", "window"), ("monthly", "month")):
        doc[key] = _typed(rebuilt[scope], doc[key])
    return doc


def _typed(new, like):
    """new, with each leaf given the type of the same leaf in like (ints stay ints)."""
    if isinstance(like, dict):
        return {k: _typed(new[k], like[k]) for k in like} if set(new) == set(like) else new
    if isinstance(like, bool):
        return bool(new)
    if isinstance(like, int) and isinstance(new, float) and new.is_integer():
        return int(new)
    return new
