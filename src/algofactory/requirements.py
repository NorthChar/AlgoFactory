"""Conservative, fully covered requirement clauses for the supported text task.

This is a local controlled-language parser, not a general LLM interpreter.
Every nonempty clause must match completely; unknown text never falls back.
"""

import re
from dataclasses import dataclass

from pydantic import ValidationError

from algofactory.experiments import ExperimentConfig
from algofactory.tasks import BANKING77

EXAMPLE_REQUEST = (
    "开发英文银行咨询分类算法，输出77类意图及概率。\n"
    "只使用逻辑回归；仅使用单词特征；词表上限10000；逻辑回归C=1。"
)

TASK_CLAUSES = {
    "开发英文银行咨询分类算法",
    "生成英文银行咨询分类器",
    "将英文银行咨询分类",
    "基于BANKING77的英文客服文本生成并验证意图分类算法",
    "输出77类意图及概率",
    "输出77类已知意图及概率",
    "输出预测类别及概率",
}
RULES = [
    (r"(?:只使用|使用|只用)(?:逻辑回归|LogisticRegression)", "algorithms", ["text_logistic"]),
    (r"(?:只使用|使用|只用)(?:朴素贝叶斯|MultinomialNB)", "algorithms", ["text_nb"]),
    (r"比较逻辑回归和朴素贝叶斯", "algorithms", ["text_logistic", "text_nb"]),
    (r"(?:仅使用|只使用|仅用|只用|仅)单词特征", "ngram_max", 1),
    (r"使用单词和相邻双词特征", "ngram_max", 2),
]
NUMERIC = [
    (r"词表上限(?:为|=)?(\d+)", "max_features", int, {10000, 30000}),
    (r"逻辑回归C(?:为|=)(\d+(?:\.\d+)?)", "logistic_c", float, {1.0, 4.0}),
    (r"朴素贝叶斯(?:alpha|平滑系数)(?:为|=)(\d+(?:\.\d+)?)", "nb_alpha", float, {0.1, 0.5}),
]
LABELS = {
    "goal": "开发目标",
    "intents": "选定的业务意图",
    "objective": "方案选优目标",
    "algorithms": "候选算法",
    "ngram_max": "文本特征",
    "max_features": "词表上限",
    "logistic_c": "逻辑回归 C",
    "nb_alpha": "朴素贝叶斯平滑系数",
}


@dataclass
class RequirementResult:
    experiment: ExperimentConfig | None
    explicit: dict
    issues: list[str]


def interpret_requirement(request: str) -> RequirementResult:
    explicit, issues = {}, []
    if not request.strip() or len(request) > 2000:
        return RequirementResult(None, {}, ["请填写不超过 2000 字的开发需求。"])
    clauses = [re.sub(r"\s+", "", p) for p in re.split(r"[，,；;。\n]+", request)]
    task_seen = False
    full_output = False
    for clause in filter(None, clauses):
        if clause in TASK_CLAUSES:
            full_output |= "77类" in clause
            task_seen |= clause in TASK_CLAUSES - {
                "输出77类意图及概率",
                "输出77类已知意图及概率",
                "输出预测类别及概率",
            }
            continue
        match = None
        selected = re.fullmatch(r"(只区分这些意图|识别单个意图)[:：](.+)", clause)
        if selected:
            names = sorted(selected[2].split("、"))
            values = {
                "goal": "subset" if selected[1] == "只区分这些意图" else "one_vs_rest",
                "intents": names,
            }
            for name, value in values.items():
                if name in explicit and explicit[name] != value:
                    issues.append("要求冲突：选定的任务或意图不一致。")
                else:
                    explicit[name] = value
            continue
        if clause in {"优先减少漏判", "兼顾各类效果"}:
            value = "recall" if clause == "优先减少漏判" else "macro_f1"
            if "objective" in explicit and explicit["objective"] != value:
                issues.append("要求冲突：选优目标不一致。")
            explicit["objective"] = value
            continue
        for pattern, name, value in RULES:
            if re.fullmatch(pattern, clause, re.IGNORECASE):
                match = (name, value)
                break
        if match is None:
            for pattern, name, convert, allowed in NUMERIC:
                found = re.fullmatch(pattern, clause, re.IGNORECASE)
                if found:
                    value = convert(found[1])
                    if value not in allowed:
                        issues.append(
                            f"超出支持范围：{clause}；{LABELS[name]} 可选 {sorted(allowed)}。"
                        )
                    else:
                        match = (name, value)
                    break
            else:
                issues.append(
                    f"无法落实此要求：{clause}。请改写为支持的表达，或移除此要求后重新检查。"
                )
        if match:
            name, value = match
            if name in explicit and explicit[name] != value:
                issues.append(f"要求冲突：{LABELS[name]} 被指定为不同值，请保留一种。")
            else:
                explicit[name] = value
    if not task_seen:
        issues.append(
            "请明确任务：开发英文银行咨询分类算法。可选择已有意图的子集或单个意图识别；不支持其他业务、中文、自有数据或新增标签。"
        )
    if full_output and explicit.get("goal", "full") != "full":
        issues.append("77 类输出与所选任务冲突，请改为输出预测类别及概率。")
    try:
        config = ExperimentConfig(**explicit)
    except ValidationError:
        issues.append(
            "任务配置无效：请使用已有意图；子集选 2–76 类，单个意图识别选 1 类；优先减少漏判仅适用于单个意图识别。"
        )
        return RequirementResult(None, explicit, issues)
    if "logistic_c" in explicit and "text_logistic" not in config.algorithms:
        issues.append("指定了逻辑回归 C，但没有选择逻辑回归。")
    if "nb_alpha" in explicit and "text_nb" not in config.algorithms:
        issues.append("指定了朴素贝叶斯参数，但没有选择朴素贝叶斯。")
    return RequirementResult(None if issues else config, explicit, issues)


def validate_bound_request(request, experiment):
    # Existing canonical CLI experiments remain compatible with explicit controls.
    if request in {"", BANKING77.request} and experiment.goal == "full":
        return
    result = interpret_requirement(request)
    if result.issues:
        raise ValueError("unsupported_requirement: " + " / ".join(result.issues))
    if result.experiment != experiment:
        raise ValueError("requirement_configuration_mismatch")
