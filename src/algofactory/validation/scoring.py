"""Score isolated predictions against labels that are never mounted into the container."""

import numpy as np
import pandas as pd

from algofactory.validation.protocol import classification_metrics
from algofactory.workflow_models import WorkerResult, WorkflowFailure


def score_predictions(
    result: WorkerResult, labels: pd.DataFrame, protocol: dict, *, require_stability: bool = True
) -> dict:
    if result.status != "ok":
        raise WorkflowFailure(result.error_category or "worker_failed")
    n = len(labels)
    arrays = [
        result.predictions,
        result.probabilities,
        result.repeat_predictions,
        result.repeat_probabilities,
    ]
    if n == 0 or any(len(a) != n for a in arrays) or result.row_ids != labels.row_id.tolist():
        raise WorkflowFailure("prediction_alignment_mismatch")
    if any(not np.isfinite(a).all() for a in arrays):
        raise WorkflowFailure("nonfinite_predictions")
    if not set(result.predictions) <= {0, 1} or not set(result.repeat_predictions) <= {0, 1}:
        raise WorkflowFailure("invalid_class_predictions")
    if any(
        np.min(a) < 0 or np.max(a) > 1 for a in (result.probabilities, result.repeat_probabilities)
    ):
        raise WorkflowFailure("invalid_probabilities")
    scores = classification_metrics(labels.churn, result.predictions, result.probabilities)
    repeat = result.predictions == result.repeat_predictions and np.allclose(
        result.probabilities, result.repeat_probabilities, rtol=0, atol=protocol["repeat_tolerance"]
    )
    stability = (
        bool(
            repeat
            and result.missing_column_rejected
            and result.invalid_numeric_rejected
            and result.unseen_category_handled
        )
        if require_stability
        else None
    )
    return {
        "metrics": scores,
        "functional": True,
        "interface": result.interface_checked,
        "stability": stability,
        "metrics_passed": all(
            scores[name] >= threshold for name, threshold in protocol["thresholds"].items()
        ),
        "stability_details": {
            "seed_repeat": bool(repeat),
            "missing_column_rejected": result.missing_column_rejected,
            "invalid_numeric_rejected": result.invalid_numeric_rejected,
            "unseen_category_handled": result.unseen_category_handled,
        },
    }
