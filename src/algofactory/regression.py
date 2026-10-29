"""Small synthetic regression extension with a frozen, independent holdout protocol."""

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from algofactory.datasets import sha256_file, write_json
from algofactory.knowledge.store import canonical
from algofactory.workflow_models import WorkflowFailure

FEATURES = ["x1", "x2", "x3"]


def generate_regression(directory: Path, rows=600, seed=42):
    if not 200 <= rows <= 100000 or (directory.exists() and any(directory.iterdir())):
        raise ValueError("invalid_regression_destination_or_rows")
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(rows, 3))
    frame = pd.DataFrame(x, columns=FEATURES)
    frame.insert(0, "row_id", np.arange(rows))
    frame["value"] = x @ np.array([3.0, -2.0, 0.5]) + rng.normal(scale=0.5, size=rows)
    train, rest = train_test_split(np.arange(rows), test_size=0.4, random_state=seed)
    valid, test = train_test_split(rest, test_size=0.5, random_state=seed)
    split = {
        key: sorted(map(int, values))
        for key, values in (("train", train), ("validation", valid), ("test", test))
    }
    frame.to_csv(directory / "all_rows.csv", index=False, float_format="%.10g")
    frame = pd.read_csv(directory / "all_rows.csv")
    frame.iloc[split["train"]].to_csv(directory / "train.csv", index=False)
    for stage in ("validation", "test"):
        selected = frame.iloc[split[stage]]
        selected[["row_id", *FEATURES]].to_csv(directory / f"{stage}_features.csv", index=False)
        selected[["row_id", "value"]].to_csv(directory / f"{stage}_labels.csv", index=False)
    manifest = {
        "schema_version": 1,
        "task_profile": "regression",
        "generator": "synthetic_linear_v1",
        "rows": rows,
        "seed": seed,
        "generator_sha256": sha256_file(Path(__file__)),
        "data_fingerprint": sha256_file(directory / "all_rows.csv"),
        "split_id": "split:" + hashlib.sha256(canonical(split).encode()).hexdigest(),
        "split_indices": split,
        "numeric_features": FEATURES,
        "categorical_features": [],
        "text_features": [],
        "class_labels": [],
        "target": "value",
        "files": {p.name: sha256_file(p) for p in sorted(directory.glob("*.csv"))},
    }
    write_json(directory / "manifest.json", manifest)
    return manifest


def verify_regression(directory, manifest):
    expected = {
        "all_rows.csv",
        "train.csv",
        "validation_features.csv",
        "validation_labels.csv",
        "test_features.csv",
        "test_labels.csv",
    }
    if set(manifest["files"]) != expected or any(
        sha256_file(directory / k) != v for k, v in manifest["files"].items()
    ):
        raise WorkflowFailure("dataset_fingerprint_mismatch")
    if any(
        manifest.get(k) != v
        for k, v in {
            "target": "value",
            "numeric_features": FEATURES,
            "categorical_features": [],
            "text_features": [],
            "class_labels": [],
        }.items()
    ):
        raise WorkflowFailure("unsupported_dataset_schema")
    split = manifest["split_indices"]
    if (
        set(split) != {"train", "validation", "test"}
        or any(not v for v in split.values())
        or sorted(i for v in split.values() for i in v) != list(range(manifest["rows"]))
    ):
        raise WorkflowFailure("overlapping_or_incomplete_split")
    if (
        manifest["split_id"] != "split:" + hashlib.sha256(canonical(split).encode()).hexdigest()
        or manifest["data_fingerprint"] != manifest["files"]["all_rows.csv"]
    ):
        raise WorkflowFailure("invalid_split_identity")
    all_rows = pd.read_csv(directory / "all_rows.csv")
    if (
        list(all_rows.columns) != ["row_id", *FEATURES, "value"]
        or all_rows.row_id.tolist() != list(range(manifest["rows"]))
        or not np.isfinite(all_rows.to_numpy()).all()
    ):
        raise WorkflowFailure("invalid_regression_data")
    for stage in split:
        names = (
            ["train.csv"] if stage == "train" else [f"{stage}_features.csv", f"{stage}_labels.csv"]
        )
        for name in names:
            frame = pd.read_csv(directory / name)
            columns = (
                ["row_id", *FEATURES, "value"]
                if stage == "train"
                else (["row_id", "value"] if "labels" in name else ["row_id", *FEATURES])
            )
            if (
                list(frame.columns) != columns
                or frame.row_id.tolist() != split[stage]
                or not np.allclose(
                    frame.to_numpy(),
                    all_rows.iloc[split[stage]][columns].to_numpy(),
                    rtol=0,
                    atol=1e-12,
                )
            ):
                raise WorkflowFailure("dataset_schema_or_order_mismatch")
    return manifest


