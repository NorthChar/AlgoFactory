"""Human-readable and machine-readable reports, including explicit failure evidence."""

import json
from pathlib import Path

from algofactory.datasets import write_json


def design_explanation(directory: Path, report: dict):
    """Explain only accepted task/plan facts, with immutable evidence IDs; no new LLM call."""
    try:
        task = json.loads((directory / "task.json").read_text())
        plan = json.loads((directory / "plan.json").read_text())
        evidence = plan["evidence_ids"]
        if plan["algorithm_id"] not in evidence:
            return None
        validation = report.get("validation", {})
        return {
            "text": f"任务要求预测 {task['target']}，类型为 {task['task_type']}。方案依据适用知识选择算法实体 {plan['algorithm_id']}，并要求预处理只在训练集拟合。候选是否通过由独立验证器依据冻结门槛决定，不由模型自行评分。此次运行状态为 {report['status']}。",
            "algorithm_id": plan["algorithm_id"],
            "evidence_ids": evidence,
            "workflow_id": report["workflow_id"],
            "validation_run_id": validation.get("run_id"),
            "selection_basis": "同一协议下按验证集排名选定版本"
            if report.get("selected_algorithm")
            else "预先指定的单候选；不声称是所有算法中最优",
            "final_test_evaluated": validation.get("final_test_evaluated", False),
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_report(directory: Path, report: dict):
    explanation = design_explanation(directory, report)
    if explanation:
        report["design_explanation"] = explanation
    write_json(directory / "report.json", report)
    result = report.get("validation") or {}
    lines = [
        "# AlgoFactory 运行报告",
        "",
        f"- 流程：{report['workflow_id']}",
        f"- 状态：{report['status']}",
        f"- 任务：{report.get('task_profile', '尚未识别')}",
        f"- 评估范围：{report.get('evaluation_scope', 'validation_and_final_test')}",
        f"- LLM 模式：{report['provider_mode']}",
        f"- 代码散列：{report.get('code_hash') or '尚未生成'}",
        f"- 知识库回写：{'已保存' if report.get('persisted') else '未完成'}",
        f"- 错误类别：{report.get('error_category') or '无'}",
        "",
        "Mock 指固定方案与代码响应；模型训练、预测和评分仍由真实程序执行。",
        "",
        "## 四维验证",
        "",
        "| 维度 | 状态 | 说明 |",
        "| --- | --- | --- |",
    ]
    for key, name in (
        ("functional", "功能"),
        ("metrics", "指标"),
        ("stability", "稳定性"),
        ("interface", "接口"),
    ):
        check = result.get(key, {"status": "not_run", "details": "尚未执行"})
        lines.append(f"| {name} | {check['status']} | {check['details']} |")
    lines += [
        "",
        "## 实际指标",
        "",
        "| 指标 | 验证集 | 独立测试集 | 冻结门槛 |",
        "| --- | --- | --- | --- |",
    ]
    thresholds = report.get("thresholds", {})
    for name in (
        ("macro_f1", "accuracy")
        if report.get("task_profile") == "banking77"
        else (
            ("mae", "rmse")
            if report.get("task_profile") == "regression"
            else ("f1", "roc_auc", "precision", "recall")
        )
    ):
        values = [
            result.get("validation_metrics", {}).get(name),
            result.get("test_metrics", {}).get(name),
            thresholds.get(name),
        ]
        cells = [f"{value:.6f}" if value is not None else "未评估" for value in values]
        lines.append("| " + " | ".join([name, *cells]) + " |")
    lines += [
        "",
        (
            "BANKING77 保留官方测试集；训练侧去重后按 80/20 分层划分训练/验证。词表和 IDF 仅在训练集拟合；Macro-F1 为门槛，Accuracy 仅报告。逐类指标及混淆矩阵见 validation-class-details.json / test-class-details.json。"
            if report.get("task_profile") == "banking77"
            else (
                "合成回归按固定种子 60/20/20 随机划分，预处理只在训练集拟合；MAE/RMSE 越低越好，门槛预先固定。"
                if report.get("task_profile") == "regression"
                else "训练/验证/测试按 60/20/20 分层划分；预处理只在训练数据拟合。门槛在独立测试之前冻结。"
            )
        ),
        "验证通过后锁定代码与配置，独立测试只评估一次；测试失败不触发重新调参或修复。",
        "",
        "完整输入散列、状态轨迹、Provider 调用和容器证据见同目录 JSON 文件。",
        "",
    ]
    if report.get("evaluation_scope") in {"validation_only", "comparison_validation_only"}:
        lines += ["本报告仅用于验证集候选比较；validated 不表示最终测试通过。", ""]
    if "attempts" in report:
        lines += [
            "## 候选与版本",
            "",
            "| 候选 | 版本 | 状态 | Macro-F1（验证） | 错误 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for attempt in report["attempts"]:
            value = attempt["validation_metrics"].get("macro_f1")
            score = f"{value:.6f}" if value is not None else "未完成"
            lines.append(
                f"| {attempt['algorithm']} | {attempt['attempt']} | {attempt['status']} | {score} | {attempt['error_category'] or '无'} |"
            )
        lines += [
            "",
            "排名只使用验证集 Macro-F1，其次 Accuracy，再按冻结候选顺序打破平局。只有通过四维检查的版本可入选。",
            "选定候选：" + report.get("selected_algorithm", "无"),
            "故障 fixture：" + (report.get("fault_fixture") or "无"),
            "修复输入、父版本、修改代码和重新验证结果见 candidates/；统一决策见 decisions.json，排名见 ranking.json（若比较完成）。",
            "",
        ]
    if report.get("error_details"):
        lines += [
            "",
            "## 校验诊断",
            "",
            "以下位置按从 0 开始的实体/关系列表索引记录；不包含引用正文。",
            "",
        ]
        for detail in report["error_details"]:
            lines.append(
                f"- {detail['rule']}：{detail.get('object_kind', 'graph')} {detail.get('object_index', '')}"
            )
    uses = [report["experience_usage"]] if report.get("experience_usage") else []
    uses += [a["experience_usage"] for a in report.get("attempts", []) if a.get("experience_usage")]
    if uses:
        lines += [
            "",
            "## 经验复用轨迹",
            "",
            "模型声明采用与代码规则检查分别记录；单次采用不代表普遍收益。",
            "",
        ]
        for use in uses:
            lines.append(
                f"- 经验开关：{use['enabled']}；匹配数：{len(use['matches'])}；输出满足经验规则：{use['observed_rule_satisfied']}"
            )
            for item in use["model_decisions"]:
                lines.append(
                    f"- {item['experience_id']}：{item['decision']}；{item['reason'].replace(chr(10), ' ')}"
                )
    if explanation:
        lines += [
            "",
            "## 设计依据与解释",
            "",
            explanation["text"],
            "",
            explanation["selection_basis"],
            "",
            "知识引用：" + ", ".join(explanation["evidence_ids"]),
            "验证记录：" + (explanation["validation_run_id"] or "尚未产生"),
            "",
        ]
    (directory / "report.md").write_text("\n".join(lines), encoding="utf-8")
