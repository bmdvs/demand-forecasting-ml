"""Demand-signal features for the weekly forecast.

Every function here is pure: it takes DataFrames and arrays, returns DataFrames or arrays,
and reads and writes no files. Dates, not paths, parameterize the work. Each feature for
an item at an origin week uses only records known on or before the origin; the builders
assert that where a record carries its own known-from date.

The frame is one row per canonical item and origin week index t (the Monday weeks[t]).
Horizon h is the reference horizon, the corrected master lead time in whole weeks, the
same for every rung so that every rung is scored on the same target.

Feature groups, added cumulatively by rung:
  S1  order book       firm requirements over the horizon and beyond, open jobs, cover,
                       the parent families' open order book
  S2  families         material/class family usage, the item's share of it, parent
                       product builds and bookings
  S3  censoring        short weeks, held jobs, time since the last short week
  S4a lifecycle        age and available history, bill membership and changes, part
                       supersession, the installed base behind service parts
  S4b history          the minimum history lowered to 13 weeks, a prior below it
  S5  supply           point-in-time lead-time statistics and supplier performance
  S6  calendar         working days and shutdowns in the horizon, the quarter, time
                       since the item's last spike
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .demand_model import FEATS as REFERENCE_FEATS

GROUPS = {
    "S1": ["firm_h", "firm_rel_h", "firm_next4", "open_jobs", "book_cover", "fam_backlog"],
    "S2": ["fam_s13", "fam_s52", "fam_trend", "fam_ly", "item_share_fam", "pf_builds_13", "pf_booked_h"],
    "S3": ["short_w13", "short_active_w13", "held_jobs_13", "last_short_wks", "censored_s4"],
    # S4a adds the lifecycle and installed-base features on the 52-week frame; S4b adds no
    # features: it lowers the minimum history to 13 weeks (nullable 52-week features) and
    # gives parts under 13 weeks the class-and-family prior
    "S4a": ["age_wks", "hist_wks", "n_parents", "bom_added_13", "bom_removed_13", "superseded",
            "supersede_pending", "successor_age_wks", "ib_units", "ib_age_wtd", "ib_growth_52"],
    "S4b": [],
    "S5": ["lt_roll8", "lt_sd", "lt_trend", "lt_roll26w", "lt_pooled26w", "lt_source_code",
           "ontime_13", "partial_13", "po_past_promise"],
    "S6": ["wd_h", "shutdown_in_h", "wks_to_qtr_end", "wks_since_spike"],
}
RUNGS = ["reference", "S1", "S2", "S3", "S4a", "S4b", "S5", "S6"]
# features that may be missing (trees split on missing; the linear model sees zero)
NULLABLE = {"book_cover", "fam_trend", "item_share_fam", "last_short_wks", "age_wks", "successor_age_wks",
            "ib_growth_52", "lt_sd", "lt_trend", "lt_roll26w", "lt_pooled26w", "ontime_13", "partial_13",
            "wks_since_spike", "lt_source_code", "lt_roll8"}
# features S4 sets missing when the item has less than a year of history
NULLABLE_52 = ["s52", "nz52", "ly", "fam_ly"]
# features that look into the order book ahead of the origin (for the shuffle test)
FORWARD_LOOKING = ["firm_h", "firm_rel_h", "firm_next4", "open_jobs", "book_cover", "fam_backlog", "pf_booked_h"]
LT_SOURCE_CODE = {"item": 0, "supplier": 1, "roll8": 2, "master": 3}


def features_for(rung: str) -> list:
    """The cumulative feature list of a rung."""
    feats = list(REFERENCE_FEATS)
    for g in RUNGS[1:RUNGS.index(rung) + 1]:
        feats += GROUPS[g]
    return feats


def group_of(feature: str) -> str:
    for g, cols in GROUPS.items():
        if feature in cols:
            return g
    return "reference"


# ── shared helpers ──────────────────────────────────────────────────────────
def week_index(weeks: pd.DatetimeIndex) -> dict:
    return {pd.Timestamp(w): i for i, w in enumerate(weeks)}


def to_week_idx(dates, weeks: pd.DatetimeIndex) -> np.ndarray:
    """Index of the Monday week containing each date (NaN for missing dates). Dates
    before the first week map below zero; after the last, beyond T - 1."""
    d = pd.to_datetime(pd.Series(dates))
    days = (d - weeks[0]).dt.days
    return np.where(d.isna(), np.nan, np.floor(days / 7.0))


def window_sum(arr: np.ndarray, t: np.ndarray, k: int) -> np.ndarray:
    """Sum of arr[t - k : t] per row (arr is items x T, rows give t); windows clipped at 0."""
    cs = np.concatenate([np.zeros((arr.shape[0], 1)), np.cumsum(arr, axis=1)], axis=1)
    return cs, np.maximum(t - k, 0)


def gather_window(cs: np.ndarray, ii: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Sum over [lo, hi) from a cumulative-sum matrix, rows ii."""
    T1 = cs.shape[1] - 1
    lo = np.clip(lo, 0, T1).astype(int); hi = np.clip(hi, 0, T1).astype(int)
    return cs[ii, hi] - cs[ii, lo]


