"""Business scope changes must reach data, scoring, generation and the confirmed UI."""

import copy
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from algofactory.banking import derive_banking77
from algofactory.datasets import sha256_file, verify_dataset, write_json
from algofactory.experiments import ExperimentConfig
from algofactory.knowledge.extraction import ingest_document
from algofactory.knowledge.store import KnowledgeStore
from algofactory.llm.workflow_mock import MockWorkflowProvider
from algofactory.planning import SearchPolicy, rank_candidates
from algofactory.requirement_understanding import configuration_request
from algofactory.requirements import interpret_requirement
from algofactory.schemas.knowledge import SourceDocument
from algofactory.tasks import compatible_evidence, profile_for
from algofactory.validation.protocol import calibrate, load_protocol
from algofactory.web import service
from algofactory.web.data_view import dataset_snapshot
from algofactory.workflow_models import WorkflowFailure

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime/banking77-data"
NAMES = ["card_arrival", "lost_or_stolen_card", "pending_transfer"]


@pytest.fixture(scope="module")
def variants(tmp_path_factory):
    if not (SOURCE / "manifest.json").is_file():
        pytest.skip("prepared BANKING77 data required")
    root = tmp_path_factory.mktemp("intent-goals")
    configs = [
        ExperimentConfig(goal="subset", intents=NAMES),
        ExperimentConfig(goal="subset", intents=NAMES[:2]),
        ExperimentConfig(goal="one_vs_rest", intents=[NAMES[1]], objective="recall"),
    ]
    result = []
    for i, config in enumerate(configs):
        directory = root / str(i)
        manifest = derive_banking77(SOURCE, directory, config)
        result.append((config, directory, manifest))
    return result


@pytest.mark.parametrize(
    "kwargs",
    [
        {"goal": "subset", "intents": ["lost_or_stolen_card"]},
        {"goal": "one_vs_rest", "intents": NAMES},
        {"goal": "full", "intents": NAMES},
        {"goal": "subset", "intents": ["new_label", "x"]},
        {"goal": "subset", "intents": [NAMES[0], NAMES[0]]},
        {"objective": "recall"},
        {"goal": "subset", "intents": NAMES, "objective": "recall"},
    ],
)
def test_invalid_scope_cannot_be_submitted(kwargs):
    with pytest.raises(ValueError):
        ExperimentConfig(**kwargs)


def test_derived_splits_keep_membership_and_remap_exactly(variants):
    parent = verify_dataset(SOURCE)
    original = pd.read_csv(SOURCE / "all_rows.csv").set_index("row_id")
    for config, directory, manifest in variants:
        assert verify_dataset(directory) == manifest
        config.validate_manifest(manifest)
        rows = pd.read_csv(directory / "all_rows.csv").set_index("row_id")
        assert rows.text.equals(original.loc[rows.index].text)
        for stage, ids in manifest["split_indices"].items():
            assert set(ids) <= set(parent["split_indices"][stage])
            assert set(rows.loc[ids].intent) == set(manifest["class_labels"])
        if config.goal == "subset":
            names = [parent["class_names"][i] for i in original.loc[rows.index].intent]
            assert [config.intents[i] for i in rows.intent] == names
            assert len(rows) < len(original)
        else:
            assert len(rows) == len(original)
            positive = parent["class_names"].index(config.intents[0])
            assert rows.intent.tolist() == (original.intent == positive).astype(int).tolist()
        assert interpret_requirement(configuration_request(config)).experiment == config
        with pytest.raises(ValueError, match="selection_mismatch"):
            ExperimentConfig().validate_manifest(manifest)
    assert len({m["data_fingerprint"] for _, _, m in variants}) == 3
    assert len({m["split_id"] for _, _, m in variants}) == 3


