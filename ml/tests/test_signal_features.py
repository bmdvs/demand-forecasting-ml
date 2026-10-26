"""Unit tests for the demand-signal features on a hand-built fixture.

Items:
  BILL-1   a bill part: one job required inside its horizon, one required after it, one
           booked after the origin (must not count)
  SVC-1    a service part on no bill: no firm requirements
  NEW-1    a part first used 20 weeks before the origin
  OLD-1 /  a superseded pair: the successor NEW-2 is created on 2025-03-03 and the bill
  NEW-2    switches on 2025-04-07
Run:  python -m pytest ml/tests -q
"""
import numpy as np
import pandas as pd
import pytest

from ml.src import signal_features as SF

WEEKS = pd.date_range("2024-12-30", periods=40, freq="W-MON")
ORIGIN = pd.Timestamp("2025-03-17")
T0 = int(np.where(WEEKS == ORIGIN)[0][0])


def frame_for(items, h=4):
    return pd.DataFrame({"item": items, "t": T0, "week": ORIGIN, "h": h,
                         "s52": 0.0, "s13": 13.0, "s4": 4.0, "ly": 0.0})


@pytest.fixture
def job_req():
    rows = [
        # inside the 4-week horizon, released before the origin
        dict(order_id="J1", canonical_item_number="BILL-1", req_qty=10, booked_date="2025-02-01",
             release_date="2025-03-03", required_date="2025-03-31", completed_date=None,
             product_family="Conveyor", qty_ordered=2),
        # required after the horizon, inside the next four weeks
        dict(order_id="J2", canonical_item_number="BILL-1", req_qty=7, booked_date="2025-02-10",
             release_date="2025-04-01", required_date="2025-04-21", completed_date=None,
             product_family="Conveyor", qty_ordered=1),
        # booked after the origin: invisible on the origin
        dict(order_id="J3", canonical_item_number="BILL-1", req_qty=99, booked_date="2025-03-20",
             release_date="2025-04-01", required_date="2025-03-31", completed_date=None,
             product_family="Conveyor", qty_ordered=5),
        # completed before the origin: no longer in the book
        dict(order_id="J4", canonical_item_number="BILL-1", req_qty=50, booked_date="2025-01-10",
             release_date="2025-02-01", required_date="2025-03-17", completed_date="2025-03-10",
             product_family="Conveyor", qty_ordered=3),
    ]
    return pd.DataFrame(rows)


def test_firm_requirements_inside_and_outside_horizon(job_req):
    f = frame_for(["BILL-1", "SVC-1"])
    out = SF.firm_features(f, job_req, WEEKS)
    bill, svc = out.iloc[0], out.iloc[1]
    assert bill["firm_h"] == 10                 # J1 only; J2 is beyond h, J3 not yet booked, J4 done
    assert bill["firm_rel_h"] == 10             # J1 was released before the origin
    assert bill["firm_next4"] == 7              # J2 falls in the four weeks after the horizon
    assert bill["open_jobs"] == 1
    assert svc["firm_h"] == 0 and svc["firm_next4"] == 0 and svc["open_jobs"] == 0


def test_job_booked_after_origin_never_counts(job_req):
    later = frame_for(["BILL-1"]).assign(week=pd.Timestamp("2025-03-24"), t=T0 + 1)
    out = SF.firm_features(later, job_req, WEEKS)
    assert out.iloc[0]["firm_h"] == 10 + 99     # once booked (2025-03-20), J3 enters the book


