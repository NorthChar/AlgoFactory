"""Replay measured Phase 3 evidence; scoped memory must not leak test outcomes."""

import copy
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from algofactory.experience_reuse import retrieve_repairs, synthesize_repair
from algofactory.knowledge.graph import export_graphml, load_graphml
from algofactory.knowledge.store import KnowledgeStore
from algofactory.schemas.contracts import ExperienceRecord
from algofactory.schemas.knowledge import KnowledgeBatch
from algofactory.tasks import BANKING77, CHURN
from algofactory.workflow_models import WorkflowFailure

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "examples/api-phase3"
CHAIN = EVIDENCE / "comparison/candidates/text_logistic"


@pytest.fixture
def memory(tmp_path):
    db = tmp_path / "knowledge.sqlite"
    shutil.copyfile(EVIDENCE / "knowledge.sqlite", db)
    with KnowledgeStore(db) as store:
        learned = synthesize_repair(
            store, CHAIN / "attempt-0", CHAIN / "attempt-1", "text_logistic"
        )
    return db, learned


def query(store, **changes):
    manifest = json.loads((CHAIN / "attempt-1/data-manifest.json").read_text())
    protocol = json.loads((CHAIN / "attempt-1/protocol.json").read_text())
    args = dict(
        profile=BANKING77,
        algorithm="text_logistic",
        manifest=manifest,
        protocol=protocol,
        category="worker_ValueError",
    )
    args.update(changes)
    return retrieve_repairs(store, **args)


def test_measured_synthesis_idempotent_and_graph_reopen(memory, tmp_path):
    db, learned = memory
    record = learned["experience"]["record"]
    assert record["verification_status"] == "verified"
    assert (
        record["repair_evidence"]["failed_code_hash"]
        != record["repair_evidence"]["repaired_code_hash"]
    )
    assert learned["inserted"] == {"sources": 1, "entities": 1, "relations": 2}
    with KnowledgeStore(db) as store:
        again = synthesize_repair(store, CHAIN / "attempt-0", CHAIN / "attempt-1", "text_logistic")
        assert all(v == 0 for v in again["inserted"].values())
        result = query(store)
        assert result["matches"][0]["experience_id"] == learned["experience"]["id"]
        assert "test_metrics" not in json.dumps(result)
        assert "0.878695" not in json.dumps(result)
        batch = KnowledgeBatch.model_validate(store.snapshot())
        export_graphml(batch, tmp_path / "graph.graphml")
        restored = load_graphml(tmp_path / "graph.graphml")
        assert {e.id: e for e in batch.entities} == {e.id: e for e in restored.entities}
        assert {e.id: e for e in batch.relations} == {e.id: e for e in restored.relations}


@pytest.mark.parametrize(
    "changes",
    [
        {"profile": CHURN},
        {"algorithm": "text_nb"},
        {"category": "interface_missing_predict_proba"},
        {"allowed_ids": set()},
        {"protocol": {"config_hash": "0" * 64}},
    ],
)
def test_incompatible_or_unavailable_experience_is_excluded(memory, changes):
    with KnowledgeStore(memory[0]) as store:
        result = query(store, **changes)
    assert not result["matches"] and result["excluded"][0]["reason"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("failed_code_hash", "0" * 64),
        ("repaired_code_hash", "0" * 64),
        ("failure_category", "made_up_failure"),
        ("rule", "unclassified"),
    ],
)
def test_verified_record_requires_matching_measured_proof(memory, field, value):
    with KnowledgeStore(memory[0]) as store:
        snapshot = store.snapshot()
    experience = next(e for e in snapshot["entities"] if e["type"] == "Experience")
    experience["record"]["repair_evidence"][field] = value
    with pytest.raises(ValidationError):
        KnowledgeBatch.model_validate(snapshot)


def test_legacy_and_proposed_records_are_not_auto_consumed(memory):
    db, learned = memory
    legacy = ExperienceRecord.model_validate(
        {"experience_id": "legacy", "condition": "old", "action": "old", "outcome": "old"}
    )
    assert "repair_evidence" not in legacy.model_dump()
    with KnowledgeStore(db) as store:
        snapshot = store.snapshot()
        entity = next(e for e in snapshot["entities"] if e["type"] == "Experience")
        entity["record"]["verification_status"] = "proposed"
        # Direct SQL only constructs a negative retrieval fixture; production store is immutable.
        store.connection.execute(
            "UPDATE entities SET payload=? WHERE id=?", (json.dumps(entity), entity["id"])
        )
        store.connection.commit()
        assert query(store)["matches"] == []


@pytest.mark.parametrize("tamper", ["code", "artifact", "test_access", "status"])
def test_changed_evidence_never_becomes_verified(tmp_path, tamper):
    db = tmp_path / "knowledge.sqlite"
    shutil.copyfile(EVIDENCE / "knowledge.sqlite", db)
    repaired = tmp_path / "repaired"
    shutil.copytree(CHAIN / "attempt-1", repaired)
    if tamper == "code":
        (repaired / "candidate.py").write_text("pass")
    elif tamper == "artifact":
        (repaired / "task.json").write_text("{}")
    elif tamper == "test_access":
        (repaired / "test-access.json").write_text("{}")
    else:
        report = json.loads((repaired / "report.json").read_text())
        report["status"] = "failed"
        (repaired / "report.json").write_text(json.dumps(report))
    with KnowledgeStore(db) as store:
        with pytest.raises(WorkflowFailure):
            synthesize_repair(store, CHAIN / "attempt-0", repaired, "text_logistic")
        assert store.search(entity_type="Experience") == []


def test_nonmatching_scope_cannot_be_marked_verified(memory):
    with KnowledgeStore(memory[0]) as store:
        snapshot = store.snapshot()
    for changes in (
        {"data_fingerprint": "0" * 64},
        {"algorithm": "text_nb"},
        {"text_features": ["other"]},
    ):
        altered = copy.deepcopy(snapshot)
        entity = next(e for e in altered["entities"] if e["type"] == "Experience")
        entity["record"]["repair_evidence"]["scope"].update(changes)
        with pytest.raises(ValidationError):
            KnowledgeBatch.model_validate(altered)


def test_failed_trials_do_not_become_zero_measured_scores(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from verify_phase4 import metrics_by_arm

    result = metrics_by_arm(
        [
            {
                "enabled": True,
                "status": "failed",
                "repair_calls": 0,
                "new_provider_calls": 1,
                "known_input_tokens": 0,
                "known_output_tokens": 0,
                "macro_f1": None,
            }
        ]
    )
    assert result["on"]["validated"] == 0
    assert result["on"]["mean_validation_macro_f1"] is None
    assert result["off"]["mean_validation_macro_f1"] is None
