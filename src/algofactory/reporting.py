"""Human-readable and machine-readable reports, including explicit failure evidence."""

from pathlib import Path

from algofactory.datasets import write_json


def save_report(directory: Path, report: dict):
    write_json(directory / "report.json", report)
    result = report.get("validation") or {}
    lines = [
        "# AlgoFactory 运行报告",
        "",
        f"- 流程：{report['workflow_id']}",
        f"- 状态：{report['status']}",
        f"- 任务：{report.get('task_profile', '尚未识别')}",
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
        else ("f1", "roc_auc", "precision", "recall")
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
            else "训练/验证/测试按 60/20/20 分层划分；预处理只在训练数据拟合。门槛在独立测试之前冻结。"
        ),
        "验证通过后锁定代码与配置，独立测试只评估一次；测试失败不触发重新调参或修复。",
        "",
        "完整输入散列、状态轨迹、Provider 调用和容器证据见同目录 JSON 文件。",
        "",
    ]
    (directory / "report.md").write_text("\n".join(lines), encoding="utf-8")
