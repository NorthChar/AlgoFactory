"""Task boundaries, data hygiene, private scoring and shared real-Docker workflow."""

import hashlib
import json
import os
from importlib.resources import files
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from algofactory.banking import clean_frames, import_banking77, normalize
from algofactory.datasets import verify_dataset, write_json
from algofactory.execution.worker import checked_features, evaluate
from algofactory.generation.safety import check_code
from algofactory.knowledge.extraction import ingest_document
from algofactory.knowledge.store import KnowledgeStore, canonical
from algofactory.llm.workflow_mock import MockWorkflowProvider
from algofactory.orchestrator import run_workflow
from algofactory.schemas.contracts import TaskSpec
from algofactory.schemas.knowledge import SourceDocument
from algofactory.tasks import BANKING77, CHURN, compatible_evidence
from algofactory.validation.protocol import calibrate, load_protocol, text_reference_pipeline
from algofactory.validation.scoring import score_predictions
from algofactory.workflow_models import WorkerResult, WorkflowFailure

ROOT = Path(__file__).resolve().parents[1]


def frame(rows):
    return pd.DataFrame(rows, columns=["text", "category"])


def test_hygiene_normalizes_preserves_test_and_records_lineage():
    train = frame([("  Same\tText ", "a"), ("same text", "a"), ("overlap", "b"), ("safe", "b")])
    test = frame([("OVERLAP", "b"), ("test only", "a"), ("test only", "a")])
    cleaned, heldout, removed = clean_frames(train, test)
    assert cleaned.source_row.tolist() == [0, 3]
    assert heldout[["text", "category"]].equals(test)
    assert removed == [
        {"source_row": 1, "reason": "training_duplicate"},
        {"source_row": 2, "reason": "official_test_overlap"},
    ]
    assert normalize("\tStraße  HERE ") == "strasse here"


@pytest.mark.parametrize("bad", [None, 12, "", " \t "])
def test_hygiene_and_worker_reject_invalid_text(bad):
    with pytest.raises(WorkflowFailure, match="invalid_text"):
        clean_frames(frame([(bad, "a")]), frame([("valid", "a")]))
    with pytest.raises(ValueError):
        checked_features(pd.DataFrame({"text": [bad]}), ["text"], ["text"])


def test_conflicting_normalized_labels_stop_before_removing_overlap():
    with pytest.raises(WorkflowFailure, match="conflicting_labels"):
        clean_frames(frame([("SAME", "a")]), frame([("same", "b")]))


def test_text_template_safe_and_training_vocabulary_excludes_validation():
    check_code(files("algofactory.generation").joinpath("templates/text_logistic.txt").read_text())
    reference = text_reference_pipeline(42)
    train = pd.DataFrame(
        {"text": ["apple red", "apple green", "sky blue", "sky grey", "bank loan", "bank card"]}
    )
    reference.fit(train, [0, 0, 1, 1, 2, 2])
    vectorizer = reference.named_steps["preprocess"].named_transformers_["text"]
    before = dict(vectorizer.vocabulary_)
    reference.predict(pd.DataFrame({"text": ["validationonlytoken"]}))
    assert vectorizer.vocabulary_ == before and "validationonlytoken" not in before


def text_result():
    return WorkerResult(
        status="ok",
        classes=[0, 1, 2],
        row_ids=[10, 11, 12],
        predictions=[0, 1, 2],
        repeat_predictions=[0, 1, 2],
        probabilities=[[0.8, 0.1, 0.1], [0.1, 0.8, 0.1], [0.1, 0.1, 0.8]],
        repeat_probabilities=[[0.8, 0.1, 0.1], [0.1, 0.8, 0.1], [0.1, 0.1, 0.8]],
        interface_checked=True,
        missing_column_rejected=True,
        invalid_text_rejected=True,
        unseen_text_handled=True,
    )


def text_protocol():
    return {
        "task_type": "multiclass_classification",
        "target": "intent",
        "class_labels": [0, 1, 2],
        "class_names": ["a", "b", "c"],
        "thresholds": {"macro_f1": 0.5},
        "repeat_tolerance": 1e-12,
    }


def test_private_multiclass_scoring_per_class_confusion_and_stability():
    labels = pd.DataFrame({"row_id": [10, 11, 12], "intent": [0, 1, 2]})
    result = text_result()
    measured = score_predictions(result, labels, text_protocol())
    assert measured["metrics"] == {"macro_f1": 1.0, "accuracy": 1.0}
    assert measured["class_details"]["confusion_matrix"] == np.eye(3, dtype=int).tolist()
    assert measured["class_details"]["per_class"]["a"]["support"] == 1
    result.repeat_probabilities[0] = [0.7, 0.2, 0.1]
    assert not score_predictions(result, labels, text_protocol())["stability"]


