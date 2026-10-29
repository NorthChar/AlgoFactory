"""Search-policy unit simulations are separate from opt-in real Docker evidence."""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import SecretStr, ValidationError

from algofactory.datasets import write_json
from algofactory.knowledge.store import KnowledgeStore
from algofactory.llm.providers import APIConfig, APIProvider, ProviderRequest
from algofactory.llm.workflow_mock import MockWorkflowProvider
from algofactory.planning import SearchPolicy, diagnose, rank_candidates
from algofactory.search import run_search
from algofactory.tasks import BANKING77
from algofactory.workflow_models import WorkerResult, WorkflowFailure

ROOT = Path(__file__).resolve().parents[1]


def invoke(out, dataset, provider=None, policy=None):
    return run_search(
        directory=out,
        dataset_dir=dataset,
        db_path=out.parent / "knowledge.sqlite",
        approval_path=ROOT / "runtime/docker-image.json",
        requirements_path=ROOT / "requirements.txt",
        knowledge_document=ROOT / "data/banking77-phase3.txt",
        request=BANKING77.request,
        provider=provider or MockWorkflowProvider(max_calls=32),
        policy=policy,
    )


@pytest.fixture
def simulated(tmp_path, monkeypatch):
    import algofactory.orchestrator as core
    import algofactory.search as search
    import algofactory.validation.final_test as final

    dataset = tmp_path / "dataset"
    dataset.mkdir()
    train = pd.DataFrame(
        {"row_id": [0, 1, 2], "text": ["apple", "bank", "card"], "intent": [0, 1, 2]}
    )
    train.to_csv(dataset / "train.csv", index=False)
    for stage, ids in (("validation", [3, 4, 5]), ("test", [6, 7, 8])):
        train.assign(row_id=ids)[["row_id", "text"]].to_csv(
            dataset / f"{stage}_features.csv", index=False
        )
        train.assign(row_id=ids)[["row_id", "intent"]].to_csv(
            dataset / f"{stage}_labels.csv", index=False
        )
    manifest = {
        "task_profile": "banking77",
        "seed": 42,
        "data_fingerprint": "a" * 64,
        "split_id": "split:fixture",
        "class_labels": [0, 1, 2],
        "class_names": ["a", "b", "c"],
        "split_indices": {"train": [0, 1, 2], "validation": [3, 4, 5], "test": [6, 7, 8]},
    }
    protocol = {
        "task_type": "multiclass_classification",
        "class_labels": [0, 1, 2],
        "class_names": ["a", "b", "c"],
        "config_hash": "b" * 64,
        "split_id": "split:fixture",
        "thresholds": {"macro_f1": 0.5},
        "repeat_tolerance": 1e-12,
    }
    state = {
        "executions": [],
        "final_fails": False,
        "all_metrics_fail": False,
        "final_raises": False,
    }

    class SimulatedExecutor:
        def __init__(self, *args):
            pass

        def execute(self, code, train_path, features_path, config, out, budget):
            out.mkdir(parents=True)
            write_json(out / "execution.json", {"simulation": True, "stage": config["stage"]})
            state["executions"].append((config["stage"], str(code)))
            if config["stage"] == "test":
                assert (out.parent / "selection.json").exists()
                assert (out.parent / "test-access.json").exists()
                assert (out.parent / "ranking.json").exists()
                if state["final_raises"]:
                    raise WorkflowFailure("execution_timeout")
            if "LinearSVC" in code.read_text():
                return WorkerResult(
                    status="failed", error_category="interface_missing_predict_proba"
                )
            predictions = [0, 1, 2]
            if "MultinomialNB" in code.read_text():
                predictions = [0, 1, 1]
            if state["all_metrics_fail"] or (config["stage"] == "test" and state["final_fails"]):
                predictions = [1, 2, 0]
            probabilities = np.eye(3)[predictions].tolist()
            return WorkerResult(
                status="ok",
                classes=[0, 1, 2],
                row_ids=pd.read_csv(features_path).row_id.tolist(),
                predictions=predictions,
                probabilities=probabilities,
                repeat_predictions=predictions,
                repeat_probabilities=probabilities,
                interface_checked=True,
                missing_column_rejected=True,
                invalid_text_rejected=True,
                unseen_text_handled=True,
                training_rows=3,
            )

    for module in (core, search):
        monkeypatch.setattr(module, "verify_dataset", lambda path: manifest)
        monkeypatch.setattr(module, "calibrate", lambda *args: protocol)
        monkeypatch.setattr(module, "DockerExecutor", SimulatedExecutor)
    monkeypatch.setattr(final, "verify_dataset", lambda path: manifest)
    return dataset, state


