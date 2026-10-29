import json
import os
import sqlite3
import subprocess
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import SecretStr, ValidationError

from algofactory.datasets import DEFAULT_REQUEST, generate_dataset, verify_dataset
from algofactory.execution.docker import DockerExecutor, create_command, docker_env
from algofactory.generation.safety import check_code
from algofactory.knowledge.store import KnowledgeConflict, KnowledgeStore
from algofactory.llm.providers import APIConfig, APIProvider, ProviderRequest
from algofactory.llm.workflow_mock import MockWorkflowProvider
from algofactory.orchestrator import run_workflow
from algofactory.schemas.contracts import ExecutionBudget
from algofactory.validation.protocol import calibrate, load_protocol
from algofactory.validation.scoring import score_predictions
from algofactory.workflow_models import WorkerResult, WorkflowFailure

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    path = tmp_path_factory.mktemp("phase2-data")
    generate_dataset(path)
    calibrate(path, path / "protocol.json")
    return path


def invoke(directory, dataset, fault=None, provider=None):
    return run_workflow(
        directory=directory,
        dataset_dir=dataset,
        db_path=directory.parent / "knowledge.sqlite",
        approval_path=ROOT / "runtime/docker-image.json",
        requirements_path=ROOT / "requirements.txt",
        knowledge_document=ROOT / "data/customer_churn.txt",
        request=DEFAULT_REQUEST,
        provider=provider or MockWorkflowProvider(fault),
    )


def test_synthetic_data_determinism_and_disjoint_splits(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    a = generate_dataset(first, rows=200)
    b = generate_dataset(second, rows=200)
    assert a == b
    groups = [set(ids) for ids in a["split_indices"].values()]
    assert [len(g) for g in groups] == [120, 40, 40]
    assert not (groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])
    assert verify_dataset(first) == a
    with pytest.raises(ValueError):
        generate_dataset(first)
    (first / "train.csv").write_text("corrupt")
    with pytest.raises(WorkflowFailure, match="fingerprint"):
        verify_dataset(first)


def test_calibration_freezes_validation_only_metrics(dataset, monkeypatch, tmp_path):
    from algofactory.validation import protocol as module

    observed = []
    original = module.classification_metrics

    def measured(labels, predictions, probabilities):
        observed.append(list(labels))
        return original(labels, predictions, probabilities)

    monkeypatch.setattr(module, "classification_metrics", measured)
    path = tmp_path / "protocol.json"
    result = calibrate(dataset, path)
    assert observed == [pd.read_csv(dataset / "validation_labels.csv").churn.tolist()]
    assert result["test_used_for_calibration"] is False
    assert calibrate(dataset, path) == result
    assert len(observed) == 1
    changed = json.loads(path.read_text())
    changed["thresholds"]["f1"] = 0.01
    path.write_text(json.dumps(changed))
    with pytest.raises(WorkflowFailure, match="protocol_hash"):
        load_protocol(path, verify_dataset(dataset))


def test_template_is_accepted_without_loading_it():
    code = files("algofactory.generation").joinpath("templates/logistic.txt").read_text()
    assert check_code(code) is None


@pytest.mark.parametrize(
    "code",
    [
        "import os\ndef build_pipeline(config):\n return os.system('echo dangerous')",
        "def build_pipeline(config):\n return eval('1')",
        "def build_pipeline(config):\n return config.__class__",
        "from sklearn.pipeline import Pipeline\nprint('side effect')\ndef build_pipeline(config):\n return Pipeline([])",
        "def build_pipeline(config):\n while True:\n  pass",
        "from pathlib import Path\ndef build_pipeline(config):\n return Path('/etc/passwd').read_text()",
    ],
)
def test_unsafe_code_rejected_before_execution(code):
    with pytest.raises(WorkflowFailure):
        check_code(code)


def test_docker_command_has_required_isolation(tmp_path):
    cmd = create_command("docker", "sha256:" + "a" * 64, "test-only", tmp_path, ExecutionBudget())
    for option in (
        "--network=none",
        "--read-only",
        "--user=65534:65534",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=128",
        "--memory=4096m",
        "--cpus=2",
        "--pull=never",
    ):
        assert option in cmd
    assert cmd[cmd.index("--mount") + 1].endswith("dst=/input,readonly")
    assert not any("docker.sock" in arg or "--privileged" in arg for arg in cmd)


def test_docker_bundled_helpers_are_in_child_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    assert docker_env(str(tmp_path / "docker"))["PATH"] == str(tmp_path) + ":/usr/bin"
    assert os.environ["PATH"] == "/usr/bin"


