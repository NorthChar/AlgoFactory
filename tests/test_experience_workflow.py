"""Explicit executor simulations exercise memory delivery and frozen-library boundaries."""

import json
from pathlib import Path

import pytest
from test_phase3 import simulated as simulated

from algofactory.knowledge.store import KnowledgeStore
from algofactory.llm.workflow_mock import MockWorkflowProvider
from algofactory.planning import SearchPolicy
from algofactory.search import run_search
from algofactory.tasks import BANKING77_REUSE_REQUEST
from algofactory.workflow_models import WorkerResult

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def adapter_failure(simulated, monkeypatch):
    import algofactory.orchestrator as core

    Original = core.DockerExecutor

    class AdapterExecutor(Original):
        def execute(self, code, *args):
            measured = super().execute(code, *args)
            if "preprocess = TfidfVectorizer(" in code.read_text():
                return WorkerResult(status="failed", error_category="worker_ValueError")
            return measured

    monkeypatch.setattr(core, "DockerExecutor", AdapterExecutor)
    return simulated


def invoke(out, dataset, provider, **options):
    return run_search(
        directory=out,
        dataset_dir=dataset,
        db_path=out.parent / "knowledge.sqlite",
        approval_path=ROOT / "runtime/docker-image.json",
        requirements_path=ROOT / "requirements.txt",
        knowledge_document=ROOT / "data/banking77-phase3.txt",
        request=BANKING77_REUSE_REQUEST,
        provider=provider,
        policy=SearchPolicy(algorithms=["text_logistic"], max_repairs=1, attempt_budget=2),
        validation_only=True,
        reuse_knowledge=True,
        **options,
    )


def test_learn_then_deliver_only_in_later_workflow(adapter_failure, tmp_path):
    dataset, state = adapter_failure
    learned = invoke(
        tmp_path / "learn",
        dataset,
        MockWorkflowProvider("text_adapter", max_calls=7),
        use_experiences=True,
        learn_experiences=True,
    )
    assert learned["status"] == "validated", learned
    assert len(learned["learned_experiences"]) == 1
    assert (
        learned["learned_experiences"][0]["experience"]["record"]["verification_status"]
        == "verified"
    )
    assert all(a["experience_usage"]["matches"] == [] for a in learned["attempts"])
    for enabled in (False, True):
        out = tmp_path / ("on" if enabled else "off")
        report = invoke(out, dataset, MockWorkflowProvider(max_calls=3), use_experiences=enabled)
        assert report["status"] == "validated", report
        usage = report["attempts"][0]["experience_usage"]
        assert bool(usage["matches"]) is enabled
        assert bool(usage["model_decisions"]) is enabled
        assert usage["observed_rule_satisfied"] is enabled
        payload = json.loads(
            (out / "candidates/text_logistic/attempt-0/builder-input.json").read_text()
        )
        assert bool(payload["source"]["retrieved_experiences"]) is enabled
        assert "test_metrics" not in json.dumps(payload)
        with KnowledgeStore(tmp_path / "knowledge.sqlite") as store:
            saved = store.get_workflow(report["attempts"][0]["workflow_id"])
            assert saved["experience_usage"] == usage
    assert not list(tmp_path.rglob("test-access.json"))
    assert all(stage == "validation" for stage, _ in state["executions"])


def test_model_cannot_claim_unsupplied_memory(adapter_failure, tmp_path):
    class FalseClaim(MockWorkflowProvider):
        def _raw(self, request, schema):
            raw = super()._raw(request, schema)
            if request.operation == "generate_code":
                data = json.loads(raw)
                data["experience_use"] = [
                    {"experience_id": "invented", "decision": "adopted", "reason": "fixture"}
                ]
                return json.dumps(data)
            return raw

    report = invoke(tmp_path / "false-claim", adapter_failure[0], FalseClaim(max_calls=4))
    assert report["error_category"] == "experience_usage_mismatch"
    assert adapter_failure[1]["executions"] == []
    assert not report["test_attempted"]


def test_unclassified_repair_remains_proposed(adapter_failure, tmp_path):
    report = invoke(
        tmp_path / "unclassified",
        adapter_failure[0],
        MockWorkflowProvider("repairable_interface", max_calls=7),
        learn_experiences=True,
    )
    assert report["status"] == "validated"
    record = report["learned_experiences"][0]["experience"]["record"]
    assert record["verification_status"] == "proposed"
    assert record["repair_evidence"]["rule"] == "unclassified"
    later = invoke(
        tmp_path / "later",
        adapter_failure[0],
        MockWorkflowProvider(max_calls=3),
        use_experiences=True,
    )
    assert later["status"] == "validated"
    assert later["attempts"][0]["experience_usage"]["matches"] == []
