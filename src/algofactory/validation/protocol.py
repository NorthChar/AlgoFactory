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
    if protocol["test_used_for_calibration"] is not False or set(protocol["thresholds"]) != {
        "f1",
        "roc_auc",
        "precision",
        "recall",
    }:
        raise WorkflowFailure("invalid_validation_protocol")
    if any(
        not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1
        for v in protocol["thresholds"].values()
    ):
        raise WorkflowFailure("invalid_validation_thresholds")
    return protocol
