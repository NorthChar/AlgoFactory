import copy
import json
import sqlite3

import pytest
from pydantic import ValidationError

from algofactory.knowledge.extraction import extract_document, ingest_document
from algofactory.knowledge.graph import export_graphml, load_graphml, to_networkx
from algofactory.knowledge.store import KnowledgeConflict, KnowledgeStore
from algofactory.llm.providers import MockProvider, ProviderError
from algofactory.schemas.knowledge import KnowledgeBatch, SourceDocument


def ordered(batch):
    return {
        key: sorted(values, key=lambda item: item["id"])
        for key, values in batch.model_dump(mode="json").items()
        if isinstance(values, list)
    }


def test_document_to_store_reopen_query_and_provenance(source, fixtures, tmp_path):
    db = tmp_path / "knowledge.sqlite"
    with KnowledgeStore(db) as store:
        result = ingest_document(source, MockProvider(fixtures), store)
        assert result["inserted"] == {"sources": 1, "entities": 6, "relations": 7}
        repeat = ingest_document(source, MockProvider(fixtures), store)
        assert repeat["inserted"] == {"sources": 0, "entities": 0, "relations": 0}
    with KnowledgeStore(db) as store:
        matches = store.search(task_type="binary_classification", entity_type="Algorithm")
        assert {m["record"]["name"] for m in matches} == {
            "Logistic Regression",
            "Random Forest",
            "HistGradientBoosting",
        }
        assert store.search(task_type="regression") == []
        assert len(store.search(text="linear nonexistent")) == 0
        assert len(store.search(text="Logistic Regression")) == 1
        for match in matches:
            span = match["source"]["span"]
            assert source.content[span["start"] : span["end"]] == span["quote"]
            assert len(match["relations"]) == 2
            assert match["source"]["sha256"] == source.sha256


@pytest.mark.parametrize(
    "mutation",
    [
        "span",
        "source",
        "dangling",
        "edge_type",
        "duplicate",
        "namespace",
        "unknown_field",
        "source_hash",
    ],
)
def test_invalid_graph_is_rejected(batch, mutation):
    data = batch.model_dump(mode="json")
    if mutation == "span":
        data["entities"][0]["source_span"]["quote"] = "编造的引用"
    elif mutation == "source":
        data["entities"][0]["source_id"] = "unknown"
    elif mutation == "dangling":
        data["relations"][0]["tail_id"] = "unknown"
    elif mutation == "edge_type":
        data["relations"][0]["type"] = "EVALUATES"
    elif mutation == "duplicate":
        data["entities"].append(copy.deepcopy(data["entities"][0]))
    elif mutation == "namespace":
        data["entities"][0]["id"] = "arbitrary:id"
    elif mutation == "unknown_field":
        data["entities"][0]["invented"] = True
    elif mutation == "source_hash":
        data["sources"][0]["content"] += "changed"
    with pytest.raises(ValidationError):
        KnowledgeBatch.model_validate(data)


def test_id_conflict_rolls_back_entire_batch(batch, tmp_path):
    with KnowledgeStore(tmp_path / "db") as store:
        store.put_batch(batch)
        before = store.snapshot()
        conflict = batch.model_copy(deep=True)
        conflict.entities[0].name = "Changed meaning under same ID"
        new = conflict.entities[-1].model_copy(deep=True)
        new.id += ":another"
        conflict.entities.insert(0, new)
        with pytest.raises(KnowledgeConflict):
            store.put_batch(conflict)
        assert store.snapshot() == before
        assert store.connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_nested_mutation_is_revalidated_before_write(batch, tmp_path):
    batch.entities.append(batch.entities[0])
    with KnowledgeStore(tmp_path / "db") as store:
        with pytest.raises(ValidationError):
            store.put_batch(batch)
        assert store.snapshot()["sources"] == []


def test_sqlite_rejects_invalid_endpoint_types(batch, tmp_path):
    with KnowledgeStore(tmp_path / "db") as store:
        store.put_batch(batch)
        task, capability = batch.entities[:2]
        with pytest.raises(sqlite3.IntegrityError), store.connection:
            store.connection.execute(
                "INSERT INTO relations VALUES (?, ?, ?, ?, ?, ?)",
                ("bad", "EVALUATES", task.id, capability.id, task.source_id, "{}"),
            )


def test_graphml_and_json_round_trip_without_loss(batch, tmp_path):
    graph_path = tmp_path / "graph.graphml"
    export_graphml(batch, graph_path)
    assert ordered(load_graphml(graph_path)) == ordered(batch)
    graph = to_networkx(batch)
    assert len(graph) == 6 and graph.number_of_edges() == 7
    with KnowledgeStore(tmp_path / "first.db") as store:
        store.put_batch(batch)
        store.export_json(tmp_path / "snapshot.json")
    restored = KnowledgeBatch.model_validate_json((tmp_path / "snapshot.json").read_bytes())
    with KnowledgeStore(tmp_path / "second.db") as store:
        store.put_batch(restored)
        assert ordered(KnowledgeBatch.model_validate(store.snapshot())) == ordered(batch)


