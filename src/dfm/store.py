"""Reads the model's inputs and writes its outputs, on the platform or locally.

The forecast and policy code reads two kinds of input, always as pandas frames with fixed columns, dtypes
and row order:
  marts     the warehouse tables the model reads (gold marts and three silver tables), projected to the
            frames in MARTS: the columns listed, cast to the dtypes listed, sorted on the keys listed
  extracts  the ERP and remediation extracts as delivered, with the types a CSV reader infers from the
            delivered text and in the delivered row order (EXTRACT_ORDER)

TableStore reads Unity Catalog tables through Spark (catalog.schema.table); the same projection applied to
Parquet exports of those tables (DirectoryTables) lets the parity runner reproduce a platform run locally.
FileStore reads a local archive: the exported mart files and the CSV extracts. Outputs are written as
Delta tables (TableStore) or Parquet files under a local folder (FileStore and DirectoryTables).
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


@dataclass(frozen=True)
class Mart:
    """A model input: source table, the output columns (source name, frame name, dtype) and sort keys."""
    schema: str
    table: str
    columns: tuple[tuple[str, str, str], ...]
    order_by: tuple[str, ...]


def _cols(*specs: tuple) -> tuple[tuple[str, str, str], ...]:
    """(name, dtype) or (source name, frame name, dtype)."""
    return tuple((s[0], s[0], s[1]) if len(s) == 2 else s for s in specs)


MARTS: dict[str, Mart] = {
    "consumption_weekly": Mart("gold", "mart_consumption_weekly", _cols(
        ("canonical_item_number", "canonical", "object"), ("week", "datetime64[ns]"), ("consumption", "float64")),
        ("canonical", "week")),
    "item_attributes": Mart("gold", "mart_item_attributes", _cols(
        ("canonical_item_number", "object"), ("standard_cost", "float64"), ("item_class", "object"),
        ("segment", "object"), ("abc", "object"), ("corrected_lead_days", "float64"),
        ("annual_consumption", "float64")), ("canonical_item_number",)),
    "item_lifecycle": Mart("gold", "mart_item_attributes", _cols(
        ("canonical_item_number", "object"), ("first_use_date", "datetime64[us]"), ("created_date", "datetime64[us]"),
        ("superseded_by", "object"), ("supersede_planned_date", "datetime64[us]"),
        ("supersede_switch_date", "datetime64[us]"), ("successor_created_date", "datetime64[us]"),
        ("supersedes", "object")), ("canonical_item_number",)),
    "firm_requirements_weekly": Mart("gold", "mart_firm_requirements_weekly", _cols(
        ("canonical_item_number", "object"), ("origin", "datetime64[us]"), ("h_weeks", "int32"), ("firm_h", "float64"),
        ("firm_rel_h", "float64"), ("firm_next4", "float64"), ("open_jobs", "int64")),
        ("canonical_item_number", "origin")),
    "item_leadtime_weekly": Mart("gold", "mart_item_leadtime_weekly", _cols(
        ("canonical_item_number", "object"), ("week", "datetime64[us]"), ("receipts_to_date", "int64"),
        ("last_receipt_date", "datetime64[us]"), ("lt_from_master", "bool"), ("lt_roll8", "float64"),
        ("lt_sd", "float64"), ("lt_trend", "float64"), ("ontime_13", "float64"), ("partial_13", "float64"),
        ("open_po_count", "int64"), ("po_past_promise", "int64"), ("receipts_26w", "int64"),
        ("lt26_source", "object"), ("lt_roll26w", "float64"), ("lt_sd26w", "float64"), ("lt_source", "object"),
        ("lt_pooled26w", "float64"), ("lt_pooled_sd26w", "float64"), ("h_weeks", "int32")),
        ("canonical_item_number", "week")),
    "supplier_leadtime_weekly": Mart("gold", "mart_supplier_leadtime_weekly", _cols(
        ("supplier_id", "object"), ("week", "datetime64[us]"), ("receipts_to_date", "int64"),
        ("last_receipt_date", "datetime64[us]"), ("lt_roll8", "float64"), ("lt_sd", "float64"),
        ("lt_trend", "float64"), ("ontime_13", "float64"), ("partial_13", "float64"), ("open_po_count", "int64"),
        ("po_past_promise", "int64"), ("receipts_26w", "int64"), ("lt_roll26w", "float64"), ("lt_sd26w", "float64"),
        ("lt26_fallback", "bool")), ("supplier_id", "week")),
    "shortage_weekly": Mart("gold", "mart_shortage_weekly", _cols(
        ("canonical_item_number", "object"), ("week", "datetime64[us]"), ("short_week", "bool"),
        ("short_active_week", "bool"), ("held_jobs", "int64"), ("service_backorder_lines", "int64"),
        ("service_backorder_qty", "float64")), ("canonical_item_number", "week")),
    "item_family": Mart("silver", "int_item_family", _cols(
        ("canonical_item_number", "object"), ("item_class", "object"), ("material_family", "object"),
        ("primary_product_family", "object"), ("primary_family_share", "float64"), ("family", "object")),
        ("canonical_item_number",)),
    "family_usage_weekly": Mart("gold", "mart_family_usage_weekly", _cols(
        ("family", "object"), ("week", "datetime64[us]"), ("n_items", "int64"), ("family_usage", "float64")),
        ("family", "week")),
    "product_family_weekly": Mart("gold", "mart_product_family_weekly", _cols(
        ("product_family", "object"), ("week", "datetime64[us]"), ("units_completed", "float64"),
        ("units_booked_open", "float64")), ("product_family", "week")),
    "installed_base": Mart("gold", "mart_installed_base", _cols(
        ("product_family", "object"), ("month", "datetime64[us]"), ("units_completed", "float64"),
        ("units_fielded", "float64"), ("age_weighted_base", "float64"), ("age_weighted_base_est", "float64")),
        ("product_family", "month")),
    "item_installed_base": Mart("gold", "mart_item_installed_base", _cols(
        ("canonical_item_number", "object"), ("month", "datetime64[us]"), ("n_parent_products", "int64"),
        ("units_carried", "float64"), ("age_weighted_base", "float64"), ("age_weighted_base_est", "float64")),
        ("canonical_item_number", "month")),
    "job_requirements": Mart("silver", "int_job_requirements", _cols(
        ("order_id", "object"), ("canonical_item_number", "object"), ("req_qty", "float64"),
        ("required_week", "datetime64[us]"), ("booked_date", "datetime64[us]"), ("release_date", "datetime64[us]"),
        ("due_date", "datetime64[us]"), ("required_date", "datetime64[us]"), ("completed_date", "datetime64[us]"),
        ("status", "object"), ("delay_days", "int32"), ("qty_ordered", "int32"), ("qty_completed", "int32"),
        ("customer_id", "object"), ("product_number", "object"), ("product_family", "object"),
        ("configuration_code", "object")), ("order_id", "canonical_item_number")),
    "dim_week": Mart("gold", "dim_week", _cols(
        ("week_index", "int32"), ("week", "datetime64[us]"), ("is_shutdown", "bool"), ("working_days", "int64"),
        ("fiscal_year", "int64"), ("fiscal_quarter", "int32"), ("weeks_to_quarter_end", "int32")), ("week",)),
    "bom_resolved": Mart("silver", "int_bom_resolved", _cols(
        ("parent", "object"), ("parent_type", "object"), ("component_item", "object"), ("component", "object"),
        ("component_type", "object"), ("qty_per", "float64"), ("valid_from", "datetime64[us]"),
        ("valid_to", "datetime64[us]"), ("row_source", "object")), ("parent", "component_item", "valid_from")),
}
CROSSWALK = ("silver", "int_item_crosswalk")

# The delivered row order of each extract the model reads, as a sort that restores it. Extracts whose
# rows the model uses only as sets or lookups (bills of material, the item master) take a full-row sort.
EXTRACT_ORDER: dict[tuple[str, str], tuple[str, ...] | None] = {
    ("erp", "inventory_transactions"): ("txn_date", "txn_id"),
    ("erp", "purchase_orders"): ("po_id", "line"),
    ("erp", "service_orders"): ("order_id", "line"),
    ("erp", "production_orders"): ("order_id",),
    ("erp", "bill_of_materials"): None,
    ("erp", "item_master"): ("item_number",),
    ("erp", "supplier_master"): ("supplier_id",),
    ("remediation", "bom_change_log"): None,
}
# added by the pipeline's bronze layer, not part of the extract; the rescued-data column (values that did
# not fit the inferred schema) must be empty
BRONZE_COLUMNS = ("source_file", "_rescued_data")


# ── projection ──────────────────────────────────────────────────────────────
def _column(col: pa.ChunkedArray, dtype: str) -> pd.Series:
    if dtype.startswith("datetime64"):
        unit = dtype[dtype.index("[") + 1:-1]
        t = col.type
        if pa.types.is_timestamp(t) and t.tz is not None:
            col = pc.cast(col, pa.timestamp(t.unit))         # wall time in UTC, the session time zone
        return pd.Series(pc.cast(col, pa.timestamp(unit)).to_pandas()).astype(dtype)
    if pa.types.is_decimal(col.type):
        s = pd.Series(col.to_pandas())
        return s.map(lambda v: np.nan if v is None else float(v)).astype(dtype)
    if dtype == "object":
        return pd.Series(col.to_pandas(), dtype=object)
    return pd.Series(col.to_pandas()).astype(dtype)


def project(table: pa.Table, mart: Mart) -> pd.DataFrame:
    """A source table as the model's input frame: listed columns, dtypes and row order."""
    out = pd.DataFrame({name: _column(table.column(src), dtype) for src, name, dtype in mart.columns})
    return out.sort_values(list(mart.order_by), kind="stable").reset_index(drop=True)