@pytest.mark.parametrize(
    "change",
    [
        {"max_repairs": 3},
        {"attempt_budget": 7},
        {"algorithms": []},
        {"algorithms": ["text_nb", "text_nb"]},
    ],
)
def test_search_policy_hard_limits(change):
    with pytest.raises(ValidationError):
        SearchPolicy(**change)


def test_ranking_ties_and_protocol_leakage_rejection():
    protocol = {"config_hash": "b" * 64, "split_id": "split:same"}
    common = protocol | {
        "status": "validated",
        "test_attempted": False,
        "validation_metrics": {"macro_f1": 0.9, "accuracy": 0.9},
    }
    attempts = [common | {"algorithm": "text_nb"}, common | {"algorithm": "text_logistic"}]
    assert rank_candidates(attempts, SearchPolicy(), protocol)[0]["algorithm"] == "text_logistic"
    for changes in (
        {"split_id": "split:other"},
        {"config_hash": "a" * 64},
        {"test_attempted": True},
    ):
        with pytest.raises(WorkflowFailure):
            rank_candidates([attempts[0] | changes], SearchPolicy(), protocol)


def test_repair_versions_and_only_selected_test(simulated, tmp_path):
    dataset, state = simulated
    report = invoke(
        tmp_path / "search", dataset, MockWorkflowProvider("repairable_interface", max_calls=32)
    )
    assert report["status"] == "accepted", report
    assert [(a["algorithm"], a["attempt"], a["status"]) for a in report["attempts"]] == [
        ("text_logistic", 0, "failed"),
        ("text_logistic", 1, "validated"),
        ("text_nb", 0, "validated"),
    ]
    assert [stage for stage, path in state["executions"]] == [
        "validation",
        "validation",
        "validation",
        "test",
    ]
    assert len(list((tmp_path / "search").rglob("test-access.json"))) == 1
    assert all(not a["test_attempted"] for a in report["attempts"])
    assert report["selected_algorithm"] == "text_logistic"
    first, second, _ = report["attempts"]
    assert second["parent_id"] == first["implementation_id"]
    with KnowledgeStore(tmp_path / "knowledge.sqlite") as store:
        implementation = store.evidence(second["implementation_id"])["record"]
        assert (
            implementation["version"] == 2
            and implementation["parent_id"] == first["implementation_id"]
        )
        assert (
            store.get_workflow(report["workflow_id"])["search_summary"]["ranking"][0][
                "implementation_id"
            ]
            == second["implementation_id"]
        )
        assert store.search(entity_type="Experience") == []
    feedback = json.loads(
        (tmp_path / "search/candidates/text_logistic/attempt-1/repair-input.json").read_text()
    )
    assert feedback["diagnosis"]["category"] == "interface_missing_predict_proba"
    assert "test_metrics" not in json.dumps(feedback)


