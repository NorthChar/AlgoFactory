"""Persist measured runs with graph provenance; scoped synthesis lives in experience_reuse."""

from algofactory.knowledge.store import KnowledgeStore, canonical
from algofactory.schemas.contracts import ValidationResult
from algofactory.schemas.knowledge import (
    DatasetEntity,
    FailureCaseEntity,
    ImplementationEntity,
    KnowledgeBatch,
    Relation,
    SourceDocument,
    SourceSpan,
    TaskEntity,
    ValidationRunEntity,
)


def persist_execution(store: KnowledgeStore, report: dict, manifest: dict, task, plan) -> dict:
    # Evidence is sealed before assigning graph IDs, avoiding self-referential content hashes.
    evidence = {
        "workflow_id": report["workflow_id"],
        "status": report["status"],
        "code_hash": report["code_hash"],
        "task": task.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json"),
        "validation": report["validation"],
        "execution_evidence": report.get("execution_evidence", []),
        "candidate": report.get("candidate"),
        "evaluation_scope": report.get("evaluation_scope", "validation_and_final_test"),
        "search_summary": report.get("search_summary"),
        "experience_usage": report.get("experience_usage"),
    }
    source = SourceDocument.from_text(report["workflow_id"] + ".json", canonical(evidence))
    span = SourceSpan(start=0, end=len(source.content), quote=source.content)

    def provenance(local):
        return {"id": source.id + ":" + local, "source_id": source.id, "source_span": span}

    implementation = ImplementationEntity(
        **provenance("implementation"),
        name="Generated candidate",
        version=report.get("candidate", {}).get("attempt", 0) + 1,
        parent_id=report.get("candidate", {}).get("parent_id"),
        code_hash=report["code_hash"],
    )
    reuse = report.get("selected_implementation_id")
    if reuse:
        implementation = ImplementationEntity.model_validate(store.evidence(reuse)["record"])
        if implementation.code_hash != report["code_hash"]:
            raise ValueError("Selected implementation hash mismatch")
    dataset = DatasetEntity(
        **provenance("dataset"),
        name="BANKING77"
        if manifest.get("task_profile") == "banking77"
        else "Synthetic churn dataset",
        field_schema={**{f.name: f.dtype for f in task.feature_schema}, task.target: "class_label"},
        fingerprint=manifest["data_fingerprint"],
        split_id=manifest["split_id"],
    )
    result = ValidationResult.model_validate(
        report["validation"]
        | {"run_id": source.id + ":validation", "implementation_id": implementation.id}
    )
    run = ValidationRunEntity(
        **provenance("validation"), name="Measured validation run", result=result
    )
    task_entity = TaskEntity(
        **provenance("task"),
        name=task.description,
        task_type=task.task_type,
        constraints=task.constraints,
    )
    existing = KnowledgeBatch.model_validate(store.snapshot())
    new_entities = [dataset, run, task_entity] + ([] if reuse else [implementation])
    links = [
        ("EVALUATES", run.id, implementation.id),
        ("USES_DATASET", run.id, dataset.id),
    ]
    if not reuse:
        links.append(("USES", implementation.id, plan.algorithm_id))
        if implementation.parent_id:
            links.append(("DERIVED_FROM", implementation.id, implementation.parent_id))
    for entity in existing.entities:
        if not reuse and entity.type == "Dependency" and entity.package == "scikit-learn":
            links.append(("DEPENDS_ON", implementation.id, entity.id))
        if entity.type == "Capability" and entity.id in plan.evidence_ids:
            links.append(("REQUIRES", task_entity.id, entity.id))
    if result.status != "passed":
        failure = FailureCaseEntity(
            **provenance("failure"),
            name="Candidate validation failure",
            category=result.error_category,
            root_cause=report["error_category"],
        )
        new_entities.append(failure)
        links.append(("REPORTS", run.id, failure.id))
    relations = [
        Relation(**provenance(f"relation:{i}"), type=kind, head_id=head, tail_id=tail)
        for i, (kind, head, tail) in enumerate(links)
    ]
    identifiers = {
        "implementation_id": implementation.id,
        "validation_run_id": run.id,
        "dataset_id": dataset.id,
        "task_id": task_entity.id,
    }
    record = {
        "workflow_id": report["workflow_id"],
        "status": report["status"],
        "knowledge_ids": identifiers,
        "validation": result.model_dump(mode="json"),
        "report_paths": result.report_paths,
        "search_summary": report.get("search_summary"),
        "evaluation_scope": report.get("evaluation_scope", "validation_and_final_test"),
        "experience_usage": report.get("experience_usage"),
    }
    store.put_batch(
        KnowledgeBatch(
            sources=[*existing.sources, source],
            entities=[*existing.entities, *new_entities],
            relations=[*existing.relations, *relations],
        ),
        workflow_record=record,
    )
    return {"validation": result.model_dump(mode="json"), "knowledge_ids": identifiers}