def cumsum_rows(arr: np.ndarray) -> np.ndarray:
    return np.concatenate([np.zeros((arr.shape[0], 1)), np.cumsum(arr, axis=1)], axis=1)


def item_matrix(df: pd.DataFrame, items: list, weeks: pd.DatetimeIndex, value: str,
                item_col: str = "canonical_item_number", week_col: str = "week", fill=0.0) -> np.ndarray:
    """items x weeks matrix of a weekly item table."""
    w = df.pivot_table(index=item_col, columns=week_col, values=value, aggfunc="sum")
    w.columns = pd.to_datetime(w.columns)
    return w.reindex(index=items, columns=weeks).astype(float).fillna(fill).to_numpy()


# ── base frame ──────────────────────────────────────────────────────────────
def extra_history_rows(weekly: pd.DataFrame, attrs: pd.DataFrame, weeks: pd.DatetimeIndex,
                       min_t: int = 13, max_t: int = 52) -> pd.DataFrame:
    """Rows for origins min_t <= t < max_t, with the reference features computed on the
    history available. Windows that would reach before the first week are left missing
    where a full window is needed (s52, nz52, ly); shorter windows are clipped."""
    from .demand_model import SEG_CODE, ABC_CODE
    wide = weekly.pivot(index="canonical", columns="week", values="consumption").reindex(columns=weeks).fillna(0)
    cls_code = {c: i for i, c in enumerate(sorted(attrs["item_class"].unique()))}
    T = len(weeks)
    woy = np.array([w.isocalendar()[1] for w in weeks]); mon = np.array([w.month for w in weeks])
    rows = []
    for item, sr in wide.iterrows():
        if item not in attrs.index:
            continue
        a = attrs.loc[item]
        s = sr.to_numpy(float); cs = np.concatenate([[0.0], np.cumsum(s)]); nz = np.concatenate([[0], np.cumsum(s > 0)])
        h = max(1, int(round(float(a["corrected_lead_days"]) / 7.0)))
        last_nz = -1; since = np.zeros(T)
        for t in range(T):
            since[t] = t - last_nz if last_nz >= 0 else t + 1
            if s[t] > 0:
                last_nz = t
        t_idx = np.arange(min_t, max_t)
        win = lambda k: cs[t_idx] - cs[np.maximum(t_idx - k, 0)]
        s4, s13, s26 = win(4), win(13), win(26)
        sq13 = np.array([s[max(0, t - 13):t].std() for t in t_idx])
        tgt = np.array([s[t:t + h].sum() if t + h <= T else np.nan for t in t_idx])
        rows.append(pd.DataFrame({
            "item": item, "t": t_idx, "week": weeks[t_idx], "h": h, "target": tgt,
            "s4": s4, "s13": s13, "s26": s26, "s52": np.nan,
            "nz13": nz[t_idx] - nz[np.maximum(t_idx - 13, 0)], "nz52": np.nan,
            "since_nz": since[t_idx], "cv13": np.where(s13 > 0, sq13 / np.maximum(s13 / 13, 1e-9), 0.0),
            "trend": s4 / 4 - s13 / 13, "ly": np.nan, "mean_all": cs[t_idx] / t_idx,
            "woy": woy[t_idx], "month": mon[t_idx], "std_cost": a["standard_cost"],
            "lead": a["corrected_lead_days"], "annual": a["annual_consumption"],
            "seg_code": SEG_CODE.get(a["segment"], 0), "abc_code": ABC_CODE.get(a["abc"], 2),
            "cls_code": cls_code.get(a["item_class"], 0), "segment": a["segment"], "abc": a["abc"]}))
    return pd.concat(rows, ignore_index=True)


