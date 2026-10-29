"""Knowledge graph schema, including exact source spans and typed edge endpoints."""

import hashlib
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from .contracts import (
    Contract,
    Digest,
    ExperienceRecord,
    Identifier,
    NonemptyTexts,
    TaskConstraints,
    TaskType,
    Text,
    ValidationResult,
)


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class SourceDocument(Contract):
    id: Identifier
    title: Text
    content: Text
    sha256: Digest

    @classmethod
    def from_text(cls, title: str, content: str):
        digest = content_hash(content)
        return cls(id=f"source:{digest}", title=title, content=content, sha256=digest)

    @model_validator(mode="after")
    def check_digest(self):
        if self.sha256 != content_hash(self.content) or self.id != f"source:{self.sha256}":
            raise ValueError("Source ID and hash must match UTF-8 content")
        return self


class SourceSpan(Contract):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: Text

    @model_validator(mode="after")
    def check_range(self):
        if self.end <= self.start:
            raise ValueError("Source span must be a nonempty half-open character interval")
        return self


class Provenance(Contract):
    id: Identifier
    source_id: Identifier
    source_span: SourceSpan


class Applicability(Contract):
    task_types: Annotated[list[TaskType], Field(min_length=1)]
    data_kind: Literal["tabular", "text"] = "tabular"
    requirements: NonemptyTexts


class TaskEntity(Provenance):
    type: Literal["Task"] = "Task"
    name: Text
    task_type: TaskType
    constraints: TaskConstraints


class CapabilityEntity(Provenance):
    type: Literal["Capability"] = "Capability"
    name: Text
    description: Text
    inputs: NonemptyTexts
    outputs: NonemptyTexts
    conditions: Applicability
    metrics: NonemptyTexts


class AlgorithmEntity(Provenance):
    type: Literal["Algorithm"] = "Algorithm"
    name: Text
    family: Text
    applicability: Applicability


class ImplementationEntity(Provenance):
    type: Literal["Implementation"] = "Implementation"
    name: Text
    version: int = Field(ge=1)
    code_hash: Digest
    parent_id: Identifier | None = None


class DatasetEntity(Provenance):
    type: Literal["Dataset"] = "Dataset"
    name: Text
    field_schema: dict[Text, Text]
    fingerprint: Digest
    split_id: Identifier


class ValidationRunEntity(Provenance):
    type: Literal["ValidationRun"] = "ValidationRun"
    name: Text
    result: ValidationResult


class FailureCaseEntity(Provenance):
    type: Literal["FailureCase"] = "FailureCase"
    name: Text
    category: Text
    root_cause: Text


class ExperienceEntity(Provenance):
    type: Literal["Experience"] = "Experience"
    name: Text
    record: ExperienceRecord


class DependencyEntity(Provenance):
    type: Literal["Dependency"] = "Dependency"
    name: Text
    package: Text
    version_constraint: Text


Entity = Annotated[
    TaskEntity
    | CapabilityEntity
    | AlgorithmEntity
    | ImplementationEntity
    | DatasetEntity
    | ValidationRunEntity
    | FailureCaseEntity
    | ExperienceEntity
    | DependencyEntity,
    Field(discriminator="type"),
]
ENTITY_ADAPTER = TypeAdapter(Entity)

RelationType = Literal[
    "REQUIRES",
    "IMPLEMENTS",
    "APPLICABLE_TO",
    "USES",
    "DEPENDS_ON",
    "DERIVED_FROM",
    "EVALUATES",
    "USES_DATASET",
    "REPORTS",
]
RELATION_ENDPOINTS = {
    "REQUIRES": {("Task", "Capability")},
    "IMPLEMENTS": {("Algorithm", "Capability")},
    "APPLICABLE_TO": {("Algorithm", "Task")},
    "USES": {("Implementation", "Algorithm")},
    "DEPENDS_ON": {("Implementation", "Dependency")},
    "DERIVED_FROM": {("Implementation", "Implementation"), ("Experience", "ValidationRun")},
    "EVALUATES": {("ValidationRun", "Implementation")},
    "USES_DATASET": {("ValidationRun", "Dataset")},
    "REPORTS": {("ValidationRun", "FailureCase")},
}


class Relation(Provenance):
    type: RelationType
    head_id: Identifier
    tail_id: Identifier