def as_delivered(df: pd.DataFrame, order: tuple[str, ...] | None) -> pd.DataFrame:
    """An extract as a CSV reader sees the delivered file: written as CSV text and read back, so every
    column takes the type inferred from the text, then put in the delivered row order."""
    if "_rescued_data" in df.columns and df["_rescued_data"].notna().any():
        raise ValueError(f"{int(df['_rescued_data'].notna().sum())} extract rows carry rescued data")
    df = df.drop(columns=[c for c in BRONZE_COLUMNS if c in df.columns])
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    out = pd.read_csv(buf, low_memory=False)
    keys = list(order) if order else list(out.columns)
    return out.sort_values(keys, kind="stable").reset_index(drop=True)


# ── backends ────────────────────────────────────────────────────────────────
class Tables(Protocol):
    def read(self, schema: str, table: str, columns: list[str] | None = None) -> pa.Table: ...


class SparkTables:
    """Unity Catalog tables through the Spark session."""

    def __init__(self, spark: Any, catalog: str) -> None:
        self.spark, self.catalog = spark, catalog

    def name(self, schema: str, table: str) -> str:
        return f"{self.catalog}.{schema}.{table}"

    def read(self, schema: str, table: str, columns: list[str] | None = None) -> pa.Table:
        df = self.spark.table(self.name(schema, table))
        return (df.select(*columns) if columns else df).toArrow()

    def exists(self, schema: str, table: str) -> bool:
        return bool(self.spark.catalog.tableExists(self.name(schema, table)))