# ── S1 order book ───────────────────────────────────────────────────────────
def firm_features(frame: pd.DataFrame, job_req: pd.DataFrame, weeks: pd.DatetimeIndex) -> pd.DataFrame:
    """firm_h, firm_rel_h, firm_next4, open_jobs per row: requirements booked on or before the
    origin, not completed before it (or open), required in [origin, origin + h) (firm_h; of
    which released on or before the origin: firm_rel_h) or in the four weeks after
    (firm_next4)."""
    out = {c: np.zeros(len(frame)) for c in ["firm_h", "firm_rel_h", "firm_next4", "open_jobs"]}
    jr = job_req.copy()
    for c in ["booked_date", "release_date", "required_date", "completed_date"]:
        jr[c] = pd.to_datetime(jr[c])
    by_item = {k: g for k, g in jr.groupby("canonical_item_number")}
    for item, rows in frame.groupby("item").groups.items():
        g = by_item.get(item)
        if g is None:
            continue
        idx = np.asarray(rows)
        o = frame.loc[idx, "week"].to_numpy(dtype="datetime64[ns]")[:, None]            # rows x 1
        h = frame.loc[idx, "h"].to_numpy()[:, None]
        bk = g["booked_date"].to_numpy(dtype="datetime64[ns]")[None, :]
        rl = g["release_date"].to_numpy(dtype="datetime64[ns]")[None, :]
        rq = g["required_date"].to_numpy(dtype="datetime64[ns]")[None, :]
        cp = g["completed_date"].to_numpy(dtype="datetime64[ns]")[None, :]
        q = g["req_qty"].to_numpy(float)[None, :]
        in_book = (bk <= o) & (np.isnat(cp) | (cp >= o))
        end_h = o + (7 * h).astype("timedelta64[D]")
        end_n = end_h + np.timedelta64(28, "D")
        horizon = in_book & (rq >= o) & (rq < end_h)
        nxt = in_book & (rq >= end_h) & (rq < end_n)
        # point in time: no requirement booked after the origin contributes
        assert not np.any(horizon & (bk > o)) and not np.any(nxt & (bk > o))
        out["firm_h"][idx] = (q * horizon).sum(axis=1)
        out["firm_rel_h"][idx] = (q * (horizon & (rl <= o))).sum(axis=1)
        out["firm_next4"][idx] = (q * nxt).sum(axis=1)
        out["open_jobs"][idx] = horizon.sum(axis=1)
    return pd.DataFrame(out, index=frame.index)


def item_family_sets(job_req: pd.DataFrame) -> dict:
    """{item: {product family: first booking date}}, the families whose bills an item has
    been drawn through, known from the first booking that drew it."""
    jr = job_req.copy(); jr["booked_date"] = pd.to_datetime(jr["booked_date"])
    first = jr.groupby(["canonical_item_number", "product_family"])["booked_date"].min()
    out = {}
    for (item, fam), d in first.items():
        out.setdefault(item, {})[fam] = d
    return out


