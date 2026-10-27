"""Console entry points for the monthly job's Python wheel tasks: dfm-train, dfm-promote, dfm-score, and
dfm-check-env (the runtime check run before training on a new cluster image).

Every entry point reads --catalog; train and promote read --experiment-root (MLflow experiments by
deployment target) and --job-run-id (the job run, which links the challenger run to its promotion);
promote reads --auto-promote and, outside a job, --run-id. Options accept hyphens or underscores, so the
job's keyword-argument form (--name=value) works.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from importlib.metadata import PackageNotFoundError, requires, version
from typing import Any

import pandas as pd

from .. import tasks

LOG = logging.getLogger("dfm")


def _flag(p: argparse.ArgumentParser, name: str, **kw: Any) -> None:
    p.add_argument(f"--{name}", f"--{name.replace('-', '_')}", dest=name.replace("-", "_"), **kw)


def _bool(v: str) -> bool:
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError(f"expected true or false, got {v!r}")


def parse(prog: str, argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog=prog)
    _flag(p, "catalog", required=True)
    _flag(p, "experiment-root", default="/Shared/dfm")
    _flag(p, "job-run-id", default=None)
    _flag(p, "run-id", default=None, help="promote: the challenger run, outside a job")
    _flag(p, "auto-promote", type=_bool, default=True)
    return p.parse_args(argv)


def setup(prog: str, argv: list[str] | None = None) -> tuple[argparse.Namespace, Any, Any]:
    from pyspark.sql import SparkSession

    from ..store import SparkTables, TableStore

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    args = parse(prog, argv)
    spark = SparkSession.builder.getOrCreate()
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    return args, spark, TableStore(SparkTables(spark, args.catalog))


def _version() -> str:
    try:
        return version("dfm")
    except PackageNotFoundError:
        return ""


def _dated(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        out[c] = pd.to_datetime(out[c]).dt.date
    return out


# ── train ───────────────────────────────────────────────────────────────────
def train(argv: list[str] | None = None) -> None:
    """Weekly reference model, the reference and S1 rungs, the selection rule; the S1 winner is logged as
    the challenger with its model."""
    import mlflow

    from .. import tracking

    args, spark, store = setup("dfm-train", argv)
    root = args.experiment_root.rstrip("/")
    mlflow.set_experiment(experiment_id=tracking.ensure_experiment(f"{root}/train"))
    job = str(args.job_run_id or "")
    t0 = time.time()
    tr = tasks.train(store)
    LOG.info("trained in %.0f s; selection %s", time.time() - t0, tr.selection)

    rows = {"feature_frame": store.write(tasks.frame_table(tr.frame), "gold", "feature_frame"),
            "backtest_predictions": store.write(_dated(pd.concat(
                [tasks.predictions(tr.tests[r]).assign(rung=r) for r in tasks.RUNGS], ignore_index=True), ["week"]),
                "gold", "backtest_predictions"),
            "weekly_backtest": store.write(_dated(tr.weekly_test, ["week"]), "gold", "weekly_backtest")}
    LOG.info("tables written %s", rows)

    docs = {f"metrics_{r}.json": tasks.metrics_document(tr.results[r]) for r in tasks.RUNGS}
    docs["weekly_metrics.json"] = tasks.weekly_metrics_document(tr.weekly_metrics)
    docs["selection.json"] = json.dumps(tr.selection, indent=1, default=float)
    docs["shap_S1.json"] = json.dumps(tr.shap, indent=1, default=float)
    hashes = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in docs.items()}
    with mlflow.start_run(run_name=f"train {job or 'manual'}") as parent:
        mlflow.set_tags({"job_run_id": job, "catalog": args.catalog, "dfm_version": _version(),
                         "selected_rung": tr.selection["chosen"]})
        mlflow.log_params({"rungs": ",".join(tasks.RUNGS), "n_trials": 12, "sampler": "TPE", "sampler_seed": 42,
                           "model_seed": 42, "candidates": "Linear,RandomForest,XGBoost"})
        t1 = time.time()
        tracking.log_inputs(spark, args.catalog, tasks.INPUT_TABLES)
        LOG.info("input lineage logged in %.0f s", time.time() - t1)
        tracking.log_text_artifacts(docs)
        mlflow.log_dict(hashes, "sha256.json")
        wm = tr.weekly_metrics
        mlflow.log_metrics({"weekly_test_wape": wm["overall"]["model"], "weekly_baseline_wape": wm["overall"]["baseline"],
                            **{f"val_wape_{r}": w for r, w in tr.selection["validation_wape"].items()},
                            "train_seconds": time.time() - t0, "rows_feature_frame": rows["feature_frame"]})
        for rung in tasks.RUNGS:
            res = tr.results[rung]
            for kind, c in res["candidates"].items():
                with mlflow.start_run(run_name=f"{rung} {kind}", nested=True):
                    winner = kind == res["winner"]
                    challenger = rung == tasks.POLICY_RUNG and winner
                    mlflow.set_tags({"rung": rung, "candidate": kind, "winner": str(winner).lower(),
                                     "challenger": str(challenger).lower(), "job_run_id": job})
                    mlflow.log_params({f"param_{k}": v for k, v in c["params"].items()})
                    mlflow.log_metrics({"val_wape": c["val_wape"], "test_wape": c["test_wape"],
                                        "test_wape_corrected": c["test_wape_corrected"],
                                        **{f"bias_factor_{s}": v for s, v in c["bias_factors"].items()}})
                    mlflow.log_dict(c["bias_factors"], "bias_factors.json")
                    mlflow.log_dict(json.loads(json.dumps(res["simple"], default=float)), "simple_methods.json")
                    if winner:
                        mlflow.log_dict(json.loads(json.dumps(res["scores_winner"], default=float)), "scores.json")
                    if challenger:
                        mlflow.log_dict(json.loads(json.dumps(tr.shap, default=float)), "shap_summary.json")
                        model = tracking.DemandModel(res["models"][kind], kind, res["features"],
                                                     tasks.rung_cap(tr.frame, rung), rung, docs[f"metrics_{rung}.json"])
                        tracking.log_model(model, tasks.test_rows(tr.frame, rung))
        LOG.info("parent run %s; artifact sha256 %s", parent.info.run_id, hashes)


# ── promote ─────────────────────────────────────────────────────────────────
def promote(argv: list[str] | None = None) -> None:
    """Register the challenger, evaluate the gates and move the champion alias when allowed."""
    from .. import registry as R

    args, spark, store = setup("dfm-promote", argv)
    reg = R.MlflowRegistry()
    run_id = args.run_id
    if run_id is None:
        if not args.job_run_id:
            raise ValueError("either a run id or the job run id is required")
        run_id = reg.find_challenger(f"{args.experiment_root.rstrip('/')}/train", str(args.job_run_id))
    tags = reg.run_tags(run_id)
    parent = tags["mlflow.parentRunId"]
    results = {r: json.loads(reg.run_text(parent, f"metrics_{r}.json")) for r in tasks.RUNGS}
    name = R.model_name(args.catalog)
    ver, reused = R.register_or_reuse(reg, run_id, name)
    LOG.info("%s version %s from run %s", "reusing" if reused else "registered", ver, run_id)
    identity = (run_id, tags.get("candidate", ""), tags.get("rung", ""), str(args.job_run_id or ""), _version())
    for k, v in zip(R.IDENTITY_TAGS, identity, strict=True):
        reg.set_tag(name, ver, R.tag_key(k), v)
    model = reg.load(name, ver)
    frame = store.read_output("gold", "feature_frame")
    frame["week"] = pd.to_datetime(frame["week"])
    pred = store.read_output("gold", "backtest_predictions")
    pred = pred[pred["rung"] == tasks.POLICY_RUNG]
    gates = R.evaluate_gates(model, tags, results, frame, pred, store.mart("item_lifecycle"),
                             tasks.weeks_of(store.mart("consumption_weekly")))
    for g in gates:
        LOG.info("gate %s %s: %s", g.name, "pass" if g.passed else "fail", g.detail)
    status = R.decide(reg, name, ver, gates, args.auto_promote)
    champion = reg.alias_version(name, R.CHAMPION)
    LOG.info("version %s %s; champion is version %s", ver, status, champion)
    if champion is None:
        raise RuntimeError(f"{name} has no {R.CHAMPION} version; version {ver} is {status}")


# ── score ───────────────────────────────────────────────────────────────────
def score(argv: list[str] | None = None) -> None:
    """The planning-window reorder schedule from the champion: gold.reorder_schedule, gold.reorder_queue
    and gold.policy_retrains."""
    import mlflow

    from .. import registry as R
    from .. import tracking

    args, spark, store = setup("dfm-score", argv)
    reg = R.MlflowRegistry()
    name = R.model_name(args.catalog)
    ver = reg.alias_version(name, R.CHAMPION)
    if ver is None:
        raise RuntimeError(f"{name} has no {R.CHAMPION} version")
    model = mlflow.pyfunc.load_model(f"models:/{name}@{R.CHAMPION}").unwrap_python_model()
    label = f"{R.MODEL}/{ver}"
    t0 = time.time()
    doc, retrains, _ = tasks.score(store, model.result, model.predict_uncovered)
    LOG.info("scored with %s in %.0f s", label, time.time() - t0)
    sched = tasks.schedule_rows(doc, label)
    rows = {"reorder_schedule": store.write(sched, "gold", "reorder_schedule"),
            "reorder_queue": store.write(tasks.queue_rows(sched), "gold", "reorder_queue"),
            "policy_retrains": store.write(tasks.retrain_rows(retrains), "gold", "policy_retrains")}
    texts = {"rop_schedule.json": tasks.schedule_document_text(doc), "retrain_log.json": json.dumps(retrains, indent=1)}
    root = args.experiment_root.rstrip("/")
    mlflow.set_experiment(experiment_id=tracking.ensure_experiment(f"{root}/score"))
    with mlflow.start_run(run_name=f"score {args.job_run_id or 'manual'}"):
        mlflow.set_tags({"job_run_id": str(args.job_run_id or ""), "model_version": label, "catalog": args.catalog,
                         "dfm_version": _version()})
        tracking.log_text_artifacts(texts)
        mlflow.log_dict({k: hashlib.sha256(v.encode()).hexdigest() for k, v in texts.items()}, "sha256.json")
        mlflow.log_metrics({f"rows_{k}": v for k, v in rows.items()} | {"score_seconds": time.time() - t0})
    LOG.info("tables written %s", rows)


# ── runtime check ───────────────────────────────────────────────────────────
def check_environment(argv: list[str] | None = None) -> None:
    """Imports the model's libraries and checks their versions against the wheel's pins, reads tables to
    pandas through Spark (toPandas and toArrow), and prints a digest of every model input frame for
    comparison with the same frames built locally from the exports."""
    import importlib

    args, spark, store = setup("dfm-check-env", argv)
    pins = {}
    for r in requires("dfm") or []:
        if "==" in r:
            n, v = r.split("==")
            pins[n.strip()] = v.strip()
    report: dict[str, Any] = {"pins": {}, "imports": {}}
    for n, want in pins.items():
        try:
            got = version(n)
        except PackageNotFoundError:
            got = None
        report["pins"][n] = {"pinned": want, "installed": got, "ok": got == want}
    for mod in ["numpy", "pandas", "scipy", "sklearn", "joblib", "threadpoolctl", "xgboost", "optuna", "shap",
                "mlflow", "pyarrow", "pyspark"]:
        try:
            m = importlib.import_module(mod)
            report["imports"][mod] = getattr(m, "__version__", "?")
        except Exception as e:  # noqa: BLE001  (reported, then failed below)
            report["imports"][mod] = f"FAILED {type(e).__name__}: {e}"
    t = spark.table(f"{args.catalog}.gold.dim_week")
    pdf = t.toPandas()
    report["topandas"] = {"rows": len(pdf), "dtypes": {c: str(d) for c, d in pdf.dtypes.items()}}
    report["toarrow"] = {"rows": t.toArrow().num_rows}
    rt = spark.createDataFrame(pd.DataFrame({"x": [1.5, float("nan")], "d": pd.to_datetime(["2026-01-05", None]).date}))
    report["createdataframe"] = [list(r) for r in rt.collect()]
    digests = {}
    for name in tasks.MART_NAMES:
        digests[f"mart {name}"] = _digest(store.mart(name))
    digests["crosswalk"] = hashlib.sha256(json.dumps(sorted(store.crosswalk().items())).encode()).hexdigest()
    for s, tb in tasks.EXTRACT_NAMES:
        digests[f"extract {s}.{tb}"] = _digest(store.extract(s, tb))
    report["digests"] = digests
    print(json.dumps(report, indent=1, default=str))
    bad = [n for n, p in report["pins"].items() if not p["ok"]] + \
        [m for m, v in report["imports"].items() if str(v).startswith("FAILED")]
    if bad:
        raise RuntimeError(f"runtime check failed: {bad}")


def _digest(df: pd.DataFrame) -> str:
    h = hashlib.sha256()
    h.update(json.dumps([[c, str(d)] for c, d in df.dtypes.items()]).encode())
    h.update(pd.util.hash_pandas_object(df, index=True).to_numpy().tobytes())
    return h.hexdigest()