@pytest.mark.parametrize(
    "fault,count,reason",
    [
        ("persistent_interface", 6, "repair_budget_exhausted"),
        ("unrepairable", 4, "unrepairable_no_change"),
    ],
)
def test_unrepairable_and_two_repair_ceiling(simulated, tmp_path, fault, count, reason):
    report = invoke(tmp_path / "search", simulated[0], MockWorkflowProvider(fault, max_calls=32))
    assert report["status"] == "stopped" and report["error_category"] == "no_valid_candidate", (
        report
    )
    assert len(report["attempts"]) == count
    assert {x["reason"] for x in report["candidate_stops"]} == {reason}
    assert not report["test_attempted"]
    assert all(stage != "test" for stage, path in simulated[1]["executions"])
    assert max(x["attempt"] for x in report["attempts"]) <= 2


@pytest.mark.parametrize(
    "policy,calls,category",
    [
        (SearchPolicy(attempt_budget=1), 32, "attempt_budget_exhausted"),
        (SearchPolicy(), 4, "call_budget_exhausted"),
    ],
)
def test_global_budget_stops_even_with_partial_success(
    simulated, tmp_path, policy, calls, category
):
    report = invoke(
        tmp_path / "search", simulated[0], MockWorkflowProvider(max_calls=calls), policy
    )
    assert report["status"] == "stopped" and report["error_category"] == category, report
    assert not report["test_attempted"] and report["persisted"]


@pytest.mark.parametrize("failure", ["final_fails", "final_raises"])
def test_final_failure_never_repairs_or_switches(simulated, tmp_path, failure):
    dataset, state = simulated
    state[failure] = True
    provider = MockWorkflowProvider(max_calls=32)
    report = invoke(tmp_path / "search", dataset, provider)
    assert report["status"] == "failed" and report["test_attempted"]
    assert report["error_category"] == (
        "final_test_threshold_failed" if failure == "final_fails" else "execution_timeout"
    )
    assert len(report["attempts"]) == 2 and provider.calls == 7
    assert sum(stage == "test" for stage, path in state["executions"]) == 1
    assert len(report["ranking"]) == 2 and report["selected_algorithm"] == "text_logistic"


def test_metrics_failure_uses_finite_predeclared_optimization(simulated, tmp_path):
    simulated[1]["all_metrics_fail"] = True
    report = invoke(tmp_path / "search", simulated[0], policy=SearchPolicy(algorithms=["text_nb"]))
    assert report["status"] == "stopped" and len(report["attempts"]) == 3
    for attempt, alpha in enumerate(["0.1", "0.05", "0.01"]):
        code = (tmp_path / f"search/candidates/text_nb/attempt-{attempt}/candidate.py").read_text()
        assert "alpha=" + alpha in code
    assert not report["test_attempted"]


def test_security_failure_stops_without_repair(simulated, tmp_path):
    report = invoke(
        tmp_path / "search", simulated[0], MockWorkflowProvider("unsafe_code", max_calls=32)
    )
    assert report["error_category"] == "unapproved_import" and len(report["attempts"]) == 1
    assert simulated[1]["executions"] == []
    assert diagnose(report)["action"] == "STOP"


def test_failed_child_writeback_prevents_selection(simulated, tmp_path, monkeypatch):
    import algofactory.orchestrator as core

    def fail(*args):
        raise ValueError("simulated transaction failure")

    monkeypatch.setattr(core, "persist_execution", fail)
    report = invoke(tmp_path / "search", simulated[0])
    assert report["status"] == "failed" and report["error_category"] == "knowledge_writeback_failed"
    assert not report["test_attempted"]


