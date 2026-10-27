"""MLflow tracking for the train and score tasks, and the registered model's Python wrapper.

The registered model wraps the S1 winner fitted on train plus validation, with its feature list, the
forecast cap and its rung result (the metrics document the reorder policy reads). predict returns the
uncovered-demand forecast over the horizon, on one thread, as training scored it.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import mlflow
import pandas as pd

from . import training as T

PIP_REQUIREMENTS = ["numpy==2.5.4", "pandas==2.3.3", "scipy==1.18.1", "scikit-learn==1.9.1", "joblib==1.6.0",
                    "threadpoolctl==3.7.0", "xgboost==3.4.1"]


class DemandModel(mlflow.pyfunc.PythonModel):
    def __init__(self, estimator: Any, kind: str, features: list, cap: float, rung: str, result_json: str) -> None:
        self.estimator, self.kind, self.features, self.cap = estimator, kind, list(features), float(cap)
        self.rung, self.result_json = rung, result_json

    @property
    def result(self) -> dict:
        return json.loads(self.result_json)

    def predict_uncovered(self, frame: pd.DataFrame):
        return T._predict(self.kind, self.estimator, frame[self.features].astype(float), self.cap)

    def predict(self, context: Any, model_input: pd.DataFrame, params: dict | None = None):
        return self.predict_uncovered(model_input)


def ensure_experiment(path: str) -> str:
    """The experiment's id, creating its workspace folder and the experiment when missing."""
    parent = path.rsplit("/", 1)[0]
    try:
        from databricks.sdk import WorkspaceClient
        WorkspaceClient().workspace.mkdirs(parent)
    except Exception:  # noqa: BLE001  (outside a workspace the tracking server owns the namespace)
        pass
    exp = mlflow.get_experiment_by_name(path)
    return exp.experiment_id if exp else mlflow.create_experiment(path)


def log_text_artifacts(files: dict[str, str]) -> None:
    with tempfile.TemporaryDirectory() as d:
        for name, text in files.items():
            p = Path(d) / name
            p.write_text(text)
            mlflow.log_artifact(str(p))


def log_inputs(spark: Any, catalog: str, tables: dict[str, str]) -> None:
    """Input lineage: each table read, by name (materialized views cannot be read by load_delta)."""
    for full in tables.values():
        name = f"{catalog}.{full}"
        ds = mlflow.data.from_spark(spark.table(name), table_name=name)
        mlflow.log_input(ds, context="training")


def log_model(model: DemandModel, example: pd.DataFrame) -> None:
    from mlflow.models import infer_signature
    X = example[model.features].astype(float)
    sig = infer_signature(X, model.predict_uncovered(X))
    mlflow.pyfunc.log_model(name="model", python_model=model, signature=sig, pip_requirements=PIP_REQUIREMENTS)
