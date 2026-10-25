"""Demand signals the shop's records carry about future and censored demand.

  Requirement dates   every job carries the date its material is required (the
                      Monday of its due week), known from the day it is booked
  Supersession        engineering replaces a purchased part with a successor
                      part number; from the effective date the bills call the
                      successor, and the old part keeps only its service demand
  Installed base      service demand on a part that sits on product bills
                      follows the fielded units of those products, weighted by
                      their age
  Plant calendar      two shutdown weeks a year: no completions, floor issues or
                      service shipments post in them
  Service holds       a service line whose part is out of stock waits until the
                      stock returns, so its ship date records the backorder

Each mechanism draws its decisions from its own random stream.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .. import config as C


# ── Plant calendar ──────────────────────────────────────────────────────────
_SHUT = set(C.shutdown_weeks(C.START_DATE, C.END_DATE + timedelta(days=14)))


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def in_shutdown(d: date) -> bool:
    return _monday(d) in _SHUT


def next_working_day(d: date) -> date:
    """d if it is a plant working day, else the first working day after it."""
    while d.weekday() >= 5 or in_shutdown(d):
        d += timedelta(days=1)
    return d


def prev_working_day(d: date) -> date:
    while d.weekday() >= 5 or in_shutdown(d):
        d -= timedelta(days=1)
    return d


def shutdown_shift_jobs(production_orders: pd.DataFrame) -> pd.DataFrame:
    """Work due to finish in a shutdown week finishes the working day before it or
    the first working day after it. A job pushed past the end of the history is
    still open."""
    rng = np.random.default_rng(C.SEED_SHUTDOWN)
    df = production_orders.copy()
    for i in df.index[df["completed_date"].notna()]:
        cd = date.fromisoformat(df.at[i, "completed_date"])
        if not in_shutdown(cd):
            continue
        if rng.random() < C.SHUTDOWN_PULL_IN_SHARE:
            new = prev_working_day(_monday(cd) - timedelta(days=1))
        else:
            new = next_working_day(_monday(cd) + timedelta(days=7))
        if new > C.END_DATE:
            df.at[i, "completed_date"] = None
            df.at[i, "qty_completed"] = 0
            df.at[i, "status"] = "OPEN"
        else:
            df.at[i, "completed_date"] = new.isoformat()
    return df


def shutdown_shift_service(service_orders: pd.DataFrame) -> pd.DataFrame:
    """Shipments due in a shutdown week go out on the first working day after it;
    the order date moves with the shipment, so the order-to-ship time is unchanged.
    A shipment pushed past the end of the history is dropped from the extract."""
    df = service_orders.copy()
    ship = pd.to_datetime(df["ship_date"]).dt.date
    order = pd.to_datetime(df["order_date"]).dt.date
    new_ship, new_order = [], []
    for s, o in zip(ship, order):
        if in_shutdown(s):
            ns = next_working_day(s)
            new_ship.append(ns); new_order.append(o + (ns - s))
        else:
            new_ship.append(s); new_order.append(o)
    df["ship_date"] = [d.isoformat() for d in new_ship]
    df["order_date"] = [d.isoformat() for d in new_order]
    return df[pd.to_datetime(df["ship_date"]).dt.date <= C.END_DATE].reset_index(drop=True)


# ── Requirement dates ───────────────────────────────────────────────────────
def add_required_dates(production_orders: pd.DataFrame) -> pd.DataFrame:
    df = production_orders.copy()
    req = [C.required_date(date.fromisoformat(d)).isoformat() for d in df["due_date"]]
    df.insert(df.columns.get_loc("due_date") + 1, "required_date", req)
    return df


# ── Supersession ────────────────────────────────────────────────────────────
def m4_selection(plan: pd.DataFrame, annual_by_item: dict) -> set:
    """The duplicate-record clusters, chosen exactly as the item master chooses them."""
    live = plan.copy()
    live["annual"] = live["item_id"].map(annual_by_item).fillna(0.0)
    pool = live[live["item_class"].isin(C.M4_CLUSTER_CLASSES)]
    n_m4 = int(round(len(live) * C.M4_LIVE_SHARE))
    return set(pool.sort_values("annual", ascending=False)
                   .head(n_m4 * 3).sample(n=min(n_m4, len(pool)), random_state=C.RANDOM_SEED)["item_id"])


def choose_supersessions(plan: pd.DataFrame, bom_true: pd.DataFrame, exclude: set) -> pd.DataFrame:
    """Pick the superseded parts and their successors.
    Returns pred_id, succ_id, effective_date, created_date, cost_ratio."""
    rng = np.random.default_rng(C.SEED_SUPERSEDE)
    cls = plan.set_index("item_id")["item_class"].to_dict()
    comps = sorted(set(bom_true.loc[bom_true["component_type"] == "purchased", "component_item"].astype(int)))
    cands = [c for c in comps if cls.get(c) in C.SUPERSEDE_CLASSES and c not in exclude]
    n = min(len(cands), int(round(C.N_LIVE_ITEMS * C.SUPERSEDE_SHARE)))
    preds = sorted(int(c) for c in rng.choice(cands, size=n, replace=False))
    lo, hi = C.SUPERSEDE_WINDOW
    span = (hi - lo).days
    rows = []
    next_id = int(plan["item_id"].max()) + 1
    for k, p in enumerate(preds):
        eff = _monday(lo + timedelta(days=int(rng.integers(0, span + 1))))
        if eff < lo:
            eff += timedelta(days=7)
        created = eff - timedelta(days=int(rng.integers(C.SUPERSEDE_CREATE_LEAD_DAYS[0],
                                                        C.SUPERSEDE_CREATE_LEAD_DAYS[1] + 1)))
        rows.append({"pred_id": p, "succ_id": next_id + k, "effective_date": eff, "created_date": created,
                     "cost_ratio": float(rng.uniform(*C.SUPERSEDE_COST_RATIO))})
    return pd.DataFrame(rows)


def successor_plan_rows(plan: pd.DataFrame, sup: pd.DataFrame) -> pd.DataFrame:
    """A successor inherits its predecessor's demand behavior, class, family and
    supplier lead time; its cost is the revision's."""
    base = plan.set_index("item_id")
    out = []
    for r in sup.itertuples(index=False):
        row = base.loc[r.pred_id].to_dict()
        row["item_id"] = int(r.succ_id)
        row["unit_cost"] = round(float(row["unit_cost"]) * r.cost_ratio, 2)
        out.append(row)
    return pd.DataFrame(out)[plan.columns]