def family_book_features(frame: pd.DataFrame, fam_sets: dict, pf_weekly: pd.DataFrame,
                         job_req: pd.DataFrame, weeks: pd.DatetimeIndex) -> pd.DataFrame:
    """fam_backlog (S1): units of parent products booked and not completed at the origin,
    over the families whose bills draw the item; pf_builds_13 and pf_booked_h (S2): parent
    family units completed in the 13 weeks before the origin, and booked, open and required
    inside the horizon."""
    fams = sorted(pf_weekly["product_family"].unique())
    open_m = item_matrix(pf_weekly, fams, weeks, "units_booked_open", item_col="product_family")
    done_m = item_matrix(pf_weekly, fams, weeks, "units_completed", item_col="product_family")
    done_cs = cumsum_rows(done_m)
    fi = {f: i for i, f in enumerate(fams)}
    # order-level book for pf_booked_h
    orders = job_req.drop_duplicates("order_id")[["order_id", "product_family", "qty_ordered", "booked_date",
                                                   "completed_date", "required_date"]].copy()
    for c in ["booked_date", "completed_date", "required_date"]:
        orders[c] = pd.to_datetime(orders[c])
    t = frame["t"].to_numpy(); o = frame["week"].to_numpy(dtype="datetime64[ns]"); h = frame["h"].to_numpy()
    backlog = np.zeros(len(frame)); builds = np.zeros(len(frame)); booked_h = np.zeros(len(frame))
    cache = {}
    for item, rows in frame.groupby("item").groups.items():
        idx = np.asarray(rows)
        fs = fam_sets.get(item, {})
        for f, first in fs.items():
            known = o[idx] >= np.datetime64(first)
            j = fi.get(f)
            if j is None:
                continue
            backlog[idx] += np.where(known, open_m[j, t[idx]], 0.0)
            builds[idx] += np.where(known, done_cs[j, t[idx]] - done_cs[j, np.maximum(t[idx] - 13, 0)], 0.0)
            hh = int(h[idx][0])
            key = (f, hh)
            if key not in cache:
                g = orders[orders["product_family"] == f]
                bk = g["booked_date"].to_numpy(dtype="datetime64[ns]")[None, :]
                cp = g["completed_date"].to_numpy(dtype="datetime64[ns]")[None, :]
                rq = g["required_date"].to_numpy(dtype="datetime64[ns]")[None, :]
                q = g["qty_ordered"].to_numpy(float)[None, :]
                ow = weeks.to_numpy(dtype="datetime64[ns]")[:, None]
                m = (bk <= ow) & (np.isnat(cp) | (cp >= ow)) & (rq >= ow) & (rq < ow + np.timedelta64(7 * hh, "D"))
                cache[key] = (q * m).sum(axis=1)
            booked_h[idx] += np.where(known, cache[key][t[idx]], 0.0)
    return pd.DataFrame({"fam_backlog": backlog, "pf_builds_13": builds, "pf_booked_h": booked_h}, index=frame.index)


# ── S2 families ─────────────────────────────────────────────────────────────
def family_usage_features(frame: pd.DataFrame, item_family: pd.DataFrame, fam_usage: pd.DataFrame,
                          weeks: pd.DatetimeIndex) -> pd.DataFrame:
    fams = sorted(fam_usage["family"].unique())
    m = item_matrix(fam_usage, fams, weeks, "family_usage", item_col="family")
    cs = cumsum_rows(m)
    fi = {f: i for i, f in enumerate(fams)}
    fam_of = item_family.set_index("canonical_item_number")["family"].to_dict()
    j = frame["item"].map(lambda i: fi.get(fam_of.get(i), -1)).to_numpy()
    t = frame["t"].to_numpy(); h = frame["h"].to_numpy()
    ok = j >= 0; jj = np.where(ok, j, 0)
    s = lambda lo, hi: np.where(ok, gather_window(cs, jj, lo, hi), np.nan)
    f4, f13, f52 = s(t - 4, t), s(t - 13, t), s(t - 52, t)
    ly = np.where(t >= 52, s(t - 52, t - 52 + h), np.nan)
    trend = np.where(f13 > 0, (f4 / 4) / np.maximum(f13 / 13, 1e-9), np.nan)
    share = np.where(f52 > 0, frame["s52"].to_numpy(float) / np.maximum(f52, 1e-9), np.nan)
    return pd.DataFrame({"fam_s13": f13, "fam_s52": f52, "fam_trend": trend, "fam_ly": ly,
                         "item_share_fam": share}, index=frame.index)


