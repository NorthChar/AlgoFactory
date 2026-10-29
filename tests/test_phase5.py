"""Regression and repository plugin boundaries, including real Docker execution."""

import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import pytest
from sklearn.metrics import mean_absolute_error

from algofactory.datasets import verify_dataset, write_json
from algofactory.generation.configuration import required_configuration, validate_configuration
from algofactory.knowledge.store import KnowledgeStore, canonical
from algofactory.llm.workflow_mock import MockWorkflowProvider
from algofactory.orchestrator import run_workflow
from algofactory.plugins import MetricPlugin, PluginRegistry, TemplatePlugin, default_registry
from algofactory.regression import generate_regression
from algofactory.tasks import REGRESSION
from algofactory.validation.protocol import calibrate, load_protocol
from algofactory.validation.scoring import score_predictions
from algofactory.workflow_models import WorkerResult, WorkflowFailure

ROOT = Path(__file__).resolve().parents[1]


def test_regression_data_frozen_disjoint_and_consistent(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    manifest = generate_regression(a)
    assert generate_regression(b) == manifest == verify_dataset(a)
    assert [len(manifest["split_indices"][s]) for s in ("train", "validation", "test")] == [
        360,
        120,
        120,
    ]
    with pytest.raises(ValueError):
        generate_regression(a)
    rows = pd.read_csv(a / "train.csv")
    rows.loc[0, "value"] += 1
    rows.to_csv(a / "train.csv", index=False)
    manifest["files"]["train.csv"] = hashlib.sha256((a / "train.csv").read_bytes()).hexdigest()
    write_json(a / "manifest.json", manifest)
    with pytest.raises(WorkflowFailure, match="schema_or_order"):
        verify_dataset(a)


def test_regression_calibration_does_not_train_or_score_test(tmp_path, monkeypatch):
    generate_regression(tmp_path / "data")
    directory = tmp_path / "data"
    import algofactory.regression as module

    original = module.pd.read_csv
    reads = []

    def capture(path, *args, **kwargs):
        reads.append(Path(path).name)
        return original(path, *args, **kwargs)

    manifest = verify_dataset(directory)
    monkeypatch.setattr(module.pd, "read_csv", capture)
    protocol = module.calibrate_regression(directory, directory / "protocol.json", manifest)
    assert not any("test" in r for r in reads)
    assert protocol["thresholds"] == {"mae": 1.0, "rmse": 1.5}
    assert load_protocol(directory / "protocol.json", manifest) == protocol
    protocol["thresholds"]["mae"] = 100.0
    protocol["config_hash"] = hashlib.sha256(
        canonical({k: v for k, v in protocol.items() if k != "config_hash"}).encode()
    ).hexdigest()
    write_json(directory / "protocol.json", protocol)
    with pytest.raises(WorkflowFailure, match="invalid_validation_protocol"):
        load_protocol(directory / "protocol.json", manifest)


def scored():
    result = WorkerResult(
        status="ok",
        classes=[],
        row_ids=[1, 2],
        predictions=[1.5, 3.0],
        repeat_predictions=[1.5, 3.0],
        interface_checked=True,
        missing_column_rejected=True,
        invalid_numeric_rejected=True,
    )
    labels = pd.DataFrame({"row_id": [1, 2], "value": [1.0, 2.0]})
    protocol = {
        "task_type": "regression",
        "thresholds": {"mae": 1.0, "rmse": 1.5},
        "repeat_tolerance": 1e-12,
    }
    return result, labels, protocol


def test_regression_continuous_output_minimize_and_stability():
    result, labels, protocol = scored()
    score = score_predictions(result, labels, protocol)
    assert score["metrics"]["mae"] == 0.75 and score["metrics_passed"] and score["stability"]
    result.predictions = [10.5, 12.0]
    result.repeat_predictions = [10.5, 12.0]
    assert not score_predictions(result, labels, protocol)["metrics_passed"]
    result.repeat_predictions = [10.5, 12.1]
    assert not score_predictions(result, labels, protocol)["stability"]


@pytest.mark.parametrize(
    "change",
    [
        {"predictions": [1.0]},
        {"row_ids": [2, 1]},
        {"probabilities": [0.2, 0.8]},
        {"classes": [0, 1]},
    ],
)
def test_regression_wrong_output_rejected(change):
    result, labels, protocol = scored()
    for name, value in change.items():
        setattr(result, name, value)
    with pytest.raises(WorkflowFailure):
        score_predictions(result, labels, protocol)


def test_plugins_extend_without_orchestrator_changes_and_fail_closed():
    registry = PluginRegistry()
    code = default_registry().template("ridge.txt", "regression")
    plugin = TemplatePlugin("demo_ridge", "regression", code)
    registry.register_template(plugin)
    registry.register_metric(MetricPlugin("mae", "regression", "minimize", mean_absolute_error))
    assert registry.score("mae", "regression", [1, 2], [1.5, 2.5]) == 0.5
    assert registry.template("demo_ridge", "regression") == code
    with pytest.raises(ValueError, match="duplicate"):
        registry.register_template(plugin)
    with pytest.raises(ValueError, match="duplicate"):
        registry.register_metric(MetricPlugin("mae", "regression", "minimize", mean_absolute_error))
    with pytest.raises(WorkflowFailure, match="task_mismatch"):
        registry.template("demo_ridge", "binary_classification")
    with pytest.raises(WorkflowFailure):
        registry.register_template(TemplatePlugin("bad", "regression", "import os\n"))
    registry.register_metric(
        MetricPlugin("rmse", "regression", "minimize", lambda y, p: float("nan"))
    )
    with pytest.raises(WorkflowFailure, match="invalid_metric"):
        registry.score("rmse", "regression", [1], [1])


def test_regression_fixed_pipeline_and_parameters():
    code = default_registry().template("ridge.txt", "regression")
    assert validate_configuration(code, required_configuration("ridge"))["status"] == "passed"
    for changed in (
        code.replace("alpha=1.0", "alpha=10.0"),
        code.replace('strategy="median"', 'strategy="mean"'),
        code.replace('config["numeric_features"]', '["x1"]'),
    ):
        with pytest.raises(WorkflowFailure):
            validate_configuration(changed, required_configuration("ridge"))


@pytest.mark.docker
@pytest.mark.skipif(
    os.environ.get("ALGOFACTORY_DOCKER_TESTS") != "1", reason="Enable real Docker explicitly"
)
def test_regression_shared_workflow_real_docker(tmp_path):
    dataset = tmp_path / "data"
    generate_regression(dataset)
    calibrate(dataset, dataset / "protocol.json")
    registry = default_registry()
    registry.register_template(
        TemplatePlugin(
            "extension_ridge",
            "regression",
            registry.template("ridge.txt", "regression")
            + "\n# Repository plugin extension used in this run.\n",
        )
    )
    report = run_workflow(
        directory=tmp_path / "run",
        dataset_dir=dataset,
        db_path=tmp_path / "knowledge.sqlite",
        approval_path=ROOT / "runtime/docker-image.json",
        requirements_path=ROOT / "requirements.txt",
        knowledge_document=ROOT / "data/synthetic_regression.txt",
        request=REGRESSION.request,
        provider=MockWorkflowProvider(
            plugins=registry, template_overrides={"regression": "extension_ridge"}
        ),
    )
    assert report["status"] == "accepted", report["error_category"]
    assert "Repository plugin extension" in (tmp_path / "run/candidate.py").read_text()
    assert set(report["validation"]["test_metrics"]) == {"mae", "rmse"}
    assert report["test_attempted"] and report["persisted"]
    with KnowledgeStore(tmp_path / "knowledge.sqlite") as store:
        assert store.get_workflow(report["workflow_id"])["status"] == "accepted"
        assert store.search(task_type="regression")
    predictions = json.loads((tmp_path / "run/validation-execution/predictions.json").read_text())
    assert any(v != int(v) for v in predictions["predictions"])
    assert predictions["probabilities"] == []
