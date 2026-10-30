"""Shared final-test boundary: sealed selection, one reservation, no feedback loop."""

import json

import pandas as pd

from algofactory.datasets import sha256_file, verify_dataset, write_json
from algofactory.validation.scoring import score_predictions
from algofactory.workflow_models import WorkflowFailure


def evaluate_final(
    directory,
    dataset_dir,
    manifest,
    task,
    candidate,
    protocol,
    executor,
    config,
    report,
    validation_metrics,
):
    code_path = directory / "candidate.py"
    selection = {
        "code_hash": candidate.code_hash,
        "config_hash": protocol["config_hash"],
        "experiment_hash": report.get("experiment_hash"),
        "split_id": manifest["split_id"],
        "validation_metrics": validation_metrics,
        "reason": "All validation checks passed before any test evaluation",
    }
    write_json(directory / "selection.json", selection)
    # Exclusive reservation is persisted before exposing test features to execution.
    with (directory / "test-access.json").open("x", encoding="utf-8") as handle:
        json.dump(selection, handle)
    report["test_attempted"] = True
    if sha256_file(code_path) != selection["code_hash"]:
        raise WorkflowFailure("selected_code_changed")
    if verify_dataset(dataset_dir) != manifest:
        raise WorkflowFailure("selected_dataset_changed")
    report["execution_evidence"].append(str(directory / "test-execution/execution.json"))
    final = executor.execute(
        code_path,
        dataset_dir / "train.csv",
        dataset_dir / "test_features.csv",
        config | {"stage": "test", "persist_model": False},
        directory / "test-execution",
        task.constraints.execution,
    )
    if final.training_rows != len(manifest["split_indices"]["train"]):
        raise WorkflowFailure(final.error_category or "final_training_row_count_mismatch")
    final_scores = score_predictions(
        final, pd.read_csv(dataset_dir / "test_labels.csv"), protocol, require_stability=False
    )
    if not final_scores["interface"]:
        raise WorkflowFailure("final_interface_check_failed")
    return final, final_scores
