"""The store's projection of tables to model input frames, and extracts as delivered."""
import datetime as dt
from decimal import Decimal

import pandas as pd
import pyarrow as pa

from dfm import store as S

MART = S.Mart("gold", "t", S._cols(("item_number", "item", "object"), ("week", "datetime64[us]"),
                                   ("qty", "int64"), ("value", "float64")), ("item", "week"))


def test_project_casts_renames_and_sorts():
    t = pa.table({"item_number": ["B", "A", "A"],
                  "week": pa.array([dt.date(2025, 1, 6), dt.date(2025, 1, 13), dt.date(2025, 1, 6)], pa.date32()),
                  "qty": pa.array([1, 2, 3], pa.int32()),
                  "value": pa.array([Decimal("1.10"), Decimal("2.20"), None], pa.decimal128(38, 2))})
    out = S.project(t, MART)
    assert list(out.columns) == ["item", "week", "qty", "value"]
    assert [str(d) for d in out.dtypes] == ["object", "datetime64[us]", "int64", "float64"]
    assert out["item"].tolist() == ["A", "A", "B"] and out["qty"].tolist() == [3, 2, 1]
    assert out["value"].iloc[1] == 2.2 and pd.isna(out["value"].iloc[0])


def test_project_open_interval_dates_survive():
    m = S.Mart("silver", "t", S._cols(("valid_to", "datetime64[us]")), ("valid_to",))
    out = S.project(pa.table({"valid_to": pa.array([dt.date(9999, 12, 31)], pa.date32())}), m)
    assert str(out["valid_to"].iloc[0].date()) == "9999-12-31"


def test_project_utc_timestamps_keep_wall_time():
    m = S.Mart("gold", "t", S._cols(("week", "datetime64[ns]")), ("week",))
    ts = pa.array([dt.datetime(2025, 1, 6)], pa.timestamp("us", tz="UTC"))
    out = S.project(pa.table({"week": ts}), m)
    assert out["week"].iloc[0] == pd.Timestamp("2025-01-06")


def test_as_delivered_reads_types_from_text_and_restores_order():
    df = pd.DataFrame({"txn_id": ["T2", "T1", "T3"], "txn_date": [dt.date(2025, 1, 2), dt.date(2025, 1, 2),
                                                                 dt.date(2025, 1, 1)],
                       "qty": [1, -2, 3], "job_id": ["SO-1", None, "WO-2"], "source_file": ["f", "f", "f"]})
    out = S.as_delivered(df, ("txn_date", "txn_id"))
    assert list(out.columns) == ["txn_id", "txn_date", "qty", "job_id"]
    assert out["txn_id"].tolist() == ["T3", "T1", "T2"]
    assert out["txn_date"].tolist() == ["2025-01-01", "2025-01-02", "2025-01-02"]
    assert str(out["qty"].dtype) == "int64" and pd.isna(out["job_id"].iloc[1])