# ── S3 censoring ────────────────────────────────────────────────────────────
def shortage_features(frame: pd.DataFrame, shortage: pd.DataFrame, items: list, weeks: pd.DatetimeIndex) -> pd.DataFrame:
    """Counts over the weeks before the origin only (weeks t - k .. t - 1)."""
    ii = frame["item"].map({it: k for k, it in enumerate(items)}).to_numpy()
    t = frame["t"].to_numpy()
    sh = shortage.copy(); sh["short_week"] = sh["short_week"].astype(float); sh["short_active_week"] = sh["short_active_week"].astype(float)
    S = item_matrix(sh, items, weeks, "short_week"); A = item_matrix(sh, items, weeks, "short_active_week")
    Hm = item_matrix(sh, items, weeks, "held_jobs")
    cS, cA, cH = cumsum_rows(S), cumsum_rows(A), cumsum_rows(Hm)
    last = np.full(S.shape, np.nan)
    for k in range(S.shape[0]):
        lw = np.nan
        for w in range(S.shape[1]):
            last[k, w] = lw                      # last short week strictly before w
            if S[k, w] > 0:
                lw = w
    lsw = last[ii, t]
    return pd.DataFrame({
        "short_w13": gather_window(cS, ii, t - 13, t),
        "short_active_w13": gather_window(cA, ii, t - 13, t),
        "held_jobs_13": gather_window(cH, ii, t - 13, t),
        "last_short_wks": np.where(np.isnan(lsw), np.nan, t - lsw),
        "censored_s4": (gather_window(cS, ii, t - 4, t) > 0).astype(float),
    }, index=frame.index), S


def short_in_target_window(frame: pd.DataFrame, S: np.ndarray, items: list) -> np.ndarray:
    """Whether the target window [t, t + h) holds a short week (for the S3 reweighting)."""
    ii = frame["item"].map({it: k for k, it in enumerate(items)}).to_numpy()
    t = frame["t"].to_numpy(); h = frame["h"].to_numpy()
    return gather_window(cumsum_rows(S), ii, t, t + h) > 0


def backorder_shift(frame: pd.DataFrame, backorders: pd.DataFrame, items: list, weeks: pd.DatetimeIndex) -> np.ndarray:
    """Units of service backorders to move into the target window from the week they shipped
    to the week they were ordered: ordered in [t, t + h) minus shipped in [t, t + h)."""
    ii = frame["item"].map({it: k for k, it in enumerate(items)}).to_numpy()
    t = frame["t"].to_numpy(); h = frame["h"].to_numpy()
    bo = backorders.copy()
    bo["order_week"] = pd.to_datetime(bo["order_date"]) - pd.to_timedelta(pd.to_datetime(bo["order_date"]).dt.weekday, unit="D")
    bo["ship_week"] = pd.to_datetime(bo["ship_date"]) - pd.to_timedelta(pd.to_datetime(bo["ship_date"]).dt.weekday, unit="D")
    O = cumsum_rows(item_matrix(bo, items, weeks, "qty", week_col="order_week"))
    Sh = cumsum_rows(item_matrix(bo, items, weeks, "qty", week_col="ship_week"))
    return gather_window(O, ii, t, t + h) - gather_window(Sh, ii, t, t + h)