def test_workflow_migration_and_atomic_immutable_write(tmp_path, batch):
    database = tmp_path / "knowledge.sqlite"
    with KnowledgeStore(database) as store:
        store.connection.execute("DROP TABLE workflow_runs")
        store.connection.execute("PRAGMA user_version=1")
    record = {"workflow_id": "workflow:atomic", "status": "failed"}
    with KnowledgeStore(database) as store:
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 2
        store.record_workflow(record)
        store.record_workflow(record)
        with pytest.raises(KnowledgeConflict):
            store.put_batch(batch, workflow_record=record | {"status": "accepted"})
        assert store.snapshot()["sources"] == []
        assert store.get_workflow(record["workflow_id"]) == record


def good_worker():
    return WorkerResult(
        status="ok",
        row_ids=[1, 2, 3, 4],
        predictions=[0, 1, 0, 1],
        probabilities=[0.1, 0.9, 0.2, 0.8],
        repeat_predictions=[0, 1, 0, 1],
        repeat_probabilities=[0.1, 0.9, 0.2, 0.8],
        interface_checked=True,
        missing_column_rejected=True,
        invalid_numeric_rejected=True,
        unseen_category_handled=True,
        training_rows=10,
    )


def test_host_scores_private_labels_and_checks_prediction_integrity():
    labels = pd.DataFrame({"row_id": [1, 2, 3, 4], "churn": [0, 1, 0, 1]})
    protocol = {
        "task_type": "binary_classification",
        "repeat_tolerance": 1e-12,
        "thresholds": {name: 0.8 for name in ("f1", "roc_auc", "precision", "recall")},
    }
    result = good_worker()
    measured = score_predictions(result, labels, protocol)
    assert measured["metrics"] == {name: 1.0 for name in protocol["thresholds"]}
    result.repeat_probabilities[0] = 0.3
    assert score_predictions(result, labels, protocol)["stability"] is False
    result.row_ids.reverse()
    with pytest.raises(WorkflowFailure, match="alignment"):
        score_predictions(result, labels, protocol)
    with pytest.raises(ValidationError):
        WorkerResult.model_validate(good_worker().model_dump() | {"claimed_f1": 1.0})


@pytest.mark.parametrize("failure", ["timeout", "oom", "cleanup"])
def test_executor_failure_cleanup_without_host_execution(tmp_path, monkeypatch, failure):
    from algofactory.execution import docker as module

    code = tmp_path / "candidate.py"
    code.write_text(files("algofactory.generation").joinpath("templates/logistic.txt").read_text())
    train, evaluation = tmp_path / "train.csv", tmp_path / "eval.csv"
    train.write_text("training fixture")
    evaluation.write_text("features only")
    seen = []

    def command(args, **kwargs):
        seen.append(args)
        if "create" in args:
            mount = args[args.index("--mount") + 1]
            path = Path(mount.split("src=", 1)[1].split(",dst=")[0])
            assert set(p.name for p in path.iterdir()) == {
                "candidate.py",
                "config.json",
                "train.csv",
                "evaluation_features.csv",
            }
        if "start" in args:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(args, 1)
            return SimpleNamespace(returncode=137, stdout="", stderr="")
        if "inspect" in args:
            return SimpleNamespace(returncode=0, stdout='{"OOMKilled":true}', stderr="")
        if "rm" in args and failure == "cleanup":
            return SimpleNamespace(returncode=1, stdout="", stderr="cleanup fixture")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", command)
    executor = DockerExecutor.__new__(DockerExecutor)
    executor.binary, executor.approval, executor.environment = (
        "docker",
        {"image_id": "sha256:" + "a" * 64},
        {},
    )
    with pytest.raises(
        WorkflowFailure,
        match={
            "timeout": "execution_timeout",
            "oom": "resource_limit_exceeded",
            "cleanup": "container_cleanup_failed",
        }[failure],
    ):
        executor.execute(
            code,
            train,
            evaluation,
            {"stage": "validation"},
            tmp_path / "execution",
            ExecutionBudget(),
        )
    assert any("rm" in args and "--force" in args for args in seen)
    assert not list((tmp_path / "execution").glob("input-*"))