def transfer_monthly(df: pd.DataFrame, sup: pd.DataFrame, qty_col: str = "qty") -> pd.DataFrame:
    """Monthly series: the months after the effective month move from the
    predecessor to the successor (the effective month stays with the predecessor)."""
    if sup is None or not len(sup):
        return df
    df = df.copy()
    for r in sup.itertuples(index=False):
        m0 = date(r.effective_date.year, r.effective_date.month, 1)
        sel = (df["item_id"] == r.pred_id) & (pd.to_datetime(df["month"]).dt.date > m0)
        df.loc[sel, "item_id"] = int(r.succ_id)
    return df.groupby(["item_id", "month"], as_index=False)[qty_col].sum()


def supersession_map(sup: pd.DataFrame) -> dict:
    return {int(r.pred_id): (int(r.succ_id), r.effective_date) for r in sup.itertuples(index=False)} if sup is not None else {}


def add_successor_records(item_master, item_meta, sup, plan):
    """Append the successor part numbers to the item master and record the
    replacement on each predecessor (superseded_by). The successor is set up from
    its predecessor's record: same class, unit, supplier, lead time and planning
    parameters, at the revision's cost."""
    from .item_master import _item_number
    rng = np.random.default_rng([C.SEED_SUPERSEDE, 1])
    im = item_master.copy()
    im["superseded_by"] = None
    num_of = {m["item_id"]: n for n, m in item_meta.items() if not m["dead"] and m["member"] == 0}
    cls_of = plan.set_index("item_id")["item_class"].to_dict()
    meta = dict(item_meta)
    rows = []
    for r in sup.itertuples(index=False):
        pn = num_of[int(r.pred_id)]
        sn = _item_number(int(r.succ_id), cls_of[int(r.pred_id)])
        p = im.loc[im["item_number"] == pn].iloc[0].to_dict()
        im.loc[im["item_number"] == pn, "superseded_by"] = sn
        row = dict(p)
        row.update({"item_number": sn, "description": f"{p['description']} REV {'BCD'[int(rng.integers(0, 3))]}",
                    "standard_cost": (round(float(p["standard_cost"]) * r.cost_ratio, 2)
                                      if pd.notna(p["standard_cost"]) else np.nan),
                    "created_by": rng.choice(C.OFFICE_USERS), "created_date": r.created_date.isoformat(),
                    "last_updated": r.created_date.isoformat(), "superseded_by": None})
        rows.append(row)
        m = dict(item_meta[pn]); m.update({"item_id": int(r.succ_id), "member": 0, "successor_of": pn})
        meta[sn] = m
        meta[pn] = dict(item_meta[pn]); meta[pn]["superseded_on"] = r.effective_date; meta[pn]["successor_num"] = sn
    im = pd.concat([im, pd.DataFrame(rows)], ignore_index=True)
    return im, meta


