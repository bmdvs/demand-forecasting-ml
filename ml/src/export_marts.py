"""Export the dbt marts the model reads from the DuckDB warehouse to parquet.

dbt builds the marts (data_pipeline/models/marts); this step writes them where the
model and report code read them, with the column names and types they expect:

  ml/data/marts/item_crosswalk.csv              item_number -> canonical record
  ml/data/marts/item_attributes.parquet         per-item attributes for the model
  ml/data/marts/consumption_{raw,master,fully,true}.parquet   monthly cleaning tiers
  ml/data/marts/consumption_monthly.parquet     the fully cleaned tier the model uses
  ml/data/marts/consumption_weekly.parquet      fully cleaned weekly usage

The three consumption tiers differ only in how clean the history is:
  raw     each surviving record's own usage (duplicate history split, unrecorded usage missing)
  master  duplicate records merged to the canonical item
  fully   master plus the confirmed corrections: unrecorded usage added back, keying
          errors deflated, duplicate postings removed
The true-demand series is the common evaluation target.

Run after `dbt build`:  python -m ml.src.export_marts
"""
from __future__ import annotations

import duckdb
import pandas as pd

from data_source.generate import config as C

REPO = C.REPO_ROOT
WAREHOUSE = REPO / "data_source" / "demand_forecasting.duckdb"
MARTS = REPO / "ml" / "data" / "marts"

TIERS = {"raw": "mart_consumption_raw", "master": "mart_consumption_master",
         "fully": "mart_consumption_fully", "true": "mart_true_demand"}


def _series(con, table, period, unit, integer):
    df = con.execute(f"select canonical_item_number as canonical, {period}, consumption from {table} "
                     f"order by canonical, {period}").fetchdf()
    df[period] = pd.to_datetime(df[period]).astype(f"datetime64[{unit}]")
    df["consumption"] = df["consumption"].astype("int64" if integer else "float64")
    return df


def run():
    MARTS.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE), read_only=True)

    xw = con.execute("select item_number, canonical_item_number from int_item_crosswalk").fetchdf()
    xw.to_csv(MARTS / "item_crosswalk.csv", index=False)

    tiers = {}
    for name, table in TIERS.items():
        integer = name != "fully"
        tiers[name] = _series(con, table, "month", "ms" if integer else "ns", integer)
        tiers[name].to_parquet(MARTS / f"consumption_{name}.parquet", index=False)
    tiers["fully"].to_parquet(MARTS / "consumption_monthly.parquet", index=False)
    _series(con, "mart_consumption_weekly", "week", "ns", False).to_parquet(
        MARTS / "consumption_weekly.parquet", index=False)

    attrs = con.execute("""select canonical_item_number, standard_cost, item_class, segment, abc,
                                  corrected_lead_days, annual_consumption
                           from mart_item_attributes order by canonical_item_number""").fetchdf()
    attrs.to_parquet(MARTS / "item_attributes.parquet", index=False)

    # demand-signal marts for the feature set: order book, lead times, shortages, families,
    # installed base, calendar and item lifecycle (kept apart from the files above)
    signals = {
        "firm_requirements_weekly": "select * from mart_firm_requirements_weekly order by canonical_item_number, origin",
        "item_leadtime_weekly": "select * from mart_item_leadtime_weekly order by canonical_item_number, week",
        "supplier_leadtime_weekly": "select * from mart_supplier_leadtime_weekly order by supplier_id, week",
        "shortage_weekly": "select * from mart_shortage_weekly order by canonical_item_number, week",
        "item_family": "select * from int_item_family order by canonical_item_number",
        "family_usage_weekly": "select * from mart_family_usage_weekly order by family, week",
        "product_family_weekly": "select * from mart_product_family_weekly order by product_family, week",
        "installed_base": "select * from mart_installed_base order by product_family, month",
        "item_installed_base": "select * from mart_item_installed_base order by canonical_item_number, month",
        "job_requirements": "select * from int_job_requirements order by order_id, canonical_item_number",
        "dim_week": "select * from dim_week order by week",
        "item_lifecycle": """select canonical_item_number, first_use_date, created_date, superseded_by,
                                    supersede_planned_date, supersede_switch_date, successor_created_date, supersedes
                             from mart_item_attributes order by canonical_item_number""",
    }
    for name, sql in signals.items():
        con.execute(sql).fetchdf().to_parquet(MARTS / f"{name}.parquet", index=False)
    con.close()

    tot = lambda d: d["consumption"].sum()
    print("\n=== Cleaning-tier consumption marts (from dbt) ===")
    print(f"  true demand      {tot(tiers['true']):>14,.0f}")
    for name, label in [("raw", "raw (recorded)"), ("master", "master-cleaned"), ("fully", "fully-cleaned")]:
        print(f"  {label:<16} {tot(tiers[name]):>14,.0f}   {tot(tiers[name]) / tot(tiers['true']) * 100:5.1f}% of true")
    print(f"  items {len(attrs):,}   segments {attrs['segment'].value_counts().to_dict()}\n")


if __name__ == "__main__":
    run()