# ── S4 lifecycle ────────────────────────────────────────────────────────────
def lifecycle_features(frame: pd.DataFrame, lifecycle: pd.DataFrame, bom: pd.DataFrame,
                       ib_item: pd.DataFrame, weeks: pd.DatetimeIndex) -> pd.DataFrame:
    lc = lifecycle.set_index("canonical_item_number")
    o = frame["week"]
    first = frame["item"].map(pd.to_datetime(lc["first_use_date"])); created = frame["item"].map(pd.to_datetime(lc["created_date"]))
    hist = np.where(first.notna() & (first <= o), (o - first).dt.days / 7.0, 0.0)
    age_from = first.where(first.notna() & (first <= o), created)
    age = np.where(age_from.notna() & (age_from <= o), (o - age_from).dt.days / 7.0, np.nan)
    # bill membership at the origin and changes in the 13 weeks before it
    b = bom[bom["component_type"] == "purchased"].copy()
    # an open interval ends in 9999, past the datetime range; any date past the history serves
    cap = lambda s: pd.to_datetime(s.astype(str).where(s.astype(str) < "2200-01-01", "2200-01-01"))
    b["valid_from"] = cap(b["valid_from"]); b["valid_to"] = cap(b["valid_to"])
    n_par = np.zeros(len(frame)); added = np.zeros(len(frame)); removed = np.zeros(len(frame))
    by = {k: g for k, g in b.groupby("component")}
    for item, rows in frame.groupby("item").groups.items():
        g = by.get(item)
        if g is None:
            continue
        idx = np.asarray(rows)
        ov = frame.loc[idx, "week"].to_numpy(dtype="datetime64[ns]")[:, None]
        vf = g["valid_from"].to_numpy(dtype="datetime64[ns]")[None, :]; vt = g["valid_to"].to_numpy(dtype="datetime64[ns]")[None, :]
        lo = ov - np.timedelta64(91, "D")
        n_par[idx] = ((vf <= ov) & (vt > ov)).sum(axis=1)
        added[idx] = ((vf > lo) & (vf <= ov)).sum(axis=1)
        removed[idx] = ((vt > lo) & (vt <= ov)).sum(axis=1)
    # part supersession, on both the old part and its successor
    pairs = lc[lc["superseded_by"].notna()][["superseded_by", "supersede_switch_date"]].copy()
    pairs["successor_created"] = pairs["superseded_by"].map(pd.to_datetime(lc["created_date"]))
    role = {}
    for pred, r in pairs.iterrows():
        sw = pd.to_datetime(r["supersede_switch_date"]); cr = pd.to_datetime(r["successor_created"])
        role[pred] = ("old", sw, cr); role[r["superseded_by"]] = ("new", sw, cr)
    sup = np.zeros(len(frame)); pend = np.zeros(len(frame)); sage = np.full(len(frame), np.nan)
    for k, (item, ow) in enumerate(zip(frame["item"], o)):
        r = role.get(item)
        if r is None:
            continue
        kind, sw, cr = r
        switched = pd.notna(sw) and sw <= ow
        sup[k] = float(switched)
        pend[k] = float(pd.notna(cr) and cr <= ow and not switched)
        if kind == "new" and switched:
            sage[k] = (ow - sw).days / 7.0
    # installed base behind the part, as of the month before the origin's month
    ib = ib_item.copy(); ib["month"] = pd.to_datetime(ib["month"])
    prev = (o.dt.to_period("M") - 1).dt.to_timestamp()
    prev13 = (o.dt.to_period("M") - 13).dt.to_timestamp()
    key = ib.set_index(["canonical_item_number", "month"])
    get = lambda col, m: key[col].reindex(pd.MultiIndex.from_arrays([frame["item"], m])).to_numpy()
    units, awb, awb13 = get("units_carried", prev), get("age_weighted_base", prev), get("age_weighted_base", prev13)
    growth = np.where(np.nan_to_num(awb13) > 0, np.nan_to_num(awb) / np.where(np.nan_to_num(awb13) > 0, awb13, 1) - 1, np.nan)
    return pd.DataFrame({"age_wks": age, "hist_wks": hist, "n_parents": n_par, "bom_added_13": added,
                         "bom_removed_13": removed, "superseded": sup, "supersede_pending": pend,
                         "successor_age_wks": sage, "ib_units": np.nan_to_num(units), "ib_age_wtd": np.nan_to_num(awb),
                         "ib_growth_52": growth}, index=frame.index)


