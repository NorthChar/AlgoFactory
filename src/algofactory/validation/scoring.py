"""Score isolated predictions against labels that are never mounted into the container."""

import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix

from algofactory.validation.protocol import classification_metrics, text_metrics
from algofactory.workflow_models import WorkerResult, WorkflowFailure


def score_predictions(
    result: WorkerResult, labels: pd.DataFrame, protocol: dict, *, require_stability: bool = True
) -> dict:
    if result.status != "ok":
        raise WorkflowFailure(result.error_category or "worker_failed")
    if protocol["task_type"] == "regression":
        from algofactory.regression import score_regression

        return score_regression(result, labels, protocol, require_stability)
    text_task = (
        protocol.get("task_profile") == "banking77"
        or protocol["task_type"] == "multiclass_classification"
    )
    target = "intent" if text_task else "churn"
    classes = protocol["class_labels"] if text_task else [0, 1]
    if list(labels.columns) != ["row_id", target] or not set(labels[target]) <= set(classes):
        raise WorkflowFailure("scoring_label_space_mismatch")
    if result.classes != classes:
        raise WorkflowFailure("probability_class_order_mismatch")
    n = len(labels)
    arrays = [
        result.predictions,
        result.probabilities,
        result.repeat_predictions,
        result.repeat_probabilities,
    ]
    if n == 0 or any(len(a) != n for a in arrays) or result.row_ids != labels.row_id.tolist():
        raise WorkflowFailure("prediction_alignment_mismatch")
    try:
        predictions, probabilities, repeats, repeat_probs = [
            np.asarray(a, dtype=float) for a in arrays
        ]
    except ValueError:
        raise WorkflowFailure("invalid_probability_shape") from None
    expected_shape = (n, len(classes)) if text_task else (n,)
    if probabilities.shape != expected_shape or repeat_probs.shape != expected_shape:
        raise WorkflowFailure("invalid_probability_shape")
    if any(not np.isfinite(a).all() for a in (predictions, probabilities, repeats, repeat_probs)):
        raise WorkflowFailure("nonfinite_predictions")
    if not set(result.predictions) <= set(classes) or not set(result.repeat_predictions) <= set(
        classes
    ):
        raise WorkflowFailure("invalid_class_predictions")
    for matrix in (probabilities, repeat_probs):
        if (matrix < 0).any() or (matrix > 1).any():
            raise WorkflowFailure("invalid_probabilities")
        if text_task and not np.allclose(matrix.sum(axis=1), 1, rtol=0, atol=1e-8):
            raise WorkflowFailure("invalid_probability_sums")
    scores = (
        text_metrics(labels[target], result.predictions, probabilities, classes)
        if text_task
        else classification_metrics(labels[target], result.predictions, result.probabilities)
    )
    repeat = result.predictions == result.repeat_predictions and np.allclose(
        probabilities, repeat_probs, rtol=0, atol=protocol["repeat_tolerance"]
    )
    input_checks = (
        result.invalid_text_rejected and result.unseen_text_handled
        if text_task
        else result.invalid_numeric_rejected and result.unseen_category_handled
    )
    stability = (
        bool(repeat and result.missing_column_rejected and input_checks)
        if require_stability
        else None
    )
    details = {
        "seed_repeat": bool(repeat),
        "missing_column_rejected": result.missing_column_rejected,
    }
    details.update(
        {
            "invalid_text_rejected": result.invalid_text_rejected,
            "unseen_text_handled": result.unseen_text_handled,
        }
        if text_task
        else {
            "invalid_numeric_rejected": result.invalid_numeric_rejected,
            "unseen_category_handled": result.unseen_category_handled,
        }
    )
    measured = {
        "metrics": scores,
        "functional": True,
        "interface": result.interface_checked,
        "stability": stability,
        "metrics_passed": all(
            scores[name] >= threshold for name, threshold in protocol["thresholds"].items()
        ),
        "stability_details": details,
    }
    if text_task:
        measured["class_details"] = {
            "class_labels": classes,
            "class_names": protocol["class_names"],
            "per_class": classification_report(
                labels[target],
                result.predictions,
                labels=classes,
                target_names=protocol["class_names"],
                output_dict=True,
                zero_division=0,
            ),
            "confusion_matrix": confusion_matrix(
                labels[target], result.predictions, labels=classes
            ).tolist(),
            "matrix_rows": "true_label",
            "matrix_columns": "predicted_label",
        }
    return measured
