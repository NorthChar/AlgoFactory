"""Trusted reference calibration uses training/validation only, then freezes rules."""

import hashlib
import importlib.metadata
import json
import math
from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from algofactory.datasets import (
    CATEGORICAL,
    FEATURES,
    NUMERIC,
    sha256_file,
    verify_dataset,
    write_json,
)
from algofactory.knowledge.store import canonical
from algofactory.workflow_models import WorkflowFailure


def reference_pipeline(seed: int):
    """Repository-owned reference, never loaded from a generated file."""
    numeric = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
    categorical = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("encode", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    return Pipeline(
        [
            (
                "preprocess",
                ColumnTransformer(
                    [("numeric", numeric, NUMERIC), ("categorical", categorical, CATEGORICAL)]
                ),
            ),
            ("model", LogisticRegression(max_iter=500, random_state=seed)),
        ]
    )


def classification_metrics(labels, predictions, probabilities) -> dict[str, float]:
    return {
        "f1": float(f1_score(labels, predictions, zero_division=0)),
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
    }


def calibrate(directory: Path, protocol_path: Path) -> dict:
    manifest = verify_dataset(directory)
    if protocol_path.exists():
        return load_protocol(protocol_path, manifest)
    if manifest.get("task_profile") == "regression":
        from algofactory.regression import calibrate_regression

        return calibrate_regression(directory, protocol_path, manifest)
    if manifest.get("task_profile") == "banking77":
        return calibrate_text(directory, protocol_path, manifest)
    train = pd.read_csv(directory / "train.csv")
    validation = pd.read_csv(directory / "validation_features.csv")
    labels = pd.read_csv(directory / "validation_labels.csv")
    reference = reference_pipeline(manifest["seed"])
    reference.fit(train[FEATURES], train.churn)
    scores = classification_metrics(
        labels.churn,
        reference.predict(validation[FEATURES]),
        reference.predict_proba(validation[FEATURES])[:, 1],
    )
    if scores["roc_auc"] < 0.65 or scores["f1"] < 0.55:
        raise WorkflowFailure("baseline_below_minimum")
    # Fixed rule chosen before viewing any test predictions or scores.
    thresholds = {
        name: max(0.5, math.floor((value - 0.05) * 100) / 100) for name, value in scores.items()
    }
    protocol = {
        "schema_version": 1,
        "task_type": "binary_classification",
        "seed": manifest["seed"],
        "data_fingerprint": manifest["data_fingerprint"],
        "split_id": manifest["split_id"],
        "baseline": {
            "algorithm": "LogisticRegression",
            "validation_metrics": scores,
            "calibrator_sha256": sha256_file(Path(__file__)),
            "sklearn_version": importlib.metadata.version("scikit-learn"),
        },
        "threshold_rule": "max(0.50, floor((validation_baseline - 0.05)*100)/100)",
        "thresholds": thresholds,
        "probability_threshold": 0.5,
        "repeat_tolerance": 1e-12,
        "test_used_for_calibration": False,
    }
    protocol["config_hash"] = hashlib.sha256(canonical(protocol).encode()).hexdigest()
    write_json(protocol_path, protocol)
    return protocol


def load_protocol(path: Path, manifest: dict) -> dict:
    protocol = json.loads(path.read_text())
    without_hash = {k: v for k, v in protocol.items() if k != "config_hash"}
    if hashlib.sha256(canonical(without_hash).encode()).hexdigest() != protocol["config_hash"]:
        raise WorkflowFailure("protocol_hash_mismatch")
    for key in ("data_fingerprint", "split_id", "seed"):
        if protocol[key] != manifest[key]:
            raise WorkflowFailure("protocol_dataset_mismatch")
    if manifest.get("task_profile") == "regression":
        if (
            protocol.get("task_type") != "regression"
            or protocol.get("task_profile") != "regression"
            or protocol.get("target") != "value"
            or protocol.get("thresholds") != {"mae": 1.0, "rmse": 1.5}
            or protocol.get("directions") != {"mae": "minimize", "rmse": "minimize"}
            or protocol.get("test_used_for_calibration") is not False
            or protocol.get("repeat_tolerance") != 1e-12
        ):
            raise WorkflowFailure("invalid_validation_protocol")
        return protocol
    text_task = manifest.get("task_profile") == "banking77"
    expected_type = (
        (
            "multiclass_classification"
            if len(manifest.get("class_labels", [])) > 2
            else "binary_classification"
        )
        if text_task
        else "binary_classification"
    )
    expected_metrics = (
        (
            {"macro_f1", "recall"}
            if manifest.get("selection", {}).get("objective") == "recall"
            else {"macro_f1"}
        )
        if text_task
        else {"f1", "roc_auc", "precision", "recall"}
    )
    if (
        protocol["task_type"] != expected_type
        or protocol["test_used_for_calibration"] is not False
        or set(protocol["thresholds"]) != expected_metrics
    ):
        raise WorkflowFailure("invalid_validation_protocol")
    if text_task and any(
        protocol.get(key) != manifest[key]
        for key in ("task_profile", "target", "class_labels", "class_names")
    ):
        raise WorkflowFailure("protocol_label_mapping_mismatch")
    if text_task and protocol.get("selection") != manifest.get("selection"):
        raise WorkflowFailure("protocol_selection_mismatch")
    tolerance = protocol.get("repeat_tolerance")
    if (
        not isinstance(tolerance, (int, float))
        or not math.isfinite(tolerance)
        or not 0 <= tolerance <= 1e-10
    ):
        raise WorkflowFailure("invalid_repeat_tolerance")
    if any(
        not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1
        for v in protocol["thresholds"].values()
    ):
        raise WorkflowFailure("invalid_validation_thresholds")
    return protocol


def text_reference_pipeline(seed):
    """Trusted independent baseline implementation, no generated code import."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    return Pipeline(
        [
            (
                "preprocess",
                ColumnTransformer(
                    [
                        (
                            "text",
                            TfidfVectorizer(
                                ngram_range=(1, 2), sublinear_tf=True, max_features=30000
                            ),
                            "text",
                        )
                    ]
                ),
            ),
            ("model", LogisticRegression(C=4.0, max_iter=500, random_state=seed)),
        ]
    )


def multiclass_metrics(labels, predictions, class_labels):
    from sklearn.metrics import accuracy_score

    return {
        "macro_f1": float(
            f1_score(labels, predictions, labels=class_labels, average="macro", zero_division=0)
        ),
        "accuracy": float(accuracy_score(labels, predictions)),
    }


def text_metrics(labels, predictions, probabilities, class_labels):
    scores = multiclass_metrics(labels, predictions, class_labels)
    if len(class_labels) == 2:
        scores.update(classification_metrics(labels, predictions, probabilities[:, 1]))
    return scores


def calibrate_text(directory, protocol_path, manifest):
    from threadpoolctl import threadpool_limits

    train = pd.read_csv(directory / "train.csv")
    validation = pd.read_csv(directory / "validation_features.csv")
    labels = pd.read_csv(directory / "validation_labels.csv")
    reference = text_reference_pipeline(manifest["seed"])
    with threadpool_limits(limits=1):
        reference.fit(train[["text"]], train.intent)
        scores = text_metrics(
            labels.intent,
            reference.predict(validation[["text"]]),
            reference.predict_proba(validation[["text"]]),
            manifest["class_labels"],
        )
    if scores["macro_f1"] < 0.5:
        raise WorkflowFailure("baseline_below_minimum")
    protocol = {
        "schema_version": 1,
        "task_type": "multiclass_classification"
        if len(manifest["class_labels"]) > 2
        else "binary_classification",
        "task_profile": "banking77",
        "target": "intent",
        "class_labels": manifest["class_labels"],
        "class_names": manifest["class_names"],
        "seed": manifest["seed"],
        "data_fingerprint": manifest["data_fingerprint"],
        "split_id": manifest["split_id"],
        "baseline": {
            "algorithm": "TF-IDF + LogisticRegression(C=4.0)",
            "validation_metrics": scores,
            "calibrator_sha256": sha256_file(Path(__file__)),
            "sklearn_version": importlib.metadata.version("scikit-learn"),
            "vocabulary_sha256": hashlib.sha256(
                canonical(
                    {
                        word: int(index)
                        for word, index in reference.named_steps["preprocess"]
                        .named_transformers_["text"]
                        .vocabulary_.items()
                    }
                ).encode()
            ).hexdigest(),
            "fit_rows": len(train),
            "fit_split": "train",
        },
        "threshold_rule": "macro_f1 >= max(0.50, floor((validation_baseline - 0.05)*100)/100); accuracy descriptive only",
        "thresholds": {"macro_f1": max(0.5, math.floor((scores["macro_f1"] - 0.05) * 100) / 100)},
        "repeat_tolerance": 1e-12,
        "test_used_for_calibration": False,
    }
    if manifest.get("selection"):
        protocol["selection"] = manifest["selection"]
        if manifest["selection"]["objective"] == "recall":
            protocol["thresholds"]["recall"] = max(
                0.0, math.floor((scores["recall"] - 0.05) * 100) / 100
            )
            protocol["threshold_rule"] += (
                "; positive recall >= floor((baseline recall - .05)*100)/100, bounded below by zero; rank valid candidates by recall then macro_f1"
            )
    protocol["config_hash"] = hashlib.sha256(canonical(protocol).encode()).hexdigest()
    write_json(protocol_path, protocol)
    return protocol