def test_rewritten_fingerprint_cannot_hide_wrong_mapping(variants, tmp_path):
    import shutil

    _, source, _ = variants[0]
    directory = tmp_path / "tampered"
    shutil.copytree(source, directory)
    manifest = verify_dataset(directory)
    frame = pd.read_csv(directory / "train.csv")
    frame.loc[0, "intent"] = (int(frame.loc[0, "intent"]) + 1) % 3
    frame.to_csv(directory / "train.csv", index=False)
    manifest["files"]["train.csv"] = sha256_file(directory / "train.csv")
    write_json(directory / "manifest.json", manifest)
    with pytest.raises(WorkflowFailure, match="processed_data_mismatch"):
        verify_dataset(directory)


def test_binary_protocol_and_retrieval_are_scoped(variants, tmp_path):
    config, directory, manifest = variants[-1]
    protocol = calibrate(directory, directory / "protocol.json")
    assert protocol["task_type"] == "binary_classification"
    assert set(protocol["thresholds"]) == {"macro_f1", "recall"}
    assert protocol["test_used_for_calibration"] is False
    assert protocol["baseline"]["fit_rows"] == 7993
    assert set(protocol["baseline"]["validation_metrics"]) == {
        "macro_f1",
        "accuracy",
        "f1",
        "precision",
        "recall",
        "roc_auc",
    }
    assert load_protocol(directory / "protocol.json", manifest) == protocol
    with pytest.raises(WorkflowFailure, match="dataset_mismatch"):
        load_protocol(directory / "protocol.json", variants[0][2])
    document = ROOT / "data/banking-intent-tasks.txt"
    source = SourceDocument.from_text(document.name, document.read_text())
    with KnowledgeStore(tmp_path / "knowledge.sqlite") as store:
        ingest_document(source, MockWorkflowProvider(), store)
        profile = profile_for(manifest)
        matches = store.search(task_type=profile.task_type, source_id=source.id, data_kind="text")
        evidence = [e for e in matches if compatible_evidence(e, profile, source.id)]
    assert {e["record"]["type"] for e in evidence} == {"Capability", "Algorithm"}


def test_recall_preference_changes_selection_without_waiving_gates():
    base = {"status": "validated", "config_hash": "h", "split_id": "s", "test_attempted": False}
    first = base | {
        "algorithm": "text_logistic",
        "validation_metrics": {"macro_f1": 0.9, "accuracy": 0.99, "recall": 0.7},
    }
    second = base | {
        "algorithm": "text_nb",
        "validation_metrics": {"macro_f1": 0.8, "accuracy": 0.97, "recall": 0.9},
    }
    failed = second | {
        "status": "failed",
        "validation_metrics": {"macro_f1": 0.4, "accuracy": 0.1, "recall": 1.0},
    }
    protocol = {"config_hash": "h", "split_id": "s"}
    assert rank_candidates([first, second, failed], SearchPolicy(), protocol)[0] == first
    protocol["selection"] = {"objective": "recall"}
    assert rank_candidates([first, second, failed], SearchPolicy(), protocol) == [second, first]


def test_unknown_and_conflicting_scope_text_never_defaults():
    for text in [
        "开发英文银行咨询分类算法；识别单个意图：贷款违约",
        "开发英文银行咨询分类算法；输出77类意图及概率；识别单个意图：lost_or_stolen_card",
        "开发英文银行咨询分类算法；只区分这些意图：card_arrival",
        "开发英文银行咨询分类算法；优先减少漏判",
        "开发英文银行咨询分类算法；识别单个意图：lost_or_stolen_card；保证不误报",
    ]:
        result = interpret_requirement(text)
        assert result.issues and result.experiment is None


def test_scope_change_invalidates_confirmation(variants):
    config, _, _ = variants[0]
    values = dict(experiment=config, request=configuration_request(config))
    draft = service.RunSettings.model_construct(**values)
    values["requirement_confirmation"] = draft.confirmation_digest()
    saved = service.RunSettings(**values).model_dump(mode="json")
    changed = copy.deepcopy(saved)
    changed["experiment"]["intents"] = NAMES[:2]
    with pytest.raises(ValueError):
        service.RunSettings.model_validate(changed)