def test_simulated_api_transport_gets_actual_repair_feedback(simulated, tmp_path):
    fixture = MockWorkflowProvider("repairable_interface", max_calls=32)
    requests = []

    def transport(url, headers, body, timeout):
        payload = json.loads(body)
        request = json.loads(payload["messages"][1]["content"])
        requests.append(request)
        content = fixture._raw(ProviderRequest(**request, instruction="simulated transport"), {})
        return json.dumps(
            {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        ).encode()

    provider = APIProvider(
        APIConfig(
            base_url="https://example.invalid/v1",
            model="simulated",
            api_key=SecretStr("fixture"),
            max_calls=32,
            max_cost_usd=2.0,
            input_usd_per_million=1.0,
            output_usd_per_million=2.0,
        ),
        transport,
    )
    report = invoke(tmp_path / "search", simulated[0], provider)
    assert report["status"] == "accepted", report
    repairs = [r for r in requests if r["operation"] == "repair_code"]
    assert len(repairs) == 1
    assert "LinearSVC" in repairs[0]["source"]["repair"]["previous_code"]
    assert (
        repairs[0]["source"]["repair"]["diagnosis"]["category"] == "interface_missing_predict_proba"
    )


docker_test = pytest.mark.skipif(
    os.environ.get("ALGOFACTORY_DOCKER_TESTS") != "1",
    reason="Explicit Docker integration opt-in required",
)


@pytest.mark.docker
@docker_test
def test_real_docker_comparison_repair_and_persisted_parent(tmp_path):
    dataset = Path(os.environ.get("ALGOFACTORY_BANKING_DATA", ROOT / "runtime/banking77-data"))
    report = invoke(
        tmp_path / "search", dataset, MockWorkflowProvider("repairable_interface", max_calls=32)
    )
    assert report["status"] == "accepted", report
    assert len(report["ranking"]) == 2
    assert (
        report["ranking"][0]["validation_metrics"]["macro_f1"]
        >= report["ranking"][1]["validation_metrics"]["macro_f1"]
    )
    assert sum(1 for _ in (tmp_path / "search").rglob("test-access.json")) == 1
    with KnowledgeStore(tmp_path / "knowledge.sqlite") as store:
        child = report["attempts"][1]
        assert (
            store.evidence(child["implementation_id"])["record"]["parent_id"]
            == report["attempts"][0]["implementation_id"]
        )
        assert store.get_workflow(report["workflow_id"])["status"] == "accepted"


def test_rejected_plan_keeps_proposal_and_diagnostics_before_execution(simulated, tmp_path):
    dataset, state = simulated
    provider = MockWorkflowProvider(max_calls=8)
    raw = provider._raw

    def invalid_plan(request, schema):
        result = json.loads(raw(request, schema))
        if request.operation == "plan_algorithm":
            capability = next(e for e in request.source["evidence"] if e["type"] == "Capability")
            result["algorithm_id"] = capability["id"]
        return json.dumps(result)

    provider._raw = invalid_plan
    out = tmp_path / "bad-plan"
    report = invoke(out, dataset, provider=provider)
    child = out / "candidates/text_logistic/attempt-0"
    details = json.loads((child / "report.json").read_text())["error_details"]
    assert {"rule": "plan_algorithm_type"} in details
    assert (child / "plan-proposal.json").is_file()
    assert not (child / "plan.json").exists()
    assert state["executions"] == [] and not report["test_attempted"]
    assert "plan_algorithm_type" in (child / "report.md").read_text()
    with KnowledgeStore(out.parent / "knowledge.sqlite") as store:
        record = json.loads((child / "report.json").read_text())
        assert store.get_workflow(record["workflow_id"])["error_details"] == details


def test_resume_real_shape_failure_preserves_lineage_and_shared_budget(simulated, tmp_path):
    dataset, state = simulated
    failed = invoke(
        tmp_path / "original",
        dataset,
        MockWorkflowProvider("repairable_interface", max_calls=4),
        SearchPolicy(algorithms=["text_logistic"], max_repairs=0),
    )
    origin = tmp_path / "original/candidates/text_logistic/attempt-0"
    original_bytes = (origin / "report.json").read_bytes()
    assert failed["status"] == "stopped"
    provider = MockWorkflowProvider(max_calls=7)
    result = run_search(
        directory=tmp_path / "resumed",
        dataset_dir=dataset,
        db_path=tmp_path / "knowledge.sqlite",
        approval_path=ROOT / "runtime/docker-image.json",
        requirements_path=ROOT / "requirements.txt",
        knowledge_document=ROOT / "data/banking77-phase3.txt",
        request=BANKING77.request,
        provider=provider,
        resume_failures={"text_logistic": origin},
    )
    assert result["status"] == "accepted", result
    first, repaired, other = result["attempts"]
    assert first["historical_failure"] and not repaired["historical_failure"]
    assert repaired["parent_id"] == first["implementation_id"]
    assert provider.calls == 7  # 4 for repair, 3 for the other candidate; one extraction.
    assert sum(a.operation == "extract_knowledge" for a in provider.audit) == 1
    assert sum(a.operation == "repair_code" for a in provider.audit) == 1
    assert (origin / "report.json").read_bytes() == original_bytes
    assert len(list((tmp_path / "resumed").rglob("test-access.json"))) == 1
    assert len(state["executions"]) == 4  # Original failure, two new validations, winner test.


@pytest.mark.parametrize("tamper", ["code", "test_access", "split", "artifact", "database"])
def test_resume_rejects_changed_or_tested_evidence_before_calls(simulated, tmp_path, tamper):
    dataset, _ = simulated
    invoke(
        tmp_path / "original",
        dataset,
        MockWorkflowProvider("repairable_interface", max_calls=4),
        SearchPolicy(algorithms=["text_logistic"], max_repairs=0),
    )
    origin = tmp_path / "original/candidates/text_logistic/attempt-0"
    if tamper == "code":
        with (origin / "candidate.py").open("a") as stream:
            stream.write("\n# changed")
    elif tamper == "test_access":
        write_json(origin / "test-access.json", {})
    elif tamper == "split":
        report = json.loads((origin / "report.json").read_text())
        report["split_id"] = "split:other"
        write_json(origin / "report.json", report)
    elif tamper == "artifact":
        (origin / "trace.json").write_text("[]")
    else:
        with KnowledgeStore(tmp_path / "knowledge.sqlite") as store:
            store.connection.execute("DELETE FROM workflow_runs")
            store.connection.commit()
    provider = MockWorkflowProvider(max_calls=20)
    report = run_search(
        directory=tmp_path / "resumed",
        dataset_dir=dataset,
        db_path=tmp_path / "knowledge.sqlite",
        approval_path=ROOT / "runtime/docker-image.json",
        requirements_path=ROOT / "requirements.txt",
        knowledge_document=ROOT / "data/banking77-phase3.txt",
        request=BANKING77.request,
        provider=provider,
        resume_failures={"text_logistic": origin},
    )
    assert report["status"] == "failed"
    assert provider.calls == 0 and not report["test_attempted"]


def test_parameter_deviation_uses_bounded_repair_before_any_test(simulated, tmp_path):
    class MissingParameters(MockWorkflowProvider):
        def _raw(self, request, schema):
            result = super()._raw(request, schema)
            if (
                request.operation == "generate_code"
                and request.source["algorithm_key"] == "text_nb"
            ):
                data = json.loads(result)
                data["code"] = data["code"].replace(
                    "TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, max_features=30000)",
                    "TfidfVectorizer()",
                )
                return json.dumps(data)
            return result

    provider = MissingParameters(max_calls=10)
    report = invoke(tmp_path / "parameters", simulated[0], provider)
    assert report["status"] == "accepted"
    first, bad, repaired = report["attempts"]
    assert bad["error_category"] == "algorithm_configuration_mismatch"
    assert not bad["test_attempted"] and repaired["parent_id"] == bad["implementation_id"]
    feedback = json.loads(
        (tmp_path / "parameters/candidates/text_nb/attempt-1/repair-input.json").read_text()
    )
    assert feedback["diagnosis"]["configuration_diagnostics"][0]["rule"] == "tfidf_parameters"
    assert "test_metrics" not in json.dumps(feedback)
    assert provider.calls == 10
