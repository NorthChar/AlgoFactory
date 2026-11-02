"""Finite search policy and deterministic decisions; no held-out results are inputs."""

from typing import Literal

from pydantic import Field, model_validator

from algofactory.schemas.contracts import Contract
from algofactory.workflow_models import WorkflowFailure

ALGORITHMS = {
    "text_logistic": ("TF-IDF + Logistic Regression", "text_logistic.txt"),
    "text_nb": ("TF-IDF + MultinomialNB", "text_nb.txt"),
}


class SearchPolicy(Contract):
    algorithms: list[Literal["text_logistic", "text_nb"]] = Field(
        default_factory=lambda: ["text_logistic", "text_nb"], min_length=1, max_length=2
    )
    max_repairs: int = Field(default=2, ge=0, le=2)
    attempt_budget: int = Field(default=6, ge=1, le=6)
    ranking: Literal[
        "macro_f1_desc_accuracy_desc_algorithm_order",
        "recall_desc_macro_f1_desc_accuracy_desc_algorithm_order",
    ] = "macro_f1_desc_accuracy_desc_algorithm_order"

    @model_validator(mode="after")
    def unique_algorithms(self):
        if len(set(self.algorithms)) != len(self.algorithms):
            raise ValueError("Candidate algorithms must be unique")
        return self


REPAIRABLE = {
    "algorithm_configuration_mismatch",
    "interface_missing_predict_proba",
    "interface_missing_predict",
    "interface_missing_fit",
    "interface_missing_build_pipeline",
    "missing_build_pipeline",
    "invalid_python",
    "invalid_probability_interface",
    "invalid_probability_values",
    "invalid_prediction_shape_or_values",
    "invalid_probability_shape",
    "probability_class_order_mismatch",
    "prediction_alignment_mismatch",
    "worker_ValueError",
    "worker_TypeError",
    "worker_KeyError",
    "validation_checks_failed",
    "execution_timeout",
    "resource_limit_exceeded",
    "container_nonzero_exit",
}


def diagnose(report):
    category = report.get("error_category")
    dimensions = report.get("validation", {})
    if (
        category == "validation_checks_failed"
        and dimensions.get("metrics", {}).get("status") == "failed"
    ):
        action, reason = (
            "OPTIMIZE",
            "验证集指标未达到冻结门槛；仅调整当前候选，禁止改阈值或查看测试集",
        )
    elif category in REPAIRABLE:
        action, reason = "REPAIR", "根据实际接口、执行或稳定性错误修复当前候选"
    else:
        action, reason = "STOP", "安全、数据完整性、服务/预算或无进展错误不能通过继续生成绕过"
    return {
        "action": action,
        "category": category or "none",
        "configuration_diagnostics": report.get("error_details", [])
        if category == "algorithm_configuration_mismatch"
        else [],
        "reason": reason,
        "validation_metrics": dimensions.get("validation_metrics", {}),
        "dimensions": {
            k: dimensions.get(k, {"status": "not_run", "details": "未执行"})
            for k in ("functional", "metrics", "stability", "interface")
        },
    }


def rank_candidates(attempts, policy, protocol):
    eligible = []
    for attempt in attempts:
        if attempt["status"] != "validated":
            continue
        if (
            attempt["config_hash"] != protocol["config_hash"]
            or attempt["split_id"] != protocol["split_id"]
        ):
            raise WorkflowFailure("candidate_protocol_mismatch")
        if attempt["test_attempted"]:
            raise WorkflowFailure("candidate_test_leakage")
        eligible.append(attempt)
    return sorted(
        eligible,
        key=lambda r: (
            -r["validation_metrics"].get("recall", 0)
            if protocol.get("selection", {}).get("objective") == "recall"
            else 0,
            -r["validation_metrics"]["macro_f1"],
            -r["validation_metrics"]["accuracy"],
            policy.algorithms.index(r["algorithm"]),
        ),
    )
