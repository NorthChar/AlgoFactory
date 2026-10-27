import copy

import pytest
from pydantic import ValidationError

from algofactory.schemas.contracts import (
    AgentDecision,
    AlgorithmPlan,
    Candidate,
    ExecutionBudget,
    ExperienceRecord,
    TaskSpec,
    ValidationResult,
)


def task_data():
    return dict(
        task_id="task:one",
        description="预测客户流失",
        task_type="binary_classification",
        target="churn",
        feature_schema=[{"name": "tenure", "dtype": "numeric"}],
        data_fingerprint="a" * 64,
        split_id="split:42",
        metrics=[{"name": "f1", "direction": "maximize", "threshold": 0.6}],
    )


def validation_data():
    return dict(
        run_id="run:one",
        implementation_id="impl:one",
        code_hash="a" * 64,
        config_hash="b" * 64,
        split_id="split:42",
        status="passed",
        **{
            key: {"status": "passed", "details": "fixture result"}
            for key in ("functional", "metrics", "stability", "interface")
        },
        validation_metrics={"f1": 0.7},
        resources={"elapsed_seconds": 1.0},
        report_paths=["runtime/report.json"],
    )


def test_contract_json_roundtrips_and_defaults():
    task = TaskSpec(**task_data())
    assert TaskSpec.model_validate_json(task.model_dump_json()) == task
    assert task.constraints.execution.network is False
    assert task.constraints.execution.fail_closed is True
    assert task.seed == 42
    plan = AlgorithmPlan(
        plan_id="plan:one",
        task_id=task.task_id,
        algorithm_id="alg:lr",
        preprocessing=["impute"],
        dependencies=["scikit-learn"],
        evidence_ids=["source:one"],
    )
    candidate = Candidate(
        implementation_id="impl:one", code_hash="a" * 64, plan_id=plan.plan_id, attempt=0
    )
    decision = AgentDecision(
        decision_id="decision:one",
        run_id="run:one",
        role="builder",
        action="GENERATE",
        reason="Retrieved evidence",
        evidence_ids=["source:one"],
        budget_remaining=1,
    )
    assert candidate.parent_id is None
    assert decision.action == "GENERATE"


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 2},
        {"seed": "42"},
        {"unknown": True},
        {"data_fingerprint": "not-a-hash"},
        {"target": "tenure"},
        {"feature_schema": [{"name": "a", "dtype": "numeric"}] * 2},
        {"metrics": [{"name": "mae", "direction": "minimize"}]},
        {"metrics": [{"name": "f1", "direction": "minimize"}]},
        {"metrics": [{"name": "f1", "direction": "maximize", "threshold": float("nan")}]},
        {"metrics": [{"name": "f1", "direction": "maximize", "threshold": 1.1}]},
    ],
)
def test_invalid_task_contracts_rejected(change):
    with pytest.raises(ValidationError):
        TaskSpec(**(task_data() | change))


def test_regression_configuration():
    task = TaskSpec(
        **(
            task_data()
            | {
                "task_type": "regression",
                "metrics": [{"name": "rmse", "direction": "minimize", "threshold": 10.0}],
            }
        )
    )
    assert task.metrics[0].direction == "minimize"


@pytest.mark.parametrize(
    "change",
    [{"network": True}, {"backend": "subprocess"}, {"fail_closed": False}, {"timeout_seconds": 0}],
)
def test_execution_contract_fails_closed(change):
    with pytest.raises(ValidationError):
        ExecutionBudget(**change)


def test_candidate_parent_invariants():
    fields = dict(implementation_id="impl:one", code_hash="a" * 64, plan_id="plan:one")
    for extra in (
        {"attempt": 1},
        {"attempt": 0, "parent_id": "impl:old"},
        {"attempt": 1, "parent_id": "impl:one"},
    ):
        with pytest.raises(ValidationError):
            Candidate(**fields, **extra)


def test_validation_cannot_accept_unrun_or_failed_dimensions():
    data = validation_data()
    assert ValidationResult(**data).test_metrics == {}
    for status in ("failed", "not_run"):
        invalid = copy.deepcopy(data)
        invalid["functional"]["status"] = status
        with pytest.raises(ValidationError):
            ValidationResult(**invalid)


def test_test_metrics_require_explicit_final_evaluation():
    data = validation_data()
    with pytest.raises(ValidationError):
        ValidationResult(**data, test_metrics={"f1": 0.8})
    valid = ValidationResult(**data, test_metrics={"f1": 0.8}, final_test_evaluated=True)
    assert valid.validation_metrics != valid.test_metrics
    with pytest.raises(ValidationError):
        ValidationResult(**(data | {"validation_metrics": {"f1": float("inf")}}))


def test_verified_experience_requires_run_reference():
    fields = dict(experience_id="exp:one", condition="缺失值", action="填补", outcome="待验证")
    assert ExperienceRecord(**fields).verification_status == "proposed"
    with pytest.raises(ValidationError):
        ExperienceRecord(**fields, verification_status="verified")


@pytest.mark.parametrize("metrics", [{}, {"f1": 1.5}])
def test_passed_validation_requires_valid_computed_metrics(metrics):
    with pytest.raises(ValidationError):
        ValidationResult(**(validation_data() | {"validation_metrics": metrics}))
