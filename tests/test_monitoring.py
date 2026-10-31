from datetime import date

import numpy as np
import pandas as pd

from dfm import config as C
from dfm import monitoring as M
from dfm import registry as R
from dfm.features import _monday

WEEKS = pd.date_range("2023-01-02", _monday(C.END_DATE), freq="W-MON")
WIDX = {w: i for i, w in enumerate(WEEKS)}


def _case(forecast: float, n_items: int = 200, months=((2026, 1), (2026, 2)), h: int = 2, version="demand_models/1"):
    """Schedule rows on the first Monday of each month for n_items smooth items, target 10 each."""
    sched, frame = [], []
    for y, m in months:
        d = pd.Timestamp(_monday(date(y, m, 7)))
        for i in range(n_items):
            item = f"IT-{i:04d}"
            sched.append({"canonical_item_number": item, "date": d.date(), "forecast_over_horizon": forecast,
                          "model_version": version})
            frame.append({"item": item, "t": WIDX[d], "h": h, "target": 10.0, "segment": "smooth",
                          "is_reference_row": True})
    return pd.DataFrame(sched), pd.DataFrame(frame)


def test_bias_gate_passes_within_limit():
    s, f = _case(10.5)
    g = R.gate_bias(s, "demand_models/1", f, WEEKS)
    assert g.passed and g.tags["bias_month"] == "2026-02" and g.tags["bias_smooth"] == "+0.0500"


def test_bias_gate_fails_outside_limit():
    s, f = _case(11.5)
    g = R.gate_bias(s, "demand_models/1", f, WEEKS)
    assert not g.passed and g.tags["bias_smooth"] == "+0.1500"


def test_bias_gate_fails_closed():
    s, f = _case(10.0)
    assert not R.gate_bias(None, "demand_models/1", f, WEEKS).passed
    assert not R.gate_bias(s, None, f, WEEKS).passed
    g = R.gate_bias(s, "demand_models/2", f, WEEKS)
    assert not g.passed and "issued by demand_models/1" in g.detail
    # forecasts whose windows run past the end of the planning window are not scored: no matured month
    s, f = _case(10.0, months=((2026, 6),), h=8)
    g = R.gate_bias(s, "demand_models/1", f, WEEKS)
    assert not g.passed and "fails closed" in g.detail and "bias_month" not in g.tags


def test_bias_gate_skips_thin_patterns():
    s, f = _case(12.0, n_items=100)
    g = R.gate_bias(s, "demand_models/1", f, WEEKS)
    assert not g.passed and "bias_smooth" not in g.tags


def test_month_bias_matches_monitor_arithmetic():
    s, f = _case(10.5)
    live = M.live_forecasts(M.table_entries(s), f, WEEKS)
    mb = M.month_bias(live)
    assert [m.period for m in mb] == ["2026-01", "2026-02"]
    assert all(m.matured and m.n_scored == 200 for m in mb)
    assert np.isclose(mb[0].pattern_bias["smooth"], 0.05)


def test_uom_gap():
    corrected = pd.DataFrame({"canonical_item_number": ["A", "A", "B"], "item_number": ["A", "A", "B"],
                              "txn_id": [1, 2, 3], "txn_type": ["RECEIPT", "ISSUE", "RECEIPT"], "qty": [2.0, 5.0, 4.0]})
    staged = pd.DataFrame({"txn_id": [1, 2, 3], "uom": ["BOX", "EA", "EA"]})
    conv = pd.DataFrame({"item_number": ["A"], "purchase_uom": ["BOX"], "stock_uom": ["EA"], "conversion": [10.0]})
    attrs = pd.DataFrame({"canonical_item_number": ["A", "B"], "standard_cost": [1.0, 2.0]})
    g = M.uom_gap(corrected, staged, conv, attrs)
    # A: as booked 2 - 5 = -3 (0 value), converted 20 - 5 = 15; B unchanged, 4 x 2 = 8
    assert g["items"] == 1 and g["on_hand_value_as_booked"] == 0.0 and g["on_hand_value_converted"] == 15.0
    assert g["understatement_of_total"] == 15.0 / 8.0


def test_short_weeks():
    s = pd.DataFrame({"week": pd.to_datetime(["2025-12-29", "2026-01-05", "2026-01-12"]),
                      "short_week": [True, True, False], "short_active_week": [True, None, False]})
    assert M.short_weeks(s) == {"2026-01": {"short_week_share": 0.5, "active_short_share": 0.0}}
