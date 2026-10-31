"""Compare two sets of tables, one Parquet file per table, at the port's parity tolerances.

Row counts, keys and strings must match exactly. Numeric columns match within 1e-9 relative,
with a 1e-12 absolute floor near zero. Each table is reported as identical (every value equal),
within tolerance, or a miss, with the largest numeric difference and the columns that moved.
Rows are aligned by sorting on every non-floating-point column, then on the floating-point
columns rounded to ten significant digits.

Usage:
  python tests/parity/compare.py REFERENCE_DIR CANDIDATE_DIR [--tables a,b] [--names map.json]
                                 [--json out.json] [--markdown out.md]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

REL_TOL = 1e-9
ABS_FLOOR = 1e-12


def _load(path: Path, dates_as_midnight: bool = False) -> pd.DataFrame:
    """Read a table; decimals become floats, dates and timestamps ISO text (UTC), so that a date
    and a timestamp never compare equal and far dates such as 9999-12-31 survive. With
    dates_as_midnight a midnight timestamp is written as its date, for files that stored
    dates as timestamps (pandas exports)."""
    table = pq.read_table(path)
    cols = {}
    for field, col in zip(table.schema, table.columns):
        t = field.type
        if pa.types.is_decimal(t):
            col = col.cast(pa.float64())
        elif pa.types.is_date(t):
            col = pc.strftime(col.cast(pa.timestamp("s")), format="%Y-%m-%d")
        elif pa.types.is_timestamp(t):
            col = pc.strftime(col.cast(pa.timestamp("us", tz="UTC")), format="%Y-%m-%dT%H:%M:%S")
            if dates_as_midnight:
                col = pc.replace_substring_regex(col, pattern=r"T00:00:00(\.0+)?$", replacement="")
        cols[field.name] = col
    return pa.table(cols).to_pandas()


def _kind(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "bool"
    if pd.api.types.is_float_dtype(s):
        return "float"
    if pd.api.types.is_integer_dtype(s):
        return "int"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    return "string"


def compare_frames(ref: pd.DataFrame, got: pd.DataFrame) -> dict:
    out: dict = {"rows_ref": len(ref), "rows_got": len(got)}
    missing = [c for c in ref.columns if c not in got.columns]
    extra = [c for c in got.columns if c not in ref.columns]
    out["missing_columns"], out["extra_columns"] = missing, extra
    cols = [c for c in ref.columns if c in got.columns]
    kinds = {}
    type_notes = []
    for c in cols:
        kr, kg = _kind(ref[c]), _kind(got[c])
        # an integer column holding nulls arrives as float; compare such pairs as numbers
        if {kr, kg} <= {"int", "float"}:
            kinds[c] = "float" if "float" in (kr, kg) else "int"
            if kr != kg and not (ref[c].isna().any() or got[c].isna().any()):
                type_notes.append(f"{c}: {kr} vs {kg}")
        elif kr == kg:
            kinds[c] = kr
        else:
            kinds[c] = "string"
            type_notes.append(f"{c}: {kr} vs {kg}")
    out["type_notes"] = type_notes
    if missing or extra or len(ref) != len(got):
        out["status"] = "MISS"
        out["reason"] = "columns" if (missing or extra) else "row count"
        return out

    floats = [c for c in cols if kinds[c] == "float"]
    keys = [c for c in cols if kinds[c] != "float"]

    def prep(df):
        d = df[cols].copy()
        for c in cols:
            if kinds[c] == "string":
                d[c] = d[c].astype("string")
            elif kinds[c] in ("int", "float"):
                d[c] = pd.to_numeric(d[c]).astype("float64")
        sort_cols = []
        for c in keys:
            d[f"__k_{c}"] = d[c].isna()
            sort_cols += [f"__k_{c}", c]
        for c in floats:
            v = d[c].to_numpy(dtype="float64")
            with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                finite = np.isfinite(v) & (v != 0)
                scale = 10.0 ** (np.floor(np.log10(np.abs(np.where(finite, v, 1.0)))) - 9)
                r = np.where(finite, np.round(v / scale) * scale, v)
            d[f"__f_{c}"] = r
            d[f"__n_{c}"] = d[c].isna()
            sort_cols += [f"__n_{c}", f"__f_{c}"]
        d = d.sort_values(sort_cols, kind="mergesort", na_position="last").reset_index(drop=True)
        return d[cols]

    a, b = prep(ref), prep(got)
    key_diff_rows = 0
    moved = {}
    if keys:
        neq = np.zeros(len(a), dtype=bool)
        for c in keys:
            x, y = a[c], b[c]
            both_null = x.isna().to_numpy() & y.isna().to_numpy()
            eq = (x == y).fillna(False).to_numpy(dtype=bool) | both_null
            if (~eq).any():
                moved[c] = {"rows_differ": int((~eq).sum())}
            neq |= ~eq
        key_diff_rows = int(neq.sum())
    max_abs = max_rel = 0.0
    tol_fail = 0
    not_identical = 0
    for c in floats:
        x = a[c].to_numpy(dtype="float64")
        y = b[c].to_numpy(dtype="float64")
        nx, ny = np.isnan(x), np.isnan(y)
        null_mismatch = nx != ny
        both = ~nx & ~ny
        d = np.abs(x - y)
        scale = np.maximum(np.abs(x), np.abs(y))
        ok = (d <= ABS_FLOOR) | (d <= REL_TOL * scale)
        fail = null_mismatch | (both & ~ok)
        diff = both & (x != y)
        n_diff = int(diff.sum() + null_mismatch.sum())
        if n_diff:
            rel = np.where(scale > 0, d / np.where(scale > 0, scale, 1), 0)
            moved[c] = {"cells_differ": n_diff, "max_abs": float(d[both].max(initial=0)),
                        "max_rel": float(rel[both].max(initial=0)), "outside_tolerance": int(fail.sum())}
            max_abs = max(max_abs, moved[c]["max_abs"])
            max_rel = max(max_rel, moved[c]["max_rel"])
        tol_fail += int(fail.sum())
        not_identical += n_diff
    out.update({"key_rows_differ": key_diff_rows, "float_cells_differ": not_identical,
                "outside_tolerance": tol_fail, "max_abs": max_abs, "max_rel": max_rel, "moved": moved})
    if key_diff_rows or tol_fail:
        out["status"] = "MISS"
        out["reason"] = "keys or strings" if key_diff_rows else "numeric tolerance"
    elif not_identical:
        out["status"] = "within tolerance"
    else:
        out["status"] = "identical"
    return out


def compare_dirs(ref_dir: Path, got_dir: Path, tables: list[str] | None = None,
                 names: dict[str, str] | None = None, dates_as_midnight: bool = False) -> dict:
    names = names or {}
    tables = tables or sorted(p.stem for p in ref_dir.glob("*.parquet"))
    results = {}
    for t in tables:
        g = got_dir / f"{names.get(t, t)}.parquet"
        if not g.exists():
            results[t] = {"status": "MISS", "reason": "table not produced"}
            continue
        results[t] = compare_frames(_load(ref_dir / f"{t}.parquet", dates_as_midnight),
                                    _load(g, dates_as_midnight))
    return results


def markdown(results: dict, marked: set[str] = frozenset()) -> str:
    lines = ["| Table | Rows (ref / port) | Result | Largest relative difference | Columns that moved |",
             "|---|---|---|---|---|"]
    for t, r in results.items():
        name = f"`{t}`" + (" (parallel aggregation)" if t in marked else "")
        rows = f"{r.get('rows_ref', '')} / {r.get('rows_got', '')}"
        rel = f"{r['max_rel']:.1e}" if r.get("max_rel") else "0"
        moved = ", ".join(f"`{c}`" for c in r.get("moved", {})) or ""
        res = r["status"] + (f" ({r['reason']})" if r["status"] == "MISS" else "")
        lines.append(f"| {name} | {rows} | {res} | {rel} | {moved} |")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("reference", type=Path)
    p.add_argument("candidate", type=Path)
    p.add_argument("--tables")
    p.add_argument("--names", type=Path, help="JSON map from reference table name to candidate file name")
    p.add_argument("--dates-as-midnight", action="store_true",
                   help="treat a date and its midnight timestamp as equal (files exported through pandas)")
    p.add_argument("--json", type=Path)
    p.add_argument("--markdown", type=Path)
    a = p.parse_args()
    names = json.loads(a.names.read_text()) if a.names else None
    res = compare_dirs(a.reference, a.candidate, a.tables.split(",") if a.tables else None, names,
                       a.dates_as_midnight)
    if a.json:
        a.json.write_text(json.dumps(res, indent=1))
    md = markdown(res)
    if a.markdown:
        a.markdown.write_text(md + "\n")
    counts = pd.Series([r["status"] for r in res.values()]).value_counts().to_dict()
    print(md)
    print(counts)


if __name__ == "__main__":
    main()
