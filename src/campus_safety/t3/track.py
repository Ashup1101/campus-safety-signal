"""Log T3-lite runs to MLflow: a local file store under data/mlruns (gitignored).

MLflow 3 keeps the file store in maintenance mode and mlflow-skinny has no SQL store; the opt-in
below keeps experiment tracking free of a server or database.
"""

import os
from collections.abc import Iterable, Mapping
from pathlib import Path

TRACKING = Path("data", "mlruns")
EXPERIMENT = "t3-lite"


def _flat(values: Mapping[str, object], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in values.items():
        name = f"{prefix}{key}"
        if isinstance(value, Mapping):
            flat |= _flat(value, f"{name}.")
        else:
            flat[name] = str(value)
    return flat


def log_run(
    name: str,
    params: Mapping[str, object],
    metrics: Mapping[str, float],
    artifacts: Iterable[Path] = (),
    tracking: Path | None = None,
) -> str:
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow

    tracking = tracking or TRACKING
    tracking.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(tracking.resolve().as_uri())
    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name=name) as run:
        mlflow.log_params(_flat(params))
        mlflow.log_metrics(dict(metrics))
        for path in artifacts:
            mlflow.log_artifact(str(path))
    return str(run.info.run_id)


def kaggle_metrics(metrics: Mapping[str, Mapping[str, Mapping[str, float]]]) -> dict[str, float]:
    """metrics.json from the notebook ({model: {split: {name: value}}}) as flat MLflow metrics."""
    return {
        f"{model}.{split}.{name}": float(value)
        for model, splits in metrics.items()
        for split, values in splits.items()
        for name, value in values.items()
    }