# ── S5 supply ───────────────────────────────────────────────────────────────
def leadtime_features(frame: pd.DataFrame, lt_item: pd.DataFrame) -> pd.DataFrame:
    lt = lt_item.copy(); lt["week"] = pd.to_datetime(lt["week"])
    # point in time: the statistics for a week use receipts dated before it
    known = lt["last_receipt_date"].notna()
    assert (pd.to_datetime(lt.loc[known, "last_receipt_date"]) < lt.loc[known, "week"]).all()
    lt["lt_source_code"] = lt["lt_source"].map(LT_SOURCE_CODE)
    cols = ["lt_roll8", "lt_sd", "lt_trend", "lt_roll26w", "lt_pooled26w", "lt_source_code",
            "ontime_13", "partial_13", "po_past_promise"]
    j = lt.set_index(["canonical_item_number", "week"])[cols]
    out = j.reindex(pd.MultiIndex.from_arrays([frame["item"], frame["week"]]))
    out.index = frame.index
    return out.astype(float)


# ── S6 calendar ─────────────────────────────────────────────────────────────
def calendar_features(frame: pd.DataFrame, dim_week: pd.DataFrame, weekly_wide: np.ndarray,
                      items: list, weeks: pd.DatetimeIndex) -> pd.DataFrame:
    dw = dim_week.copy(); dw["week"] = pd.to_datetime(dw["week"])
    dw = dw.set_index("week").reindex(weeks)
    wd = np.concatenate([[0.0], np.cumsum(dw["working_days"].fillna(5).to_numpy(float))])
    sd = np.concatenate([[0.0], np.cumsum(dw["is_shutdown"].fillna(False).astype(float).to_numpy())])
    t = frame["t"].to_numpy(); h = frame["h"].to_numpy(); T = len(weeks)
    hi = np.minimum(t + h, T)
    # time since the item's last spike: a week above 3x the median of the 13 weeks before it
    last = np.full(weekly_wide.shape, np.nan)
    for k in range(weekly_wide.shape[0]):
        s = weekly_wide[k]; lw = np.nan
        for w in range(len(s)):
            last[k, w] = lw
            if w >= 13 and s[w] > 0 and s[w] > 3 * np.median(s[w - 13:w]):
                lw = w
    ii = frame["item"].map({it: k for k, it in enumerate(items)}).to_numpy()
    ls = last[ii, t]
    return pd.DataFrame({"wd_h": wd[hi] - wd[t], "shutdown_in_h": (sd[hi] - sd[t] > 0).astype(float),
                         "wks_to_qtr_end": dw["weeks_to_quarter_end"].to_numpy(float)[t],
                         "wks_since_spike": np.where(np.isnan(ls), np.nan, t - ls)}, index=frame.index)


# ── simple methods ──────────────────────────────────────────────────────────
def simple_methods(frame: pd.DataFrame, unscheduled_cs: np.ndarray, items: list) -> pd.DataFrame:
    """The four reference methods scaled to the horizon, and the same four on the demand jobs
    do not carry (usage less backflush), each added to the order book (u_* columns hold the
    unscheduled part; firm_ma13 is firm_h plus its 13-week rate)."""
    ii = frame["item"].map({it: k for k, it in enumerate(items)}).to_numpy()
    t = frame["t"].to_numpy(); h = frame["h"].to_numpy()
    u = lambda lo, hi: gather_window(unscheduled_cs, ii, lo, hi)
    u_ly = np.where(t >= 52, u(t - 52, t - 52 + h), np.nan)
    return pd.DataFrame({"ma4": frame["s4"] / 4 * h, "ma13": frame["s13"] / 13 * h, "ma52": frame["s52"] / 52 * h,
                         "snaive": frame["ly"],
                         "u_ma4": u(t - 4, t) / 4 * h, "u_ma13": u(t - 13, t) / 13 * h, "u_ma52": u(t - 52, t) / 52 * h,
                         "u_snaive": u_ly,
                         "firm_ma13": frame["firm_h"] + u(t - 13, t) / 13 * h}, index=frame.index)
