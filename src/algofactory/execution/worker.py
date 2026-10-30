"""Trusted image entrypoint. Never import generated code on the host."""

import base64
import gzip
import importlib.metadata
import importlib.util
import json
import os
import pickle
import platform
import resource
import time
from pathlib import Path

import numpy as np
import pandas as pd


def checked_features(frame, features, text_features):
    selected = frame[features]
    for name in text_features:
        if any(not isinstance(value, str) or not value.strip() for value in selected[name]):
            raise ValueError("Text features must be nonblank strings")
    return selected


def outputs(pipeline, data, classes):
    if not classes:
        predictions = np.asarray(pipeline.predict(data), dtype=float)
        if predictions.shape != (len(data),) or not np.isfinite(predictions).all():
            raise ValueError("invalid_regression_predictions")
        return predictions, np.empty((0,))
    predictions = np.asarray(pipeline.predict(data))
    probabilities = np.asarray(pipeline.predict_proba(data))
    if probabilities.shape != (len(data), len(classes)) or not np.array_equal(
        pipeline.classes_, classes
    ):
        raise ValueError("invalid_probability_interface")
    if (
        predictions.shape != (len(data),)
        or not np.isfinite(predictions).all()
        or not np.isfinite(probabilities).all()
    ):
        raise ValueError("invalid_prediction_shape_or_values")
    if (
        not set(np.unique(predictions)) <= set(classes)
        or not np.allclose(probabilities.sum(axis=1), 1, rtol=0, atol=1e-8)
        or (probabilities < 0).any()
        or (probabilities > 1).any()
    ):
        raise ValueError("invalid_probability_values")
    return predictions, probabilities


def evaluate(factory, train, evaluation, config):
    """Candidate sees training labels and evaluation features, never held-out labels."""
    text_features = config.get("text_features", [])
    features = config["numeric_features"] + config["categorical_features"] + text_features
    target, classes = config.get("target", "churn"), config.get("class_labels", [0, 1])
    regression = config.get("task_type") == "regression"
    multiclass = config.get("task_type") == "multiclass_classification"
    X = checked_features(train, features, text_features)
    E = checked_features(evaluation, features, text_features)
    y = train[target]
    if (
        (not regression and set(y.unique()) != set(classes))
        or (regression and (classes or not np.isfinite(y).all()))
        or target in evaluation.columns
        or "row_id" in features
    ):
        return {"status": "failed", "error_category": "worker_input_contract_mismatch"}
    pipeline = factory(config)
    for method in ("fit", "predict") if regression else ("fit", "predict", "predict_proba"):
        if not callable(getattr(pipeline, method, None)):
            return {"status": "failed", "error_category": "interface_missing_" + method}
    pipeline.fit(X, y)
    try:
        predictions, probabilities = outputs(pipeline, E, classes)
    except ValueError as exc:
        return {"status": "failed", "error_category": str(exc)}
    repeat_predictions, repeat_probabilities = predictions, probabilities
    missing_rejected = invalid_rejected = unseen_handled = False
    invalid_text_rejected = unseen_text_handled = False
    if config["stage"] == "validation":
        repeat = factory(config)
        repeat.fit(X, y)
        try:
            repeat_predictions, repeat_probabilities = outputs(repeat, E, classes)
        except ValueError as exc:
            return {"status": "failed", "error_category": str(exc)}
        try:
            pipeline.predict(checked_features(E.drop(columns=features[0]), features, text_features))
        except Exception:
            missing_rejected = True
        if text_features:
            rejected = []
            for bad_value in (None, 123, "", "  \t "):
                invalid = E.head(3).copy()
                invalid[text_features[0]] = bad_value
                try:
                    pipeline.predict(checked_features(invalid, features, text_features))
                    rejected.append(False)
                except (ValueError, TypeError):
                    rejected.append(True)
            invalid_text_rejected = all(rejected)
            unseen = E.head(3).copy()
            unseen[text_features[0]] = "zzunseentokenxyz"
            try:
                outputs(pipeline, checked_features(unseen, features, text_features), classes)
                unseen_text_handled = True
            except Exception:
                pass
        else:
            invalid = E.head(3).copy()
            invalid[features[0]] = "invalid-number"
            try:
                pipeline.predict(invalid)
            except Exception:
                invalid_rejected = True
            unseen = E.head(3).copy()
            if config["categorical_features"]:
                unseen[config["categorical_features"][0]] = "unseen-contract-fixture"
            try:
                outputs(pipeline, unseen, classes)
                unseen_handled = True
            except Exception:
                pass
    if not multiclass and not regression:
        probabilities, repeat_probabilities = probabilities[:, 1], repeat_probabilities[:, 1]
    result = {
        "status": "ok",
        "classes": classes,
        "row_ids": evaluation.row_id.astype(int).tolist(),
        "predictions": predictions.astype(float if regression else int).tolist(),
        "probabilities": probabilities.tolist(),
        "repeat_predictions": repeat_predictions.astype(float if regression else int).tolist(),
        "repeat_probabilities": repeat_probabilities.tolist(),
        "interface_checked": True,
        "missing_column_rejected": missing_rejected,
        "invalid_numeric_rejected": invalid_rejected,
        "unseen_category_handled": unseen_handled,
        "invalid_text_rejected": invalid_text_rejected,
        "unseen_text_handled": unseen_text_handled,
        "training_rows": len(train),
    }

    if config.get("persist_model") or config["stage"] == "prepare":
        result["model_payload"] = base64.b64encode(
            gzip.compress(pickle.dumps(pipeline, protocol=5), mtime=0)
        ).decode("ascii")
        result["model_environment"] = model_environment()
    return result


def model_environment():
    return {
        "python": platform.python_version(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "scikit-learn", "scipy", "joblib")
        },
    }


def predict_saved(config):
    # Only the approved container deserializes models; host verifies provenance and bytes.
    if config["model_environment"] != model_environment():
        raise ValueError("model_environment_mismatch")
    with gzip.open("/input/model.pkl.gz", "rb") as file:
        pipeline = pickle.load(file)
    frame = pd.read_csv("/input/evaluation_features.csv", keep_default_na=False)
    predicted, probabilities = outputs(
        pipeline, checked_features(frame, ["text"], ["text"]), config["class_labels"]
    )
    return {
        "status": "ok",
        "classes": config["class_labels"],
        "row_ids": frame.row_id.tolist(),
        "predictions": predicted.astype(int).tolist(),
        "probabilities": probabilities.tolist(),
        "model_environment": model_environment(),
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
        if config["stage"] == "predict":
            result = predict_saved(config)
        else:
            result = execute_candidate(config)
    except Exception as exc:
        result = {"status": "failed", "error_category": "worker_" + type(exc).__name__}
    result.update(
        schema_version=1,
        elapsed_seconds=time.monotonic() - started,
        peak_memory_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    )
    print(json.dumps(result, allow_nan=False, separators=(",", ":")))


def execute_candidate(config):
    specification = importlib.util.spec_from_file_location("candidate", "/input/candidate.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    factory = getattr(module, "build_pipeline", None)
    if not callable(factory):
        result = {"status": "failed", "error_category": "interface_missing_build_pipeline"}
    else:
        # Preserve literal strings such as 'NA'; the text boundary rejects actual empty values.
        text_task = bool(config.get("text_features"))
        train = pd.read_csv("/input/train.csv", keep_default_na=not text_task)
        evaluation = pd.read_csv("/input/evaluation_features.csv", keep_default_na=not text_task)
        result = evaluate(factory, train, evaluation, config)
    return result


if __name__ == "__main__":
    main()