@pytest.mark.parametrize(
    "fault, category",
    [("unsafe_code", "unapproved_import"), ("invalid_json", "invalid_structured_response")],
)
def test_rejected_workflows_have_reports_and_no_test_access(
    tmp_path, dataset, monkeypatch, fault, category
):
    import algofactory.orchestrator as module

    monkeypatch.setattr(module, "DockerExecutor", lambda *args: pytest.fail("must not execute"))
    directory = tmp_path / "run"
    report = invoke(directory, dataset, fault)
    assert report["status"] == "failed" and report["error_category"] == category
    assert report["persisted"]
    assert not (directory / "test-access.json").exists()
    with KnowledgeStore(tmp_path / "knowledge.sqlite") as store:
        assert store.get_workflow(report["workflow_id"])["status"] == "failed"


def test_missing_docker_fails_closed(tmp_path, dataset, monkeypatch):
    from algofactory.execution import docker as module

    def unavailable():
        raise WorkflowFailure("docker_missing")

    monkeypatch.setattr(module, "locate_docker", unavailable)
    report = invoke(tmp_path / "run", dataset)
    assert report["status"] == "failed" and report["error_category"] == "docker_missing"
    assert report["validation"]["functional"]["status"] == "not_run"
    assert report["validation"]["test_metrics"] == {}


def test_writeback_failure_never_accepted(tmp_path, dataset, monkeypatch):
    def fail(self, record):
        raise sqlite3.OperationalError("controlled test failure")

    monkeypatch.setattr(KnowledgeStore, "_insert_workflow", fail)
    report = invoke(tmp_path / "run", dataset, "invalid_json")
    assert report["status"] == "failed"
    assert report["error_category"] == "knowledge_writeback_failed"
    assert report["persisted"] is False


docker_test = pytest.mark.skipif(
    os.environ.get("ALGOFACTORY_DOCKER_TESTS") != "1",
    reason="Explicit Docker integration opt-in required",
)


@pytest.mark.docker
@docker_test
def test_real_docker_mock_closure_repeat_and_holdout(tmp_path, dataset):
    first = invoke(tmp_path / "first", dataset)
    assert first["status"] == "accepted", first
    second = invoke(tmp_path / "second", dataset)
    assert second["status"] == "accepted", second
    assert first["validation"]["validation_metrics"] == second["validation"]["validation_metrics"]
    assert first["validation"]["test_metrics"] == second["validation"]["test_metrics"]
    assert first["validation"]["final_test_evaluated"]
    with KnowledgeStore(tmp_path / "knowledge.sqlite") as store:
        record = store.get_workflow(first["workflow_id"])
        assert record["status"] == "accepted"
        assert len(store.search(entity_type="ValidationRun")) == 2
        assert store.search(entity_type="Experience") == []
    trace = json.loads((tmp_path / "first/trace.json").read_text())
    assert [item["state"] for item in trace] == [
        "received",
        "parsed",
        "retrieved",
        "planned",
        "generated",
        "checked",
        "executed",
        "validated",
        "persisted",
        "accepted",
    ]
    with pytest.raises(WorkflowFailure, match="run_directory"):
        invoke(tmp_path / "first", dataset)
    for stage in ("validation", "test"):
        evidence = json.loads((tmp_path / f"first/{stage}-execution/execution.json").read_text())
        assert evidence["input_files"] == [
            "candidate.py",
            "config.json",
            "evaluation_features.csv",
            "train.csv",
        ]


@pytest.mark.docker
@docker_test
def test_real_docker_interface_failure_does_not_open_test_set(tmp_path, dataset):
    report = invoke(tmp_path / "failure", dataset, "missing_predict_proba")
    assert report["status"] == "failed"
    assert report["error_category"] == "interface_missing_predict_proba"
    assert not report["test_attempted"]
    assert not (tmp_path / "failure/test-access.json").exists()
    assert report["persisted"]


@pytest.mark.docker
@docker_test
def test_api_adapter_uses_same_workflow_with_simulated_transport(tmp_path, dataset):
    operations = []
    fixture = MockWorkflowProvider()

    def transport(url, headers, body, timeout):
        payload = json.loads(body)
        request = json.loads(payload["messages"][1]["content"])
        operations.append(request["operation"])
        content = fixture._raw(ProviderRequest(**request, instruction="test fixture"), {})
        return json.dumps(
            {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        ).encode()

    provider = APIProvider(
        APIConfig(
            base_url="https://example.invalid/v1",
            model="simulated-workflow-fixture",
            api_key=SecretStr("test-only"),
            max_cost_usd=2.0,
            input_usd_per_million=1.0,
            output_usd_per_million=2.0,
        ),
        transport,
    )
    report = invoke(tmp_path / "simulated-api", dataset, provider=provider)
    assert report["status"] == "accepted", report
    assert operations == ["parse_task", "extract_knowledge", "plan_algorithm", "generate_code"]
    assert all(item.mode == "api" for item in provider.audit)