class Extraction(Contract):
    """Provider output; the caller owns the source document, not the model."""

    source_id: Identifier
    entities: Annotated[list[Entity], Field(min_length=1)]
    relations: list[Relation]


class KnowledgeBatch(Contract):
    sources: Annotated[list[SourceDocument], Field(min_length=1)]
    entities: Annotated[list[Entity], Field(min_length=1)]
    relations: list[Relation]

    @model_validator(mode="after")
    def check_graph(self):
        sources = {source.id: source for source in self.sources}
        entities = {entity.id: entity for entity in self.entities}
        objects = [*self.entities, *self.relations]
        ids = [obj.id for obj in objects]
        if len(sources) != len(self.sources) or len(ids) != len(set(ids)):
            raise ValueError("Source, entity and relation IDs must be unique")
        for obj in objects:
            source = sources.get(obj.source_id)
            if source is None:
                raise ValueError("Unknown source reference")
            if not obj.id.startswith(f"{source.id}:"):
                raise ValueError("Knowledge IDs must be namespaced by source ID")
            span = obj.source_span
            if source.content[span.start : span.end] != span.quote or span.end > len(
                source.content
            ):
                raise ValueError("Source span does not match the archived text")
        edge_set = set()
        for edge in self.relations:
            head, tail = entities.get(edge.head_id), entities.get(edge.tail_id)
            if head is None or tail is None:
                raise ValueError("Relation references an unknown entity")
            if (head.type, tail.type) not in RELATION_ENDPOINTS[edge.type]:
                raise ValueError("Relation type is incompatible with endpoint types")
            if edge.head_id == edge.tail_id:
                raise ValueError("Self-relations are not allowed")
            triple = (edge.head_id, edge.type, edge.tail_id)
            if triple in edge_set:
                raise ValueError("Duplicate relation")
            if edge.type == "DERIVED_FROM":
                parent = (
                    head.parent_id
                    if isinstance(head, ImplementationEntity)
                    else head.record.source_run_id
                )
                if parent != tail.id:
                    raise ValueError("DERIVED_FROM edge disagrees with the parent/run reference")
            if edge.type == "EVALUATES" and head.result.implementation_id != tail.id:
                raise ValueError("EVALUATES edge disagrees with the validation result")
            if edge.type == "USES_DATASET" and head.result.split_id != tail.split_id:
                raise ValueError("Validation and dataset must use the same split")
            edge_set.add(triple)
        parents = {e.id: e.parent_id for e in self.entities if isinstance(e, ImplementationEntity)}
        for identifier in parents:
            seen = set()
            cursor = identifier
            while cursor is not None:
                if cursor in seen:
                    raise ValueError("Implementation lineage must be acyclic")
                seen.add(cursor)
                cursor = parents.get(cursor)
        for entity in self.entities:
            if isinstance(entity, ImplementationEntity) and entity.parent_id:
                if (entity.id, "DERIVED_FROM", entity.parent_id) not in edge_set:
                    raise ValueError("Implementation parent requires a DERIVED_FROM edge")
            if isinstance(entity, ValidationRunEntity):
                if entity.result.run_id != entity.id:
                    raise ValueError("Validation run ID must match its result")
                target = entities.get(entity.result.implementation_id)
                if not isinstance(target, ImplementationEntity):
                    raise ValueError("Validation must reference an implementation")
                if target.code_hash != entity.result.code_hash:
                    raise ValueError("Validation code hash does not match implementation")
                if (entity.id, "EVALUATES", target.id) not in edge_set:
                    raise ValueError("Validation requires an EVALUATES edge")
            if isinstance(entity, ExperienceEntity):
                record = entity.record
                if record.experience_id != entity.id:
                    raise ValueError("Experience ID must match its record")
                if record.source_run_id:
                    run = entities.get(record.source_run_id)
                    if not isinstance(run, ValidationRunEntity):
                        raise ValueError("Experience references an unknown validation run")
                    if (entity.id, "DERIVED_FROM", run.id) not in edge_set:
                        raise ValueError("Experience requires a DERIVED_FROM edge")
                    if record.verification_status == "verified" and run.result.status != "passed":
                        raise ValueError("Verified experience requires a passed retest")
        return self
