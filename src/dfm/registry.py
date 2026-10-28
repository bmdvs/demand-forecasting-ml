"""Champion and challenger promotion for the demand model (Unity Catalog model <catalog>.ml.demand_models).

The train task logs a challenger run. The promote task registers the challenger's model as a new version
(or reuses the version already registered from that run, when the task is repaired), evaluates the
gates and moves the champion alias only when every gate passes and auto_promote is on:
  selection       the challenger is the selection rules' pick from the run's logged results
  parity          the registered model scores the 2025 test rows as the train task did, within 1e-9
  completeness    every item in use for 13 weeks or more at the planning-window start has a forecast
  bias            the champion's own planning-window forecasts (gold.reorder_schedule) against the actuals
                  in the current tables, as the monitor scores them: on the latest month with 80% of its
                  forecasts matured, corrected bias within 10% for every pattern with 150 scored
                  forecasts; fails closed when there is no champion schedule or no such month
  beats_baseline  validation WAPE on total demand below the best simple method chosen by pattern
Every gate result is a tag on the version, with keys free of Unity Catalog's reserved characters; a
rejected version leaves the champion where it is.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
import pandas as pd

from . import tasks
from . import training as T

MODEL = "demand_models"
CHAMPION = "champion"
BIAS_LIMIT = 0.10
RESERVED_TAG_CHARACTERS = frozenset(".=><%&?\\")
TAG_VALUE_MAX = 256
IDENTITY_TAGS = ("source_run_id", "candidate", "rung", "job_run_id", "dfm_version")


def tag_key(key: str) -> str:
    """A model version tag key Unity Catalog accepts: no reserved characters."""
    bad = sorted(set(key) & RESERVED_TAG_CHARACTERS)
    if not key or bad:
        raise ValueError(f"tag key {key!r} contains reserved characters {bad}")
    return key


def tag_value(value: str) -> str:
    """A model version tag value within Unity Catalog's length limit (longer values end in '...')."""
    s = str(value)
    return s if len(s) <= TAG_VALUE_MAX else s[: TAG_VALUE_MAX - 3] + "..."


def model_name(catalog: str) -> str:
    return f"{catalog}.ml.{MODEL}"


@dataclass
class Gate:
    name: str
    passed: bool
    detail: str
    tags: dict[str, str] = field(default_factory=dict)


def gate_selection(run_tags: dict[str, str], results: dict) -> Gate:
    """The run's rung and candidate are the selection rules' pick from the logged rung results."""
    rung, kind = tasks.selection_pick(results)
    ok = run_tags.get("challenger") == "true" and (run_tags.get("rung"), run_tags.get("candidate")) == (rung, kind)
    v = {r: results[r]["candidates"][results[r]["winner"]]["val_wape"] for r in results}
    detail = (f"run {run_tags.get('rung')} {run_tags.get('candidate')}, rule pick {rung or 'none'} {kind}; "
              f"validation WAPE " + ", ".join(f"{r} {w:.6f}" for r, w in v.items()))
    return Gate("selection", ok, detail)


def gate_parity(model: Any, test: pd.DataFrame, train_pred: pd.DataFrame) -> Gate:
    """The registered model's uncovered forecasts on the 2025 test rows against the train task's."""
    col = f"predu_{model.kind}"
    m = test[["item", "t"]].assign(reg=model.predict_uncovered(test)).merge(
        train_pred[["item", "t", col]], on=["item", "t"], how="outer", indicator=True)
    unmatched = int((m["_merge"] != "both").sum())
    both = m[m["_merge"] == "both"]
    differ = int((~tasks.float_close(both["reg"], both[col])).sum())
    exact = int((both["reg"].to_numpy() == both[col].to_numpy()).sum())
    ok = unmatched == 0 and differ == 0 and len(both) == len(train_pred)
    return Gate("parity", ok, f"rows {len(train_pred)}, unmatched {unmatched}, outside 1e-9 {differ}, identical {exact}",
                {"parity_rows": str(len(train_pred)), "parity_identical": str(exact)})


def gate_completeness(model: Any, frame: pd.DataFrame, universe: list, t_fwd: int) -> Gate:
    """A finite, non-negative forecast at the planning-window start for every item in the universe."""
    cur = frame[frame["is_reference_row"] & (frame["t"] == t_fwd)]
    pu = model.predict_uncovered(cur)
    have = set(cur.loc[np.isfinite(pu) & (pu >= 0), "item"])
    missing = sorted(set(universe) - have)
    return Gate("completeness", not missing,
                f"items in use 13 weeks or more {len(universe)}, with a forecast {len(set(universe) & have)}, "
                f"missing {len(missing)}{(': ' + ', '.join(missing[:20])) if missing else ''}",
                {"completeness_items": str(len(universe)), "completeness_missing": str(len(missing))})