def test_graphml_tampering_rejected(batch, tmp_path):
    path = tmp_path / "graph.graphml"
    export_graphml(batch, path)
    data = path.read_text()
    data = data.replace(">Logistic Regression<", ">Changed name<", 1)
    path.write_text(data)
    with pytest.raises(ValueError, match="metadata"):
        load_graphml(path)


def test_changed_document_never_replays_unrelated_mock(source, fixtures):
    other = SourceDocument.from_text("other.txt", source.content + "\n额外信息")
    with pytest.raises(ProviderError, match="mock_fixture_missing"):
        extract_document(other, MockProvider(fixtures))


def test_invalid_extraction_leaves_database_empty(source, fixtures, tmp_path):
    fixtures[source.sha256]["response"]["entities"][0]["source_span"]["start"] += 1
    with KnowledgeStore(tmp_path / "db") as store:
        with pytest.raises(ProviderError, match="invalid_knowledge_graph"):
            ingest_document(source, MockProvider(fixtures), store)
        assert store.snapshot()["entities"] == []


def test_unrelated_source_and_sql_metacharacters_are_safe(batch, tmp_path):
    data = batch.model_dump(mode="json")
    old = data["sources"][0]
    other = SourceDocument.from_text("same contents with suffix.txt", old["content"] + "\n附注")
    # Simulate a second source with identical local IDs to verify content-scoped IDs.
    encoded = json.dumps(data, ensure_ascii=False).replace(old["id"], other.id)
    second = json.loads(encoded)
    second["sources"] = [other.model_dump(mode="json")]
    with KnowledgeStore(tmp_path / "db") as store:
        store.put_batch(batch)
        store.put_batch(KnowledgeBatch.model_validate(second))
        assert len(store.search(entity_type="Algorithm")) == 6
        assert store.search(text="' OR 1=1 --") == []
        assert store.search(entity_type="' OR 1=1 --") == []


def test_future_database_version_rejected(tmp_path):
    path = tmp_path / "future.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="schema version"):
        KnowledgeStore(path)