class DirectoryTables:
    """Parquet exports of the platform tables (one file per table) and the landed extract files."""

    def __init__(self, tables: Path, landing: Path | None = None, pass_name: str = "pass1") -> None:
        self.tables, self.landing, self.pass_name = Path(tables), landing, pass_name

    def read(self, schema: str, table: str, columns: list[str] | None = None) -> pa.Table:
        if schema == "bronze":
            source, name = table.split("__", 1)
            assert self.landing is not None, "no landing folder for extracts"
            path = self.landing / source / name / self.pass_name / f"{name}.parquet"
        else:
            path = self.tables / f"{table}.parquet"
        return pq.read_table(path, columns=columns)


class TableStore:
    """Inputs from tables (Unity Catalog, or their exports); outputs to Delta tables or a local folder."""

    def __init__(self, tables: Tables, out: Path | None = None) -> None:
        self.tables, self.out = tables, out

    @property
    def catalog(self) -> str | None:
        return getattr(self.tables, "catalog", None)

    def mart(self, name: str) -> pd.DataFrame:
        m = MARTS[name]
        return project(self.tables.read(m.schema, m.table, sorted({c[0] for c in m.columns})), m)

    def crosswalk(self) -> dict:
        t = self.tables.read(*CROSSWALK, ["item_number", "canonical_item_number"]).to_pandas()
        xw = as_delivered(t[["item_number", "canonical_item_number"]], ("item_number",))
        return xw.set_index("item_number")["canonical_item_number"].to_dict()

    def extract(self, source: str, table: str) -> pd.DataFrame:
        df = self.tables.read("bronze", f"{source}__{table}").to_pandas()
        return as_delivered(df, EXTRACT_ORDER.get((source, table)))

    def write(self, pdf: pd.DataFrame, schema: str, table: str) -> int:
        if isinstance(self.tables, SparkTables):
            spark = self.tables.spark
            sdf = spark.createDataFrame(pdf)
            (sdf.write.format("delta").mode("overwrite").option("overwriteSchema", "true")
             .saveAsTable(self.tables.name(schema, table)))
            return spark.table(self.tables.name(schema, table)).count()
        return _write_local(self.out, pdf, schema, table)

    def read_output(self, schema: str, table: str) -> pd.DataFrame:
        if isinstance(self.tables, SparkTables):
            return self.tables.read(schema, table).to_pandas()
        return pd.read_parquet(Path(self.out) / schema / f"{table}.parquet")

    def has_output(self, schema: str, table: str) -> bool:
        if isinstance(self.tables, SparkTables):
            return self.tables.exists(schema, table)
        return self.out is not None and (Path(self.out) / schema / f"{table}.parquet").exists()