def gate_bias(schedule: pd.DataFrame | None, champion: str | None, frame: pd.DataFrame,
              weeks: pd.DatetimeIndex) -> Gate:
    """Corrected bias, (forecast - actual) / actual, by demand pattern on the champion's issued
    planning-window forecasts, for the latest month the monitor would judge on accuracy."""
    from . import monitoring as M

    if champion is None:
        return Gate("bias", False, "no champion: fails closed")
    if schedule is None or schedule.empty:
        return Gate("bias", False, "no issued schedule: fails closed")
    issued_by = sorted(set(schedule["model_version"]))
    if issued_by != [champion]:
        return Gate("bias", False, f"schedule issued by {', '.join(issued_by)}, champion is {champion}: fails closed",
                    {"bias_schedule": ",".join(issued_by)})
    months = M.month_bias(M.live_forecasts(M.table_entries(schedule), frame, weeks))
    seen = ", ".join(f"{m.period} {m.n_scored}/{m.n_forecasts}" for m in months)
    matured = [m for m in months if m.matured]
    if not matured:
        return Gate("bias", False, f"no month with {M.MATURED:.0%} of its forecasts matured ({seen}): fails closed",
                    {"bias_schedule": champion})
    m = matured[-1]
    by = m.pattern_bias
    ok = bool(by) and all(abs(v) <= BIAS_LIMIT for v in by.values())
    detail = (f"{champion} schedule, {m.period}, {m.n_scored} of {m.n_forecasts} scored: "
              + ", ".join(f"{k} {v:+.4f}" for k, v in sorted(by.items())) + f" (limit {BIAS_LIMIT:.2f})")
    tags = {"bias_schedule": champion, "bias_month": m.period, "bias_months_scored": seen,
            **{f"bias_{k}": f"{v:+.4f}" for k, v in sorted(by.items())}}
    return Gate("bias", ok, detail, tags)


def gate_beats_baseline(result: dict, val: pd.DataFrame) -> Gate:
    """The winner's validation WAPE on total demand against the best of the four simple methods,
    chosen by demand pattern on the same rows."""
    kind = result["winner"]
    model_wape = float(result["candidates"][kind]["val_wape"])
    best, sel = T._best_by_segment(val, ["ma4", "ma13", "ma52", "snaive"])
    base = float(T._wape(val["target"], best))
    return Gate("beats_baseline", model_wape < base,
                f"validation WAPE {model_wape:.6f} against best simple by pattern {base:.6f} ({sel})",
                {"beats_baseline_model": f"{model_wape:.6f}", "beats_baseline_simple": f"{base:.6f}"})


class Registry(Protocol):
    def find_challenger(self, experiment: str, job_run_id: str) -> str: ...
    def run_tags(self, run_id: str) -> dict[str, str]: ...
    def run_text(self, run_id: str, path: str) -> str: ...
    def register(self, run_id: str, name: str) -> str: ...
    def find_version(self, name: str, run_id: str) -> str | None: ...
    def load(self, name: str, version: str) -> Any: ...
    def set_tag(self, name: str, version: str, key: str, value: str) -> None: ...
    def delete_tag(self, name: str, version: str, key: str) -> None: ...
    def set_alias(self, name: str, alias: str, version: str) -> None: ...
    def alias_version(self, name: str, alias: str) -> str | None: ...