def test_write_failure_rolls_back_sources_and_entities(batch, tmp_path):
    with KnowledgeStore(tmp_path / "db") as store:
        store.connection.execute("""CREATE TRIGGER injected_failure BEFORE INSERT ON entities
            WHEN NEW.type = 'Algorithm' BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
        with pytest.raises(sqlite3.IntegrityError):
            store.put_batch(batch)
        assert store.snapshot() == {
            "schema_version": 1,
            "sources": [],
            "entities": [],
            "relations": [],
        }


def history_fixture():
    """Synthetic schema fixture, never exported as a real algorithm validation."""
    from test_contracts import validation_data

    source = SourceDocument.from_text(
        "synthetic-test-only", "Synthetic implementation and validation records for contract tests."
    )

    def provenance(local):
        return {
            "id": source.id + ":" + local,
            "source_id": source.id,
            "source_span": {"start": 0, "end": len(source.content), "quote": source.content},
        }

    implementation = {
        **provenance("impl"),
        "type": "Implementation",
        "name": "fixture",
        "version": 1,
        "code_hash": "a" * 64,
    }
    dataset = {
        **provenance("dataset"),
        "type": "Dataset",
        "name": "fixture data",
        "field_schema": {"x": "numeric"},
        "fingerprint": "c" * 64,
        "split_id": "split:42",
    }
    validation = {**provenance("run"), "type": "ValidationRun", "name": "fixture run"}
    validation["result"] = validation_data() | {
        "run_id": validation["id"],
        "implementation_id": implementation["id"],
    }
    experience = {**provenance("experience"), "type": "Experience", "name": "fixture experience"}
    experience["record"] = {
        "experience_id": experience["id"],
        "condition": "fixture",
        "action": "fixture",
        "outcome": "fixture",
        "source_run_id": validation["id"],
        "verification_status": "verified",
    }
    failure = {
        **provenance("failure"),
        "type": "FailureCase",
        "name": "fixture failure",
        "category": "missing_method",
        "root_cause": "Synthetic historical failure",
    }
    edges = [
        {**provenance("edge:" + kind), "type": kind, "head_id": head["id"], "tail_id": tail["id"]}
        for kind, head, tail in [
            ("EVALUATES", validation, implementation),
            ("USES_DATASET", validation, dataset),
            ("DERIVED_FROM", experience, validation),
        ]
    ]
    return {
        "sources": [source.model_dump(mode="json")],
        "entities": [implementation, dataset, validation, experience, failure],
        "relations": edges,
    }


def test_historical_schema_store_and_export(tmp_path):
    batch = KnowledgeBatch.model_validate(history_fixture())
    with KnowledgeStore(tmp_path / "db") as store:
        store.put_batch(batch)
        matches = store.search(entity_type="Experience")
        assert matches[0]["record"]["record"]["verification_status"] == "verified"
        assert len(matches[0]["relations"]) == 1
    export_graphml(batch, tmp_path / "history.graphml")
    assert ordered(load_graphml(tmp_path / "history.graphml")) == ordered(batch)


@pytest.mark.parametrize(
    "mutation", ["missing_run", "failed_run", "wrong_hash", "wrong_split", "missing_relation"]
)
def test_unbacked_history_is_rejected(mutation):
    data = history_fixture()
    if mutation == "missing_run":
        data["entities"][3]["record"]["source_run_id"] = "missing"
    elif mutation == "failed_run":
        data["entities"][2]["result"].update(status="failed", error_category="fixture")
    elif mutation == "wrong_hash":
        data["entities"][2]["result"]["code_hash"] = "f" * 64
    elif mutation == "wrong_split":
        data["entities"][1]["split_id"] = "split:wrong"
    elif mutation == "missing_relation":
        data["relations"].pop()
    with pytest.raises(ValidationError):
        KnowledgeBatch.model_validate(data)


def test_cyclic_implementation_lineage_rejected():
    data = history_fixture()
    original = data["entities"][0]
    revision = copy.deepcopy(original)
    revision["id"] += ":revision"
    revision["version"] = 2
    revision["parent_id"] = original["id"]
    original["parent_id"] = revision["id"]
    data["entities"].append(revision)
    for i, (head, tail) in enumerate(((original, revision), (revision, original))):
        data["relations"].append(
            {
                "id": original["source_id"] + f":cycle:{i}",
                "source_id": original["source_id"],
                "source_span": original["source_span"],
                "type": "DERIVED_FROM",
                "head_id": head["id"],
                "tail_id": tail["id"],
            }
        )
    with pytest.raises(ValidationError, match="acyclic"):
        KnowledgeBatch.model_validate(data)


@pytest.mark.parametrize(
    "mutation,rule,kind",
    [
        ("span", "knowledge_source_span_mismatch", "entity"),
        ("namespace", "knowledge_id_namespace", "entity"),
        ("dangling", "knowledge_unknown_endpoint", "relation"),
        ("edge_type", "knowledge_endpoint_type", "relation"),
        ("duplicate", "knowledge_duplicate_id", None),
    ],
)
def test_extraction_diagnostics_are_specific_and_redacted(source, fixtures, mutation, rule, kind):
    response = fixtures[source.sha256]["response"]
    if mutation == "span":
        response["entities"][0]["source_span"]["quote"] = "private text must not enter diagnostics"
    elif mutation == "namespace":
        response["entities"][0]["id"] = "private-id"
    elif mutation == "dangling":
        response["relations"][0]["tail_id"] = "private-id"
    elif mutation == "edge_type":
        response["relations"][0]["type"] = "IMPLEMENTS"
    elif mutation == "duplicate":
        response["entities"].append(copy.deepcopy(response["entities"][0]))
    with pytest.raises(ProviderError) as error:
        extract_document(source, MockProvider(fixtures))
    assert error.value.category == "invalid_knowledge_graph"
    details = error.value.diagnostics
    assert details[0]["rule"] == rule
    if kind:
        assert details[0]["object_kind"] == kind and details[0]["object_index"] == 0
    assert "private" not in json.dumps(details)
    assert "quote" not in json.dumps(details)


def test_document_schema_does_not_advertise_historical_entities_or_edges():
    from algofactory.schemas.knowledge import DocumentExtraction

    schema = DocumentExtraction.model_json_schema()
    definitions = schema["$defs"]
    assert definitions["DocumentRelation"]["properties"]["type"]["enum"] == [
        "REQUIRES",
        "IMPLEMENTS",
        "APPLICABLE_TO",
    ]
    assert "DependencyEntity" in definitions
    assert (
        not {
            "ImplementationEntity",
            "ExperienceEntity",
            "ValidationRunEntity",
            "FailureCaseEntity",
            "DatasetEntity",
        }
        & definitions.keys()
    )


def test_algorithm_dependency_is_rejected_not_silently_removed(source, fixtures):
    response = fixtures[source.sha256]["response"]
    response["relations"][0]["type"] = "DEPENDS_ON"
    with pytest.raises(ProviderError, match="invalid_structured_response"):
        extract_document(source, MockProvider(fixtures, max_retries=0))


def test_recorded_live_algorithm_dependency_failure_replays_offline():
    from pathlib import Path

    from algofactory.knowledge.extraction import validate_extraction
    from algofactory.schemas.knowledge import DocumentExtraction, Extraction

    root = Path(__file__).resolve().parents[1] / "tests/fixtures/knowledge-diagnosis"
    source = SourceDocument.model_validate_json((root / "source.json").read_bytes())
    raw = (root / "extraction.json").read_bytes()
    legacy = Extraction.model_validate_json(raw)
    with pytest.raises(ProviderError) as error:
        validate_extraction(source, legacy)
    assert error.value.diagnostics == [
        {"rule": "knowledge_endpoint_type", "object_kind": "relation", "object_index": 3}
    ]
    # The revised output boundary refuses the same edge even before graph validation.
    with pytest.raises(ValidationError):
        DocumentExtraction.model_validate_json(raw)
