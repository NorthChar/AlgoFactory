"""Phase 2 boundary contracts; the host owns labels, thresholds and final decisions."""

from typing import Annotated, Literal

from pydantic import Field

from algofactory.schemas.contracts import Contract, Identifier, Text


class TaskIntent(Contract):
    task_type: Literal["binary_classification"]
    target: Literal["churn"]
    numeric_features: list[Text]
    categorical_features: list[Text]


class GeneratedCode(Contract):
    interface: Literal["build_pipeline"]
    code: Annotated[str, Field(min_length=1, max_length=32768)]
    plan_id: Identifier


class WorkerResult(Contract):
    status: Literal["ok", "failed"]
    error_category: Text | None = None
    row_ids: list[int] = Field(default_factory=list)
    predictions: list[int] = Field(default_factory=list)
    probabilities: list[float] = Field(default_factory=list)
    repeat_predictions: list[int] = Field(default_factory=list)
    repeat_probabilities: list[float] = Field(default_factory=list)
    interface_checked: bool = False
    missing_column_rejected: bool = False
    invalid_numeric_rejected: bool = False
    unseen_category_handled: bool = False
    training_rows: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0.0, ge=0)
    peak_memory_mib: float = Field(default=0.0, ge=0)


class WorkflowFailure(RuntimeError):
    def __init__(self, category: str):
        self.category = category
        super().__init__(category)