class MlflowRegistry:
    """The Unity Catalog model registry and the workspace tracking server."""

    def __init__(self) -> None:
        import mlflow
        from mlflow import MlflowClient

        mlflow.set_registry_uri("databricks-uc")
        self.mlflow = mlflow
        self.client = MlflowClient(registry_uri="databricks-uc")

    def find_challenger(self, experiment: str, job_run_id: str) -> str:
        exp = self.client.get_experiment_by_name(experiment)
        if exp is None:
            raise RuntimeError(f"experiment {experiment} not found")
        runs = self.client.search_runs([exp.experiment_id],
                                       filter_string=f"tags.challenger = 'true' and tags.job_run_id = '{job_run_id}'",
                                       order_by=["attributes.start_time DESC"], max_results=1)
        if not runs:
            raise RuntimeError(f"no challenger run in {experiment} for job run {job_run_id}")
        return runs[0].info.run_id

    def run_tags(self, run_id: str) -> dict[str, str]:
        return dict(self.client.get_run(run_id).data.tags)

    def run_text(self, run_id: str, path: str) -> str:
        return self.mlflow.artifacts.load_text(f"runs:/{run_id}/{path}")

    def run_frame(self, run_id: str, path: str) -> pd.DataFrame:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            return pd.read_parquet(self.mlflow.artifacts.download_artifacts(f"runs:/{run_id}/{path}", dst_path=d))

    def version_run(self, name: str, version: str) -> str:
        """The run a model version was registered from."""
        return str(self.client.get_model_version(name, version).run_id)

    def latest_issue(self, experiment: str, exclude_job_run_id: str) -> dict | None:
        """The latest finished score run outside the given job run: the schedule in force before it."""
        exp = self.client.get_experiment_by_name(experiment)
        if exp is None:
            return None
        for r in self.client.search_runs([exp.experiment_id], filter_string="attributes.status = 'FINISHED'",
                                         order_by=["attributes.start_time DESC"], max_results=50):
            if exclude_job_run_id and r.data.tags.get("job_run_id", "") == exclude_job_run_id:
                continue
            return {"run_id": r.info.run_id, "job_run_id": r.data.tags.get("job_run_id", ""),
                    "model_version": r.data.tags["model_version"]}
        return None

    def register(self, run_id: str, name: str) -> str:
        return str(self.mlflow.register_model(f"runs:/{run_id}/model", name).version)

    def find_version(self, name: str, run_id: str) -> str | None:
        try:
            found = [int(v.version) for v in self.client.search_model_versions(f"name='{name}'") if v.run_id == run_id]
        except Exception:  # noqa: BLE001  (a model not yet created has no versions)
            return None
        return str(min(found)) if found else None

    def load(self, name: str, version: str) -> Any:
        return self.mlflow.pyfunc.load_model(f"models:/{name}/{version}").unwrap_python_model()

    def set_tag(self, name: str, version: str, key: str, value: str) -> None:
        self.client.set_model_version_tag(name, version, key, value)

    def delete_tag(self, name: str, version: str, key: str) -> None:
        try:
            self.client.delete_model_version_tag(name, version, key)
        except Exception:  # noqa: BLE001  (the tag is absent)
            return

    def set_alias(self, name: str, alias: str, version: str) -> None:
        self.client.set_registered_model_alias(name, alias, version)

    def alias_version(self, name: str, alias: str) -> str | None:
        try:
            return str(self.client.get_model_version_by_alias(name, alias).version)
        except Exception:  # noqa: BLE001  (no version holds the alias)
            return None


def decide(registry: Registry, name: str, version: str, gates: list[Gate], auto_promote: bool) -> str:
    """Tag the version with every gate and move the champion alias when all pass and auto_promote is on."""
    failed = [g.name for g in gates if not g.passed]
    for g in gates:
        registry.set_tag(name, version, tag_key(f"gate_{g.name}"), "pass" if g.passed else "fail")
        registry.set_tag(name, version, tag_key(f"gate_{g.name}_detail"), tag_value(g.detail))
        for k, v in g.tags.items():
            registry.set_tag(name, version, tag_key(k), tag_value(v))
    if failed:
        registry.set_tag(name, version, tag_key("failed_gates"), tag_value(",".join(failed)))
    else:
        registry.delete_tag(name, version, "failed_gates")
    if not auto_promote:
        status = "for_review"
    elif failed:
        status = "rejected"
    else:
        registry.set_alias(name, CHAMPION, version)
        status = "promoted"
    registry.set_tag(name, version, tag_key("status"), status)
    return status


def register_or_reuse(registry: Registry, run_id: str, name: str) -> tuple[str, bool]:
    """The version registered from this run, if one exists (a repaired promote task), otherwise a new one."""
    found = registry.find_version(name, run_id)
    if found is not None:
        return found, True
    return registry.register(run_id, name), False


def evaluate_gates(model: Any, run_tags: dict[str, str], results: dict, frame: pd.DataFrame,
                   pred: pd.DataFrame, lifecycle: pd.DataFrame, weeks: pd.DatetimeIndex,
                   schedule: pd.DataFrame | None, champion: str | None) -> list[Gate]:
    from . import config as C
    wk = tasks.week_indices(weeks)
    test = tasks.test_rows(frame, tasks.POLICY_RUNG)
    f, cold = T._rows(frame, tasks.POLICY_RUNG)
    val = f[(f["split"] == "val") & ~cold]
    return [
        gate_selection(run_tags, results),
        gate_parity(model, test, pred),
        gate_completeness(model, frame, tasks.completeness_universe(lifecycle, C.FORWARD_START), wk["fwd"]),
        gate_bias(schedule, champion, frame, weeks),
        gate_beats_baseline(results[tasks.POLICY_RUNG], val),
    ]
