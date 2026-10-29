"""Host-owned task profiles; candidates cannot choose their fields or evaluation rules."""

from dataclasses import dataclass

from algofactory.workflow_models import WorkflowFailure


@dataclass(frozen=True)
class TaskProfile:
    name: str
    task_type: str
    data_kind: str
    target: str
    numeric: tuple[str, ...]
    categorical: tuple[str, ...]
    text: tuple[str, ...]
    request: str
    algorithm: str
    template: str
    document: str

    @property
    def features(self):
        return [*self.numeric, *self.categorical, *self.text]

    def intent(self):
        return {
            "task_type": self.task_type,
            "target": self.target,
            "numeric_features": list(self.numeric),
            "categorical_features": list(self.categorical),
            "text_features": list(self.text),
        }


CHURN = TaskProfile(
    "churn",
    "binary_classification",
    "tabular",
    "churn",
    ("tenure_months", "monthly_fee", "support_tickets"),
    ("contract_type",),
    (),
    "根据客户特征预测客户是否流失，输出流失类别和概率。",
    "Logistic Regression",
    "logistic.txt",
    "customer_churn.txt",
)
BANKING77 = TaskProfile(
    "banking77",
    "multiclass_classification",
    "text",
    "intent",
    (),
    (),
    ("text",),
    "基于 BANKING77 的英文客服文本生成并验证意图分类算法，输出 77 类已知意图及概率。",
    "TF-IDF + Logistic Regression",
    "text_logistic.txt",
    "banking77.txt",
)
PROFILES = {p.name: p for p in (CHURN, BANKING77)}
BANKING77_REUSE_REQUEST = "为另一个调用方复用相同 BANKING77 输入协议，请生成并验证可接收 DataFrame 的 77 类英文客服意图分类组件。"


def profile_for(manifest):
    name = manifest.get("task_profile", "churn")
    if name not in PROFILES:
        raise WorkflowFailure("unsupported_task_profile")
    return PROFILES[name]


def compatible_evidence(entry, profile, source_id):
    record = entry["record"]
    conditions = record.get("conditions", record.get("applicability", {}))
    return (
        record["source_id"] == source_id
        and record["type"] in {"Algorithm", "Capability"}
        and profile.task_type in conditions.get("task_types", [])
        and conditions.get("data_kind") == profile.data_kind
    )
