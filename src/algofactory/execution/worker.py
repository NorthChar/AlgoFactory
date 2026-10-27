"""Trusted image entrypoint. Never import generated code on the host."""

import importlib.util
import json
import os
import resource
import time
from pathlib import Path

import numpy as np
import pandas as pd


def evaluate(factory, train, evaluation, config):
    """The factory sees feature names/seed only; evaluation labels are absent."""
    features = config["numeric_features"] + config["categorical_features"]
    X, y, E = train[features], train["churn"], evaluation[features]
    pipeline = factory(config)
    for method in ("fit", "predict", "predict_proba"):
        if not callable(getattr(pipeline, method, None)):
            return {"status": "failed", "error_category": "interface_missing_" + method}
    pipeline.fit(X, y)
    predictions = np.asarray(pipeline.predict(E))
    probability_matrix = np.asarray(pipeline.predict_proba(E))
    if probability_matrix.shape != (len(E), 2) or not np.array_equal(pipeline.classes_, [0, 1]):
        return {"status": "failed", "error_category": "invalid_probability_interface"}
    probabilities = probability_matrix[:, 1]
    if (
        predictions.shape != (len(E),)
        or not np.isfinite(predictions).all()
        or not np.isfinite(probability_matrix).all()
    ):
        return {"status": "failed", "error_category": "invalid_prediction_shape_or_values"}
    if (
        not set(np.unique(predictions)) <= {0, 1}
        or not np.allclose(probability_matrix.sum(axis=1), 1)
        or (probability_matrix < 0).any()
        or (probability_matrix > 1).any()
    ):
        return {"status": "failed", "error_category": "invalid_probability_values"}
    repeat_predictions, repeat_probabilities = predictions, probabilities
    missing_rejected = invalid_rejected = unseen_handled = False
    if config["stage"] == "validation":
        repeat = factory(config)
        repeat.fit(X, y)
        repeat_predictions = np.asarray(repeat.predict(E))
        repeat_probabilities = np.asarray(repeat.predict_proba(E))[:, 1]
        try:
            pipeline.predict(E.drop(columns=features[0]))
        except Exception:
            missing_rejected = True
        invalid = E.head(3).copy()
        invalid[features[0]] = "invalid-number"
        try:
            pipeline.predict(invalid)
        except Exception:
            invalid_rejected = True
        unseen = E.head(3).copy()
        unseen[config["categorical_features"][0]] = "unseen-contract-fixture"
        try:
            unseen_handled = bool(np.isfinite(pipeline.predict_proba(unseen)).all())
        except Exception:
            pass
    return {
        "status": "ok",
        "row_ids": evaluation.row_id.astype(int).tolist(),
        "predictions": predictions.astype(int).tolist(),
        "probabilities": probabilities.tolist(),
        "repeat_predictions": repeat_predictions.astype(int).tolist(),
        "repeat_probabilities": repeat_probabilities.tolist(),
        "interface_checked": True,
        "missing_column_rejected": missing_rejected,
        "invalid_numeric_rejected": invalid_rejected,
        "unseen_category_handled": unseen_handled,
        "training_rows": len(train),
    }


def main():
    started = time.monotonic()
    if (
        os.environ.get("ALGOFACTORY_SANDBOX") != "1"
        or os.getuid() == 0
        or not Path("/proc/self/status").is_file()
    ):
        raise SystemExit("This entrypoint requires the approved non-root Linux sandbox")
    try:
        config = json.loads(Path("/input/config.json").read_text())
        specification = importlib.util.spec_from_file_location("candidate", "/input/candidate.py")
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        factory = getattr(module, "build_pipeline", None)
        if not callable(factory):
            result = {"status": "failed", "error_category": "interface_missing_build_pipeline"}
        else:
            train = pd.read_csv("/input/train.csv")
            evaluation = pd.read_csv("/input/evaluation_features.csv")
            result = evaluate(factory, train, evaluation, config)
    except Exception as exc:
        result = {"status": "failed", "error_category": "worker_" + type(exc).__name__}
    result.update(
        schema_version=1,
        elapsed_seconds=time.monotonic() - started,
        peak_memory_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    )
    print(json.dumps(result, allow_nan=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
