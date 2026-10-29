"""Offline replay of a real rejected plan, plus independent plan boundary checks."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from algofactory.generation.plan import SandboxAlgorithmPlan, validate_plan
from algofactory.schemas.contracts import AlgorithmPlan
from algofactory.workflow_models import WorkflowFailure

ROOT = Path(__file__).resolve().parents[1] / "examples/api-plan-fix/diagnosis"


def recorded():
    req = json.loads((ROOT / "request.json").read_text())["source"]
    plan = AlgorithmPlan.model_validate_json((ROOT / "plan-proposal.json").read_bytes())
    args = {k: req[k] for k in ("task_id", "plan_id", "algorithm", "evidence")}
    return plan, args


def test_real_plan_failure_replays_as_dependency_mismatch():
    plan, args = recorded()
    with pytest.raises(WorkflowFailure) as failure:
        validate_plan(plan, **args)
    assert failure.value.category == "unsupported_phase2_plan"
    assert failure.value.diagnostics == [{"rule": "plan_dependencies"}]
    with pytest.raises(ValidationError):
        SandboxAlgorithmPlan.model_validate(plan.model_dump())


def test_same_plan_with_package_name_passes_all_host_checks():
    plan, args = recorded()
    data = plan.model_dump() | {"dependencies": ["scikit-learn"]}
    fixed = SandboxAlgorithmPlan.model_validate(data)
    validate_plan(fixed, **args)
    assert plan.dependencies != fixed.dependencies  # Original evidence remains intact.


@pytest.mark.parametrize(
    "dependencies", [["sklearn"], ["scikit-learn>=1.5"], ["scikit-learn", "numpy"], []]
)
def test_sandbox_plan_does_not_accept_aliases_versions_or_extra_packages(dependencies):
    plan, _ = recorded()
    with pytest.raises(ValidationError):
        SandboxAlgorithmPlan.model_validate(plan.model_dump() | {"dependencies": dependencies})


@pytest.mark.parametrize(
    "field,value,rule",
    [
        ("task_id", "wrong-task", "plan_task_id"),
        ("plan_id", "wrong-plan", "plan_id"),
        ("evidence_ids", ["private-value"], "plan_evidence_ids"),
        ("algorithm_id", "private-value", "plan_algorithm_reference"),
    ],
)
def test_invalid_plan_references_remain_rejected_and_redacted(field, value, rule):
    plan, args = recorded()
    bad = plan.model_copy(update={"dependencies": ["scikit-learn"], field: value})
    with pytest.raises(WorkflowFailure) as failure:
        validate_plan(bad, **args)
    assert {"rule": rule} in failure.value.diagnostics
    assert "private-value" not in str(failure.value.diagnostics)