def bom_replacement_rows(bom_ds, sup, item_meta):
    """Bill rows carry effectivity. A superseded component is replaced on use-up:
    its rows and the successor's replacement rows carry effectivity USE_UP and the
    date engineering planned; the actual switch date is filled in when the old
    part's stock runs out (apply_switches)."""
    bom = bom_ds.copy()
    bom["effectivity"] = "DATE"
    bom["planned_date"] = None
    bom["expiry_date"] = None
    bom["replaces_item"] = None
    num_of = {m["item_id"]: n for n, m in item_meta.items() if not m["dead"] and m["member"] == 0}
    add = []
    for r in sup.itertuples(index=False):
        pn, sn = num_of[int(r.pred_id)], num_of[int(r.succ_id)]
        sel = bom["component_item"] == pn
        bom.loc[sel, "effectivity"] = "USE_UP"
        bom.loc[sel, "planned_date"] = r.effective_date.isoformat()
        for row in bom[sel].to_dict("records"):
            row.update({"component_item": sn, "effective_date": None, "planned_date": r.effective_date.isoformat(),
                        "effectivity": "USE_UP", "expiry_date": None, "replaces_item": pn})
            add.append(row)
    return pd.concat([bom, pd.DataFrame(add)], ignore_index=True) if add else bom


def apply_switches(bom_ds, switches):
    """The old part's rows expire on the day its stock ran out; the successor's start then."""
    bom = bom_ds.copy()
    for s in switches:
        if s["switch"] is None:
            continue
        d = s["switch"].isoformat()
        bom.loc[bom["component_item"] == s["pred_number"], "expiry_date"] = d
        bom.loc[(bom["component_item"] == s["succ_number"]) & (bom["replaces_item"] == s["pred_number"]), "effective_date"] = d
    return bom


def relabel_after_switch(events, service_orders, switches, item_meta):
    """Requirements dated on or after the switch post to the successor."""
    ev, so = events.copy(), service_orders.copy()
    for s in switches:
        if s["switch"] is None:
            continue
        sid = int(item_meta[s["succ_number"]]["item_id"])
        sel = (ev["item_number"] == s["pred_number"]) & (pd.to_datetime(ev["date"]).dt.date >= s["switch"])
        ev.loc[sel, "item_number"] = s["succ_number"]; ev.loc[sel, "item_id"] = sid
        sel = (so["item_number"] == s["pred_number"]) & (pd.to_datetime(so["ship_date"]).dt.date >= s["switch"])
        so.loc[sel, "item_number"] = s["succ_number"]
    return ev, so


# ── Installed base ──────────────────────────────────────────────────────────
def _age_weight(age_months: np.ndarray) -> np.ndarray:
    w = np.zeros_like(age_months, dtype=float)
    for lo, hi, val in C.INSTALLED_BASE_AGE_PROFILE:
        sel = (age_months >= lo) & ((age_months < hi) if hi is not None else True)
        w[sel] = val
    return w


