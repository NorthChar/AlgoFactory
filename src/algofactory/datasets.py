"""Deterministic synthetic data and host-owned stratified splits; never supplied to the LLM."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from algofactory.knowledge.store import canonical
from algofactory.workflow_models import WorkflowFailure

NUMERIC = ["tenure_months", "monthly_fee", "support_tickets"]
CATEGORICAL = ["contract_type"]
FEATURES = NUMERIC + CATEGORICAL
DEFAULT_REQUEST = "根据客户特征预测客户是否流失，输出流失类别和概率。"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def generate_dataset(directory: Path, rows: int = 1500, seed: int = 42) -> dict:
    if rows < 200 or rows > 100000:
        raise ValueError("Synthetic demo requires 200–100000 rows")
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Dataset destination must be empty; frozen data is never overwritten")
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    tenure = rng.integers(1, 73, rows).astype(float)
    fee = rng.uniform(20, 140, rows)
    tickets = rng.poisson(2, rows).astype(float)
    contract = rng.choice(["monthly", "annual", "two_year"], rows, p=[0.55, 0.3, 0.15])
    score = -1.6 - 0.045 * tenure + 0.026 * fee + 0.65 * tickets - 1.5 * (contract != "monthly")
    probability = 1 / (1 + np.exp(-score))
    labels = (rng.random(rows) < probability).astype(int)
    frame = pd.DataFrame(
        {
            "row_id": np.arange(rows),
            "tenure_months": tenure,
            "monthly_fee": fee,
            "support_tickets": tickets,
            "contract_type": contract,
            "churn": labels,
        }
    )
    for column in ["tenure_months", "monthly_fee", "contract_type"]:
        frame.loc[rng.random(rows) < 0.05, column] = np.nan
    training, heldout = train_test_split(
        np.arange(rows), test_size=0.4, random_state=seed, stratify=labels
    )
    validation, testing = train_test_split(
        heldout, test_size=0.5, random_state=seed, stratify=labels[heldout]
    )
    split = {
        "train": sorted(map(int, training)),
        "validation": sorted(map(int, validation)),
        "test": sorted(map(int, testing)),
    }
    frame.to_csv(directory / "all_rows.csv", index=False, float_format="%.10g")
    # Reload serialized values so all consumers and fingerprints share identical inputs.
    frame = pd.read_csv(directory / "all_rows.csv")
    frame.iloc[split["train"]].to_csv(directory / "train.csv", index=False)
    for name in ("validation", "test"):
        selected = frame.iloc[split[name]]
        selected[["row_id", *FEATURES]].to_csv(directory / f"{name}_features.csv", index=False)
        selected[["row_id", "churn"]].to_csv(directory / f"{name}_labels.csv", index=False)
    manifest = {
        "schema_version": 1,
        "generator": "synthetic_churn_v1",
        "rows": rows,
        "seed": seed,
        "generator_sha256": sha256_file(Path(__file__)),
        "data_fingerprint": sha256_file(directory / "all_rows.csv"),
        "split_id": "split:" + hashlib.sha256(canonical(split).encode()).hexdigest(),
        "split_indices": split,
        "numeric_features": NUMERIC,
        "categorical_features": CATEGORICAL,
        "target": "churn",
        "files": {p.name: sha256_file(p) for p in sorted(directory.glob("*.csv"))},
    }
    write_json(directory / "manifest.json", manifest)
    return manifest


def verify_dataset(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("task_profile") == "banking77":
        from algofactory.banking import verify_banking77

        return verify_banking77(directory, manifest)
    if manifest.get("task_profile", "churn") != "churn":
        raise WorkflowFailure("unsupported_task_profile")
    expected = {
        "all_rows.csv",
        "train.csv",
        "validation_features.csv",
        "validation_labels.csv",
        "test_features.csv",
        "test_labels.csv",
    }
    if set(manifest["files"]) != expected:
        raise WorkflowFailure("dataset_file_set_mismatch")
    for name, digest in manifest["files"].items():
        if sha256_file(directory / name) != digest:
            raise WorkflowFailure("dataset_fingerprint_mismatch")
    split = manifest["split_indices"]
    if set(split) != {"train", "validation", "test"}:
        raise WorkflowFailure("invalid_split")
    indices = [index for group in split.values() for index in group]
    if sorted(indices) != list(range(manifest["rows"])):
        raise WorkflowFailure("overlapping_or_incomplete_split")
    split_id = "split:" + hashlib.sha256(canonical(split).encode()).hexdigest()
    if (
        split_id != manifest["split_id"]
        or manifest["data_fingerprint"] != manifest["files"]["all_rows.csv"]
    ):
        raise WorkflowFailure("invalid_split_identity")
    if (
        manifest["numeric_features"] != NUMERIC
        or manifest["categorical_features"] != CATEGORICAL
        or manifest["target"] != "churn"
        or manifest.get("text_features", []) != []
        or manifest.get("class_labels", [0, 1]) != [0, 1]
    ):
        raise WorkflowFailure("unsupported_dataset_schema")
    # IDs and target separation are checked before any candidate is allowed to run.
    for stage in ("train", "validation", "test"):
        name = "train.csv" if stage == "train" else f"{stage}_features.csv"
        frame = pd.read_csv(directory / name)
        expected_columns = (
            ["row_id", *FEATURES, "churn"] if stage == "train" else ["row_id", *FEATURES]
        )
        if list(frame.columns) != expected_columns or frame.row_id.tolist() != split[stage]:
            raise WorkflowFailure("dataset_schema_or_order_mismatch")
        if stage != "train":
            labels = pd.read_csv(directory / f"{stage}_labels.csv")
            if (
                list(labels.columns) != ["row_id", "churn"]
                or labels.row_id.tolist() != split[stage]
            ):
                raise WorkflowFailure("label_alignment_mismatch")
        else:
            labels = frame
        if set(labels.churn.unique()) != {0, 1}:
            raise WorkflowFailure("split_requires_both_classes")
    return manifest