@pytest.fixture
def lifecycle():
    return pd.DataFrame([
        dict(canonical_item_number="BILL-1", first_use_date="2023-01-02", created_date="2015-01-01",
             superseded_by=None, supersede_planned_date=None, supersede_switch_date=None,
             successor_created_date=None, supersedes=None),
        dict(canonical_item_number="NEW-1", first_use_date=str((ORIGIN - pd.Timedelta(weeks=20)).date()),
             created_date="2024-09-01", superseded_by=None, supersede_planned_date=None,
             supersede_switch_date=None, successor_created_date=None, supersedes=None),
        dict(canonical_item_number="OLD-1", first_use_date="2023-01-02", created_date="2015-01-01",
             superseded_by="NEW-2", supersede_planned_date="2025-02-03", supersede_switch_date="2025-04-07",
             successor_created_date="2025-03-03", supersedes=None),
        dict(canonical_item_number="NEW-2", first_use_date="2025-04-07", created_date="2025-03-03",
             superseded_by=None, supersede_planned_date=None, supersede_switch_date=None,
             successor_created_date=None, supersedes="OLD-1"),
    ])


@pytest.fixture
def bom():
    return pd.DataFrame([
        dict(parent="PRD-CO-000", component="BILL-1", component_type="purchased", valid_from="1900-01-01", valid_to="9999-12-31"),
        dict(parent="PRD-CO-000", component="OLD-1", component_type="purchased", valid_from="1900-01-01", valid_to="2025-04-07"),
        dict(parent="PRD-CO-000", component="NEW-2", component_type="purchased", valid_from="2025-04-07", valid_to="9999-12-31"),
    ])


def empty_ib():
    return pd.DataFrame(columns=["canonical_item_number", "month", "units_carried", "age_weighted_base"])


def test_twenty_week_old_item_history(lifecycle, bom):
    out = SF.lifecycle_features(frame_for(["NEW-1", "BILL-1"]), lifecycle, bom, empty_ib(), WEEKS)
    assert out.iloc[0]["hist_wks"] == pytest.approx(20)
    assert out.iloc[0]["hist_wks"] < 52          # S4 sets s52, nz52, ly and fam_ly missing for it
    assert out.iloc[1]["n_parents"] == 1


def test_superseded_pair_across_the_switch(lifecycle, bom):
    before = frame_for(["OLD-1", "NEW-2"])                                       # 2025-03-17
    after = frame_for(["OLD-1", "NEW-2"]).assign(week=pd.Timestamp("2025-04-14"), t=T0 + 4)
    b = SF.lifecycle_features(before, lifecycle, bom, empty_ib(), WEEKS)
    a = SF.lifecycle_features(after, lifecycle, bom, empty_ib(), WEEKS)
    # successor created, switch not yet: pending on both, superseded on neither
    assert list(b["supersede_pending"]) == [1.0, 1.0] and list(b["superseded"]) == [0.0, 0.0]
    # after the switch: superseded on both, the successor one week past its switch
    assert list(a["superseded"]) == [1.0, 1.0] and list(a["supersede_pending"]) == [0.0, 0.0]
    assert a.iloc[1]["successor_age_wks"] == pytest.approx(1.0)
    # the bill as of the origin carries the old part before the switch and the successor after
    assert list(b["n_parents"]) == [1, 0] and list(a["n_parents"]) == [0, 1]
    assert a.iloc[1]["bom_added_13"] == 1 and a.iloc[0]["bom_removed_13"] == 1


def test_lead_time_rejects_a_receipt_dated_on_or_after_the_week():
    lt = pd.DataFrame([dict(canonical_item_number="BILL-1", week=ORIGIN, last_receipt_date=ORIGIN,
                            lt_roll8=20, lt_sd=2, lt_trend=1, lt_roll26w=20, lt_pooled26w=20, lt_source="item",
                            ontime_13=1, partial_13=0, po_past_promise=0)])
    with pytest.raises(AssertionError):
        SF.leadtime_features(frame_for(["BILL-1"]), lt)


def test_feature_lists_are_cumulative():
    ref = SF.features_for("reference")
    s1 = SF.features_for("S1"); s6 = SF.features_for("S6")
    assert set(ref) < set(s1) < set(s6)
    assert all(c in s6 for g in SF.GROUPS.values() for c in g)