class FileStore:
    """A local archive of the warehouse's exported mart files (marts) and the CSV extracts (raw)."""

    def __init__(self, marts: Path, raw: Path, out: Path | None = None) -> None:
        self.marts, self.raw, self.out = Path(marts), Path(raw), out
        self.catalog = None

    def mart(self, name: str) -> pd.DataFrame:
        return pd.read_parquet(self.marts / f"{name}.parquet")

    def crosswalk(self) -> dict:
        return pd.read_csv(self.marts / "item_crosswalk.csv").set_index("item_number")["canonical_item_number"].to_dict()

    def extract(self, source: str, table: str) -> pd.DataFrame:
        return pd.read_csv(self.raw / source / f"{table}.csv", low_memory=False)

    def write(self, pdf: pd.DataFrame, schema: str, table: str) -> int:
        return _write_local(self.out, pdf, schema, table)

    def read_output(self, schema: str, table: str) -> pd.DataFrame:
        return pd.read_parquet(Path(self.out) / schema / f"{table}.parquet")

    def has_output(self, schema: str, table: str) -> bool:
        return self.out is not None and (Path(self.out) / schema / f"{table}.parquet").exists()


def _write_local(out: Path | None, pdf: pd.DataFrame, schema: str, table: str) -> int:
    assert out is not None, "no output folder"
    d = Path(out) / schema
    d.mkdir(parents=True, exist_ok=True)
    pdf.to_parquet(d / f"{table}.parquet", index=False)
    return len(pdf)