@pytest.mark.parametrize(
    "change, category",
    [
        ({"classes": [2, 1, 0]}, "class_order"),
        ({"predictions": [0, 1, 77]}, "class_predictions"),
        ({"row_ids": [12, 11, 10]}, "alignment"),
        ({"probabilities": [[0.8, 0.2]] * 3}, "probability_shape"),
        ({"probabilities": [[0.1, 0.1, 0.1]] * 3}, "probability_sums"),
        ({"probabilities": [[-0.1, 0.5, 0.6]] * 3}, "probabilities"),
        ({"repeat_probabilities": [[0.1, 0.1]] * 3}, "probability_shape"),
    ],
)
def test_host_rejects_invalid_multiclass_output(change, category):
    result = WorkerResult.model_validate(text_result().model_dump() | change)
    with pytest.raises(WorkflowFailure, match=category):
        score_predictions(
            result, pd.DataFrame({"row_id": [10, 11, 12], "intent": [0, 1, 2]}), text_protocol()
        )


def test_nonfinite_worker_output_and_wrong_target_rejected():
    with pytest.raises(ValidationError):
        WorkerResult.model_validate(
            text_result().model_dump() | {"probabilities": [[float("nan")] * 3] * 3}
        )
    with pytest.raises(WorkflowFailure, match="label_space"):
        score_predictions(
            text_result(),
            pd.DataFrame({"row_id": [10, 11, 12], "churn": [0, 1, 1]}),
            text_protocol(),
        )


def test_worker_text_checks_and_class_mapping_with_trusted_factory():
    train = pd.DataFrame(
        {
            "row_id": range(6),
            "text": ["apple red", "apple green", "sky blue", "sky grey", "bank loan", "bank card"],
            "intent": [0, 0, 1, 1, 2, 2],
        }
    )
    config = BANKING77.intent() | {"seed": 42, "stage": "validation", "class_labels": [0, 1, 2]}
    result = evaluate(
        lambda cfg: text_reference_pipeline(cfg["seed"]), train, train[["row_id", "text"]], config
    )
    assert result["status"] == "ok", result
    assert (
        result["invalid_text_rejected"]
        and result["unseen_text_handled"]
        and result["missing_column_rejected"]
    )
    config["class_labels"] = [2, 1, 0]
    result = evaluate(
        lambda cfg: text_reference_pipeline(cfg["seed"]), train, train[["row_id", "text"]], config
    )
    assert result["error_category"] == "invalid_probability_interface"


def test_shared_knowledge_store_filters_task_and_data_kind(tmp_path):
    with KnowledgeStore(tmp_path / "knowledge.sqlite") as store:
        for profile in (CHURN, BANKING77):
            source = SourceDocument.from_text(
                profile.document, (ROOT / "data" / profile.document).read_text()
            )
            ingest_document(source, MockWorkflowProvider(), store)
        entries = store.search(task_type=BANKING77.task_type)
        compatible = [e for e in entries if compatible_evidence(e, BANKING77, source.id)]
        assert {e["record"]["type"] for e in compatible} == {"Algorithm", "Capability"}
        assert not any(compatible_evidence(e, CHURN, source.id) for e in entries)
        wrong = json.loads(json.dumps(compatible[0]))
        key = "conditions" if wrong["record"]["type"] == "Capability" else "applicability"
        wrong["record"][key]["data_kind"] = "tabular"
        assert not compatible_evidence(wrong, BANKING77, source.id)
        assert store.search(entity_type="Experience") == []


def test_multiclass_contract_rejects_binary_metrics_and_missing_mapping():
    base = {
        "task_id": "task:text",
        "description": "text",
        "task_type": "multiclass_classification",
        "target": "intent",
        "feature_schema": [{"name": "text", "dtype": "text"}],
        "data_fingerprint": "a" * 64,
        "split_id": "split:text",
        "metrics": [{"name": "macro_f1", "direction": "maximize"}],
        "class_labels": [0, 1, 2],
    }
    TaskSpec.model_validate(base)
    for change in (
        {"class_labels": []},
        {"class_labels": [0, 0, 2]},
        {"metrics": [{"name": "roc_auc", "direction": "maximize"}]},
    ):
        with pytest.raises(ValidationError):
            TaskSpec.model_validate(base | change)


def test_import_rejects_unpinned_data_without_network(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "train.csv").write_text("tampered")
    with pytest.raises(WorkflowFailure, match="raw_fingerprint"):
        import_banking77(tmp_path / "dataset", raw)


# Full source data is an explicit prerequisite, not silently downloaded by unit tests.
docker_test = pytest.mark.skipif(
    os.environ.get("ALGOFACTORY_DOCKER_TESTS") != "1",
    reason="Explicit Docker integration opt-in required",
)


@pytest.fixture
def banking_data():
    path = Path(os.environ.get("ALGOFACTORY_BANKING_DATA", ROOT / "runtime/banking77-data"))
    assert path.is_dir(), "Run prepare-banking77 before full Phase 2.5 verification"
    verify_dataset(path)
    return path