def test_task_local_dataset_has_no_full_task_fallback(tmp_path):
    with pytest.raises(OSError):
        dataset_snapshot(tmp_path, "runtime/web-jobs/" + "a" * 32 + "/run")


def test_workbench_subset_and_binary_require_confirmation(monkeypatch):
    monkeypatch.setattr(service.Jobs, "submit", Mock(return_value="a" * 32))
    app = AppTest.from_file(str(ROOT / "src/algofactory/web/app.py"), default_timeout=20).run()
    next(b for b in app.button if b.label == "开始开发银行分类算法").click().run()
    next(r for r in app.radio if r.label == "你要开发哪一种算法？").set_value("subset").run()
    next(r for r in app.radio if r.label == "需求理解方式").set_value("rules").run()
    next(b for b in app.button if b.label == "解析并检查需求").click().run()
    assert not app.exception
    assert any("指定类别分类" in i.value for i in app.markdown)
    assert not service.Jobs.submit.called
    next(r for r in app.radio if r.label == "你要开发哪一种算法？").set_value("one_vs_rest").run()
    next(r for r in app.radio if r.label == "你更重视什么？").set_value("recall").run()
    next(b for b in app.button if b.label == "解析并检查需求").click().run()
    assert not app.exception
    assert "识别单个意图" in next(t for t in app.text_area if t.label == "开发需求").value
    assert not service.Jobs.submit.called


def test_recall_preference_changes_actual_generated_parameters():
    from algofactory.generation.configuration import validate_configuration
    from algofactory.llm.providers import ProviderRequest
    from algofactory.workflow_models import GeneratedCode

    config = ExperimentConfig(
        goal="one_vs_rest", intents=["lost_or_stolen_card"], objective="recall"
    )
    for algorithm in config.algorithms:
        required = config.configuration(algorithm)
        source = {
            "task_profile": "banking77",
            "algorithm_key": algorithm,
            "required_configuration": required,
            "experiment_hash": config.digest,
            "plan": {"plan_id": "plan:test"},
        }
        generated = MockWorkflowProvider().complete(
            ProviderRequest(
                role="builder", operation="generate_code", instruction="fixture", source=source
            ),
            GeneratedCode,
        )
        assert validate_configuration(generated.code, required)["status"] == "passed"
        if algorithm == "text_logistic":
            assert required["classifier_parameters"]["class_weight"] == "balanced"
        else:
            assert required["classifier_parameters"]["fit_prior"] is False


def test_semantic_interpreter_receives_catalog_and_preserves_goal():
    import json

    from algofactory.llm.providers import Provider
    from algofactory.requirement_understanding import understand

    class SemanticFixture(Provider):
        mode = "mock"

        def _raw(self, request, schema):
            assert "lost_or_stolen_card" in request.source["allowed_intents"]
            if request.operation == "review_requirement":
                return json.dumps({"verdict": "approve", "issues": []})
            return json.dumps(
                {
                    "task": "banking77",
                    "summary": "识别银行卡丢失，优先减少漏判，同时报告误报",
                    "configuration": {
                        "goal": "one_vs_rest",
                        "intents": ["lost_or_stolen_card"],
                        "objective": "recall",
                    },
                    "assessments": [
                        {
                            "part_id": p["id"],
                            "disposition": "supported",
                            "explanation": "受支持的单个意图需求",
                            "fields": ["goal", "intents", "objective"],
                        }
                        for p in request.source["parts"]
                    ],
                }
            )

    provider = SemanticFixture(max_calls=2, max_retries=0)
    review = understand(
        "我想识别英文银行咨询中银行卡丢失或被盗的问题，优先减少漏判。", [], provider
    )
    assert provider.calls == 2 and not review.problems()
    config = interpret_requirement(review.execution_request()).experiment
    assert config.goal == "one_vs_rest" and config.objective == "recall"