def calibrate_regression(directory, protocol_path, manifest):
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    from algofactory.plugins import default_registry

    train = pd.read_csv(directory / "train.csv")
    validation = pd.read_csv(directory / "validation_features.csv")
    labels = pd.read_csv(directory / "validation_labels.csv")
    baseline = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=1.0))
    baseline.fit(train[FEATURES], train.value)
    prediction = baseline.predict(validation[FEATURES])
    registry = default_registry()
    scores = {
        name: registry.score(name, "regression", labels.value, prediction)
        for name in ("mae", "rmse")
    }
    # Predeclared relative to generator noise (std=0.5), never derived from the test split.
    thresholds = {"mae": 1.0, "rmse": 1.5}
    if any(scores[k] > v for k, v in thresholds.items()):
        raise WorkflowFailure("baseline_below_minimum")
    protocol = {
        "schema_version": 1,
        "task_type": "regression",
        "task_profile": "regression",
        "target": "value",
        "seed": manifest["seed"],
        "data_fingerprint": manifest["data_fingerprint"],
        "split_id": manifest["split_id"],
        "baseline": {
            "algorithm": "Ridge(alpha=1.0)",
            "validation_metrics": scores,
            "fit_split": "train",
            "calibrator_sha256": sha256_file(Path(__file__)),
        },
        "threshold_rule": "predeclared MAE <= 1.0 and RMSE <= 1.5 (synthetic noise std 0.5)",
        "thresholds": thresholds,
        "directions": {"mae": "minimize", "rmse": "minimize"},
        "repeat_tolerance": 1e-12,
        "test_used_for_calibration": False,
    }
    protocol["config_hash"] = hashlib.sha256(canonical(protocol).encode()).hexdigest()
    write_json(protocol_path, protocol)
    return protocol


def score_regression(result, labels, protocol, require_stability):
    from algofactory.plugins import default_registry

    if (
        list(labels.columns) != ["row_id", "value"]
        or len(labels) == 0
        or result.row_ids != labels.row_id.tolist()
    ):
        raise WorkflowFailure("prediction_alignment_mismatch")
    y = labels.value.to_numpy(dtype=float)
    p = np.asarray(result.predictions, dtype=float)
    r = np.asarray(result.repeat_predictions, dtype=float)
    if p.shape != y.shape or r.shape != y.shape or not all(np.isfinite(a).all() for a in (y, p, r)):
        raise WorkflowFailure("invalid_regression_predictions")
    if result.classes or result.probabilities or result.repeat_probabilities:
        raise WorkflowFailure("regression_probability_contract_mismatch")
    registry = default_registry()
    scores = {name: registry.score(name, "regression", y, p) for name in protocol["thresholds"]}
    repeat = bool(np.allclose(p, r, rtol=0, atol=protocol["repeat_tolerance"]))
    return {
        "metrics": scores,
        "functional": True,
        "interface": result.interface_checked,
        "stability": bool(
            repeat and result.missing_column_rejected and result.invalid_numeric_rejected
        )
        if require_stability
        else None,
        "metrics_passed": all(scores[k] <= v for k, v in protocol["thresholds"].items()),
        "stability_details": {
            "seed_repeat": repeat,
            "missing_column_rejected": result.missing_column_rejected,
            "invalid_numeric_rejected": result.invalid_numeric_rejected,
        },
    }