@pytest.mark.docker
@docker_test
def test_official_import_reproducibility_and_tamper_rejection(tmp_path, banking_data):
    original = verify_dataset(banking_data)
    copy = tmp_path / "dataset"
    imported = import_banking77(copy, banking_data / "raw")
    assert imported["files"] == original["files"]
    audit = json.loads((copy / "audit.json").read_text())
    assert audit["split_counts"] == {"train": 7993, "validation": 1999, "test": 3080}
    assert len(audit["removed_training_rows"]) == 11
    groups = []
    for stage in ("train", "validation", "test"):
        path = "train.csv" if stage == "train" else f"{stage}_features.csv"
        groups.append(set(pd.read_csv(copy / path).text.map(normalize)))
    assert not (groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])
    assert len(audit["official_test_duplicate_rows"]) == 1
    changed = pd.read_csv(copy / "validation_features.csv")
    changed.loc[0, "text"] = "tampered"
    changed.to_csv(copy / "validation_features.csv", index=False)
    imported["files"]["validation_features.csv"] = hashlib.sha256(
        (copy / "validation_features.csv").read_bytes()
    ).hexdigest()
    write_json(copy / "manifest.json", imported)
    with pytest.raises(WorkflowFailure, match="processed_data"):
        verify_dataset(copy)


@pytest.mark.docker
@docker_test
def test_calibration_uses_no_test_data_and_rejects_protocol_mixup(
    tmp_path, banking_data, monkeypatch
):
    import algofactory.validation.protocol as module

    manifest = verify_dataset(banking_data)
    monkeypatch.setattr(module, "verify_dataset", lambda path: manifest)
    original = pd.read_csv
    reads = []

    def read(path, *args, **kwargs):
        reads.append(Path(path).name)
        assert "test" not in Path(path).name
        return original(path, *args, **kwargs)

    monkeypatch.setattr(module.pd, "read_csv", read)
    path = tmp_path / "protocol.json"
    protocol = calibrate(banking_data, path)
    assert reads == ["train.csv", "validation_features.csv", "validation_labels.csv"]
    for change in (
        {"class_names": list(reversed(manifest["class_names"]))},
        {"task_type": "binary_classification"},
        {"thresholds": {"roc_auc": 0.5}},
        {"split_id": "split:other"},
        {"data_fingerprint": "a" * 64},
    ):
        modified = {k: v for k, v in (protocol | change).items() if k != "config_hash"}
        modified["config_hash"] = hashlib.sha256(canonical(modified).encode()).hexdigest()
        write_json(path, modified)
        with pytest.raises(WorkflowFailure):
            load_protocol(path, manifest)


def invoke(directory, dataset, provider=None, document=None, request=None):
    return run_workflow(
        directory=directory,
        dataset_dir=dataset,
        db_path=directory.parent / "knowledge.sqlite",
        approval_path=ROOT / "runtime/docker-image.json",
        requirements_path=ROOT / "requirements.txt",
        knowledge_document=document or ROOT / "data/banking77.txt",
        request=request or BANKING77.request,
        provider=provider or MockWorkflowProvider(),
    )


@pytest.mark.docker
@docker_test
def test_banking_real_docker_closure_and_fail_closed_task_boundaries(tmp_path, banking_data):
    report = invoke(tmp_path / "normal", banking_data)
    assert report["status"] == "accepted", report
    assert report["validation"]["test_metrics"]["macro_f1"] >= report["thresholds"]["macro_f1"]
    details = json.loads((tmp_path / "normal/test-class-details.json").read_text())
    assert len(details["confusion_matrix"]) == 77
    for stage in ("validation", "test"):
        execution = json.loads((tmp_path / f"normal/{stage}-execution/execution.json").read_text())
        assert execution["input_files"] == [
            "candidate.py",
            "config.json",
            "evaluation_features.csv",
            "train.csv",
        ]
    with KnowledgeStore(tmp_path / "knowledge.sqlite") as store:
        assert store.get_workflow(report["workflow_id"])["status"] == "accepted"
        assert store.search(entity_type="Dataset")[0]["record"]["field_schema"] == {
            "text": "text",
            "intent": "class_label",
        }
    for name, kwargs, category in (
        ("wrong-intent", {"request": CHURN.request}, "intent_feature_mismatch"),
        (
            "wrong-knowledge",
            {"document": ROOT / "data/customer_churn.txt"},
            "empty_knowledge_retrieval",
        ),
        (
            "interface",
            {"provider": MockWorkflowProvider("missing_predict_proba")},
            "interface_missing_predict_proba",
        ),
        ("unsafe", {"provider": MockWorkflowProvider("unsafe_code")}, "unapproved_import"),
        ("json", {"provider": MockWorkflowProvider("invalid_json")}, "invalid_structured_response"),
    ):
        failed = invoke(tmp_path / name, banking_data, **kwargs)
        assert failed["status"] == "failed" and failed["error_category"] == category, failed
        assert failed["persisted"] and not failed["test_attempted"]
        assert not (tmp_path / name / "test-access.json").exists()
