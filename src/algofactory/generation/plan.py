"""Planning boundary for the currently supported, locked scikit-learn sandbox."""

from typing import Annotated, Literal

from pydantic import Field

from algofactory.schemas.contracts import AlgorithmPlan
from algofactory.workflow_models import WorkflowFailure


class SandboxAlgorithmPlan(AlgorithmPlan):
    dependencies: Annotated[
        list[Literal["scikit-learn"]],
        Field(
            min_length=1,
            max_length=1,
            description="Installable package names only; no estimator names or version constraints. Versions are managed by the host lockfile.",
        ),
    ]


def validate_plan(
    plan: AlgorithmPlan, *, task_id: str, plan_id: str, algorithm: str, evidence: list[dict]
):
    records = {entry["id"]: entry for entry in evidence}
    checks = {
        "plan_task_id": plan.task_id == task_id,
        "plan_id": plan.plan_id == plan_id,
        "plan_evidence_ids": set(plan.evidence_ids) <= set(records),
        "plan_algorithm_reference": plan.algorithm_id in plan.evidence_ids,
    }
    issues = [{"rule": rule} for rule, passed in checks.items() if not passed]
    if issues:
        raise WorkflowFailure("plan_evidence_mismatch", diagnostics=issues)
    selected = records.get(plan.algorithm_id, {})
    checks = {
        "plan_algorithm_type": selected.get("type") == "Algorithm",
        "plan_algorithm_name": selected.get("name") == algorithm,
        "plan_dependencies": plan.dependencies == ["scikit-learn"],
    }
    issues = [{"rule": rule} for rule, passed in checks.items() if not passed]
    if issues:
        raise WorkflowFailure("unsupported_phase2_plan", diagnostics=issues)
