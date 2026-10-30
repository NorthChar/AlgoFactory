"""Read only known workflow artifacts, including incomplete runs, without following report paths."""

import re
from pathlib import Path

from algofactory.web.service import Jobs, confined, read_json, report_catalog

STEPS = (
    "a. 理解需求",
    "b. 检索知识",
    "c. 规划方案",
    "d. 生成代码",
    "e. 测试与评估",
    "f. 修复或优化",
    "g. 结果沉淀",
)
FILES = (
    "task.json",
    "retrieval.json",
    "knowledge-input.json",
    "plan.json",
    "plan-proposal.json",
    "candidate.py",
    "configuration-check.json",
    "report.json",
    "repair-input.json",
    "trace.json",
    "ranking.json",
    "decisions.json",
    "selection.json",
    "provider-usage.json",
    "resume-origin.json",
)


def workflow_evidence(root, relative):
    root = Path(root).resolve()
    match = re.fullmatch(r"runtime/web-jobs/([a-f0-9]{32})/run", relative)
    if relative not in report_catalog(root) and not (match and match[1] in Jobs(root).list()):
        raise ValueError("unknown_workflow")
    directory = confined(root, relative)

    # Do not expose even an in-workspace credential symlink under an allowed artifact name.
    def safe(path):
        return path.resolve().is_relative_to(directory) and not any(
            p.is_symlink() for p in (path, *path.parents) if p != root and root in p.parents
        )

    warnings = []

    def bundle(path):
        result = {}
        for name in FILES:
            file = path / name
            if not safe(file) or not file.is_file():
                continue
            try:
                if file.stat().st_size > 1_000_000:
                    raise ValueError("oversize")
                value = file.read_text() if name.endswith(".py") else read_json(file)
                expected = (
                    list if name in {"retrieval.json", "trace.json", "decisions.json"} else dict
                )
                if name.endswith(".json") and not isinstance(value, expected):
                    raise ValueError("invalid_artifact_shape")
                result[name] = value
            except (OSError, ValueError):
                warnings.append(str(file.relative_to(directory)))
        return result

    summary = bundle(directory)
    versions = {}
    for algorithm in ("text_logistic", "text_nb"):
        for attempt in range(3):
            name = f"candidates/{algorithm}/attempt-{attempt}"
            path = directory / name
            if safe(path) and path.is_dir():
                versions[name] = bundle(path)
    if not versions:
        versions["single"] = summary
    return {"summary": summary, "versions": versions, "warnings": warnings}


def stage_rows(bundle, terminal=False):
    """Statuses describe available evidence, never invent a running/completed stage."""
    report = bundle.get("report.json", {})
    validation = report.get("validation") or {}
    missing = "未产出 / 未留存" if terminal else "待产出"
    statuses = [
        "已解析" if bundle.get("task.json") else missing,
        "已检索" if bundle.get("retrieval.json") else missing,
        "方案已校验"
        if bundle.get("plan.json")
        else ("仅有提案，未通过校验" if bundle.get("plan-proposal.json") else missing),
        "代码已生成" if bundle.get("candidate.py") else missing,
        {"passed": "通过", "failed": "未通过", "stopped": "已停止"}.get(
            validation.get("status"), "已有评估记录" if validation else missing
        ),
        "已提交修复反馈" if bundle.get("repair-input.json") else "未记录修复",
        "已回写（含失败记录）"
        if report.get("persisted")
        else ("回写未完成" if report else missing),
    ]
    return [
        {"步骤": name, "当前版本的证据": status}
        for name, status in zip(STEPS, statuses, strict=True)
    ]