def installed_base(builds: pd.DataFrame, products: pd.DataFrame, bom_true: pd.DataFrame, sup: pd.DataFrame):
    """Age-weighted fielded units carrying each purchased part, per month.
    Returns (ib, ib_units): DataFrames item_id x month, the age-weighted base and
    the plain unit count. A superseded part stops entering new units after its
    effective date; its successor starts then."""
    from .bom import effective_component_map
    months = C.month_starts()
    M = len(months)
    pmap = effective_component_map(bom_true)
    base_build = products.set_index("product_number")["base_build"].to_dict()
    wide = (builds.pivot(index="product_number", columns="month", values="completed")
                  .reindex(columns=months).fillna(0.0))
    opening = {p: C.INSTALLED_BASE_OPENING_YEARS * 12.0 * base_build.get(p, 0.0) for p in wide.index}
    # per product, per month: age-weighted units and units in the field
    age = np.arange(M)[:, None] - np.arange(M)[None, :]          # [month, build month]
    w = np.where(age >= 0, _age_weight(np.maximum(age, 0)), 0.0)
    fielded = (age >= 0).astype(float)
    smap = supersession_map(sup)
    ib, units = {}, {}
    for p, comps in pmap.items():
        b = wide.loc[p].to_numpy(float) if p in wide.index else np.zeros(M)
        for c, qper in comps.items():
            for item, mask in _carrier_masks(c, smap, months):
                bb = b * mask
                op = opening.get(p, 0.0) if item == c else 0.0
                ib.setdefault(item, np.zeros(M))
                units.setdefault(item, np.zeros(M))
                ib[item] += qper * (w @ bb + op)
                units[item] += qper * (fielded @ bb + op)
    def _long(d):
        return pd.DataFrame([(i, m, float(v)) for i, arr in d.items() for m, v in zip(months, arr)],
                            columns=["item_id", "month", "value"])
    return _long(ib), _long(units)


def _carrier_masks(c, smap, months):
    """Which build months put part c (or its successor) into the field."""
    if c not in smap:
        return [(c, np.ones(len(months)))]
    succ, eff = smap[c]
    m0 = date(eff.year, eff.month, 1)
    after = np.array([m > m0 for m in months], dtype=float)
    return [(c, 1.0 - after), (succ, after)]


def apply_installed_base(service_demand: pd.DataFrame, ib: pd.DataFrame, bill_items: set) -> pd.DataFrame:
    """Service level = (1 - w) x own draw + w x failure rate x installed base."""
    w = C.INSTALLED_BASE_WEIGHT
    ibw = ib.pivot(index="item_id", columns="month", values="value")
    sd = service_demand.copy()
    # every month of a bill part carrying a service channel gets a level, active or not
    items = sorted(set(sd["item_id"].astype(int)) & set(int(i) for i in bill_items) & set(ibw.index))
    full = pd.MultiIndex.from_product([items, list(ibw.columns)], names=["item_id", "month"])
    own = sd.set_index(["item_id", "month"])["qty"].reindex(full).fillna(0.0)
    term = ibw.loc[items].stack().reindex(full)
    level = (1 - w) * own + w * C.INSTALLED_BASE_FAILURE_RATE * term
    new = level.round().astype(int).reset_index().rename(columns={0: "qty"})
    new.columns = ["item_id", "month", "qty"]
    rest = sd[~sd["item_id"].isin(items)]
    out = pd.concat([rest, new[new["qty"] > 0]], ignore_index=True)
    return out.sort_values(["item_id", "month"]).reset_index(drop=True)


# ── Service holds ───────────────────────────────────────────────────────────
def apply_service_holds(service_orders: pd.DataFrame, holds: dict) -> pd.DataFrame:
    """A line held for stock ships the day the stock returns (or the first working
    day after it)."""
    df = service_orders.copy()
    for i in df.index:
        dly = holds.get((df.at[i, "order_id"], df.at[i, "item_number"]), 0)
        if dly > 0:
            d = date.fromisoformat(df.at[i, "ship_date"]) + timedelta(days=int(dly))
            df.at[i, "ship_date"] = min(next_working_day(d), C.END_DATE).isoformat()
    return df
