"""Run the pipeline's SQL sources on a local Spark session against a local copy of the landing volume.

Development check of the pipeline logic before a pipeline update: each streaming table and
materialized view in pipelines/ is evaluated in dependency order on Spark (same SQL dialect as
the pipeline, ANSI mode, UTC session time), written to Parquet, and each expectation is counted.
It does not replace the pipeline update; parity is reported on the tables the pipeline writes.
Requires pyspark matching the runtime's Spark minor version and a Java runtime.

Usage:
  python tests/parity/run_local_spark.py --landing runs/landing/files --pass pass1 --out runs/parity/local/pass1
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]
CREATE = re.compile(r"CREATE OR REFRESH (PRIVATE )?(STREAMING TABLE|MATERIALIZED VIEW) ([\w.]+)", re.S)
CONSTRAINT = re.compile(r"CONSTRAINT (\w+) EXPECT \((.*)\)(?: ON VIOLATION (FAIL UPDATE|DROP ROW))?,?\s*$")
REF = re.compile(r"\b(bronze|silver|gold)\.(\w+)")
READ_FILES = re.compile(r"STREAM read_files\('\$\{dfm\.landing_root\}/([\w/]+)/\$\{dfm\.pass\}', format => 'parquet'\)")


def statements(root: Path) -> list[dict]:
    out = []
    for path in sorted(root.rglob("*.sql")):
        buf: list[str] = []
        for line in path.read_text().splitlines():
            buf.append(line)
            if line.rstrip().endswith(";") and not line.lstrip().startswith("--"):
                text = "\n".join(buf)
                buf = []
                m = CREATE.search(text)
                if not m:
                    continue
                head, _, query = text[m.end():].partition("\nAS\n")
                cons = []
                for l in head.splitlines():
                    if l.startswith("COMMENT ") and not re.fullmatch(r"COMMENT '[^'\\]*'", l.strip()):
                        raise ValueError(f"{path}: comment is not a plain string literal: {l}")
                    c = CONSTRAINT.match(l.strip())
                    if c:
                        cons.append({"name": c.group(1), "expr": c.group(2), "action": c.group(3) or "warn"})
                name = m.group(3)
                out.append({"name": name, "kind": m.group(2), "private": bool(m.group(1)), "file": str(path.relative_to(REPO)),
                            "query": query.rstrip().rstrip(";"), "constraints": cons,
                            "refs": sorted({f"{a}.{b}" for a, b in REF.findall(query)} - {name})})
    return out


def local_name(name: str) -> str:
    return name.replace(".", "__")


def run(landing: Path, pass_name: str, out: Path) -> dict:
    from pyspark.sql import SparkSession

    spark = (SparkSession.builder.master("local[4]").appName("dfm-pipeline-local")
             .config("spark.sql.session.timeZone", "UTC").config("spark.sql.ansi.enabled", "true")
             .config("spark.sql.shuffle.partitions", "8").config("spark.driver.memory", "6g")
             .config("spark.ui.enabled", "false").config("spark.driver.host", "127.0.0.1")
             .config("spark.driver.bindAddress", "127.0.0.1").getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    out.mkdir(parents=True, exist_ok=True)
    pending = statements(REPO / "pipelines")
    done: set[str] = set()
    report = {}
    while pending:
        ready = [s for s in pending if all(r in done for r in s["refs"])]
        if not ready:
            raise RuntimeError(f"unresolved references: {[(s['name'], s['refs']) for s in pending]}")
        for s in ready:
            q = READ_FILES.sub(lambda m: f"parquet.`{(landing / m.group(1) / pass_name).as_posix()}`", s["query"])
            q = REF.sub(lambda m: f"{m.group(1)}__{m.group(2)}", q)
            t0 = time.time()
            df = spark.sql(q)
            path = out / f"{local_name(s['name'])}.parquet"
            pq.write_table(df.toArrow(), path)
            spark.read.parquet(path.as_posix()).createOrReplaceTempView(local_name(s["name"]))
            exp = {}
            for c in s["constraints"]:
                n = spark.sql(f"select count(*) from {local_name(s['name'])} "
                              f"where not coalesce({REF.sub(lambda m: m.group(1) + '__' + m.group(2), c['expr'])}, false)").first()[0]
                exp[c["name"]] = {"action": c["action"], "failing_rows": n}
            rows = pq.ParquetFile(path).metadata.num_rows
            report[s["name"]] = {"rows": rows, "seconds": round(time.time() - t0, 1), "expectations": exp,
                                 "private": s["private"], "file": s["file"]}
            bad = {k: v for k, v in exp.items() if v["failing_rows"]}
            print(f"  {s['name']:55s} {rows:>9,} rows  {report[s['name']]['seconds']:>6.1f}s"
                  + (f"  FAILING {bad}" if bad else ""))
            done.add(s["name"])
            pending.remove(s)
    spark.stop()
    (out / "_run.json").write_text(json.dumps(report, indent=1))
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--landing", type=Path, required=True, help="local copy of the landing volume root")
    p.add_argument("--pass", dest="pass_name", choices=["pass1", "pass2"], required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    run(a.landing.resolve(), a.pass_name, a.out.resolve())


if __name__ == "__main__":
    main()
