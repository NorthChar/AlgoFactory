"""Validated interfaces; validation and execution remain independent of the LLM."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Identifier = Annotated[str, Field(min_length=1, max_length=240, pattern=r"^[a-zA-Z0-9_.:-]+$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
TaskType = Literal["binary_classification", "regression"]
MetricName = Literal["f1", "roc_auc", "precision", "recall", "mae", "rmse"]
NonemptyTexts = Annotated[list[Text], Field(min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, validate_assignment=True
    )
    schema_version: Literal[1] = 1


class ExecutionBudget(Contract):
    backend: Literal["docker"] = "docker"
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    cpus: int = Field(default=2, ge=1)
    memory_mib: int = Field(default=4096, ge=128)
    network: Literal[False] = False
    fail_closed: Literal[True] = True


class TaskConstraints(Contract):
    candidate_limit: int = Field(default=2, ge=1, le=10)
    max_repairs_per_candidate: int = Field(default=2, ge=0, le=10)
    allowed_algorithms: list[Identifier] = Field(default_factory=list)
    execution: ExecutionBudget = Field(default_factory=ExecutionBudget)


class FeatureSpec(Contract):
    name: Text
    dtype: Literal["numeric", "categorical", "boolean"]
    nullable: bool = False


class MetricRule(Contract):
    name: MetricName
    direction: Literal["maximize", "minimize"]
    threshold: float | None = None

    @model_validator(mode="after")
    def check_metric(self):
        regression = self.name in {"mae", "rmse"}
        if self.direction != ("minimize" if regression else "maximize"):
            raise ValueError("Metric direction does not match its definition")
        if self.threshold is not None:
            if self.threshold < 0 or (not regression and self.threshold > 1):
                raise ValueError("Invalid metric threshold")
        return self


class TaskSpec(Contract):
    task_id: Identifier
    description: Text
    task_type: TaskType
    target: Text
    feature_schema: Annotated[list[FeatureSpec], Field(min_length=1)]
    data_fingerprint: Digest
    split_id: Identifier
    metrics: Annotated[list[MetricRule], Field(min_length=1)]
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)
    seed: int = Field(default=42, ge=0)

    @model_validator(mode="after")
    def check_fields(self):
        names = [f.name for f in self.feature_schema]
        if len(names) != len(set(names)) or self.target in names:
            raise ValueError("Features must be unique and must exclude the target")
        metrics = [m.name for m in self.metrics]
        allowed = (
            {"mae", "rmse"}
            if self.task_type == "regression"
            else {"f1", "roc_auc", "precision", "recall"}
        )
        if len(set(metrics)) != len(metrics) or not set(metrics) <= allowed:
            raise ValueError("Metrics must be unique and compatible with task_type")
        return self


class AlgorithmPlan(Contract):
    plan_id: Identifier
    task_id: Identifier
    algorithm_id: Identifier
    preprocessing: list[Text]
    dependencies: NonemptyTexts
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]


class Candidate(Contract):
    implementation_id: Identifier
    parent_id: Identifier | None = None
    code_hash: Digest
    plan_id: Identifier
    attempt: int = Field(ge=0)

    @model_validator(mode="after")
    def check_parent(self):
        if self.parent_id == self.implementation_id:
            raise ValueError("A candidate cannot be its own parent")
        if (self.attempt == 0) != (self.parent_id is None):
            raise ValueError("Initial candidates have no parent; revisions require a parent")
        return self


class DimensionResult(Contract):
    status: Literal["passed", "failed", "not_run"]
    details: Text


class ResourceUsage(Contract):
    elapsed_seconds: float = Field(ge=0)
    peak_memory_mib: float | None = Field(default=None, ge=0)


class ValidationResult(Contract):
    run_id: Identifier
    implementation_id: Identifier
    code_hash: Digest
    config_hash: Digest
    split_id: Identifier
    status: Literal["passed", "failed", "stopped"]
    functional: DimensionResult
    metrics: DimensionResult
    stability: DimensionResult
    interface: DimensionResult
    validation_metrics: dict[MetricName, float]
    test_metrics: dict[MetricName, float] = Field(default_factory=dict)
    final_test_evaluated: bool = False
    resources: ResourceUsage
    report_paths: NonemptyTexts
    error_category: Text | None = None

    @model_validator(mode="after")
    def check_status(self):
        checks = [self.functional, self.metrics, self.stability, self.interface]
        if self.status == "passed" and any(c.status != "passed" for c in checks):
            raise ValueError("All four dimensions must pass before accepting a result")
        if self.status == "passed" and not self.validation_metrics:
            raise ValueError("Passed validation requires nonempty computed metrics")
        for measured in (self.validation_metrics, self.test_metrics):
            for name, value in measured.items():
                if value < 0 or (name not in {"mae", "rmse"} and value > 1):
                    raise ValueError("Computed metric is outside its valid range")
        if bool(self.test_metrics) != self.final_test_evaluated:
            raise ValueError("Test metrics require explicit final-test evaluation")
        if self.status != "passed" and self.error_category is None:
            raise ValueError("Unsuccessful validation requires an error category")
        return self


class AgentDecision(Contract):
    decision_id: Identifier
    run_id: Identifier
    role: Literal["knowledge", "builder", "review"]
    action: Literal["GENERATE", "REPAIR", "OPTIMIZE", "SWITCH", "ACCEPT", "STOP"]
    reason: Text
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]
    budget_remaining: int = Field(ge=0)


class ExperienceRecord(Contract):
    experience_id: Identifier
    condition: Text
    action: Text
    outcome: Text
    source_run_id: Identifier | None = None
    verification_status: Literal["proposed", "verified"] = "proposed"

    @model_validator(mode="after")
    def check_evidence(self):
        if self.verification_status == "verified" and self.source_run_id is None:
            raise ValueError("Verified experience requires a validation run")
        return self
