"""Validate a persisted, untested first failure before resuming bounded search."""

import json
from pathlib import Path

from algofactory.datasets import sha256_file
from algofactory.knowledge.store import KnowledgeStore
from algofactory.planning import ALGORITHMS, diagnose
from algofactory.schemas.contracts import AlgorithmPlan, Candidate
from algofactory.workflow_models import WorkflowFailure


def validate_resume(directory: Path, db_path: Path, algorithm: str, manifest, protocol):
    report = json.loads((directory / "report.json").read_text())
    candidate = Candidate.model_validate_json((directory / "candidate.json").read_text())
    plan = AlgorithmPlan.model_validate_json((directory / "plan.json").read_text())
    validation = report.get("validation", {})
    valid = (
        report["status"] == "failed"
        and report["persisted"]
        and report["task_profile"] == "banking77"
        and not report["test_attempted"]
        and not validation.get("final_test_evaluated")
        and not validation.get("test_metrics")
        and not list(directory.rglob("test-access.json"))
        and candidate.attempt == 0
        and candidate.parent_id is None
        and candidate.code_hash == report["code_hash"] == sha256_file(directory / "candidate.py")
        and validation.get("code_hash") == candidate.code_hash
        and report["data_fingerprint"] == manifest["data_fingerprint"]
        and report["split_id"] == validation.get("split_id") == manifest["split_id"]
        and validation.get("config_hash") == protocol["config_hash"]
        and diagnose(report)["action"] in {"REPAIR", "OPTIMIZE"}
    )
    if not valid:
        raise WorkflowFailure("resume_failure_mismatch")
    # The report and code must agree with immutable persisted evidence, not just each other.
    with KnowledgeStore(db_path) as store:
        saved = store.get_workflow(report["workflow_id"])
        implementation = store.evidence(report["knowledge_ids"]["implementation_id"])["record"]
        selected_algorithm = store.evidence(plan.algorithm_id)["record"]
        if (
            saved["status"] != "failed"
            or saved["validation"] != validation
            or saved["knowledge_ids"] != report["knowledge_ids"]
            or implementation["code_hash"] != candidate.code_hash
            or implementation["version"] != 1
            or implementation.get("parent_id") is not None
            or selected_algorithm["type"] != "Algorithm"
            or selected_algorithm["name"] != ALGORITHMS[algorithm][0]
        ):
            raise WorkflowFailure("resume_persistence_mismatch")
    # Retain the exact historical outputs; reject modified/missing evidence before paid calls.
    for name, digest in report["artifacts_sha256"].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()) or sha256_file(path) != digest:
            raise WorkflowFailure("resume_artifact_changed")
    return report
