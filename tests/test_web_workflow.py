"""Seven-step browsing preserves evidence and never runs a model or follows artifact paths."""

import json
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from algofactory.datasets import write_json
from algofactory.web.evidence import FILES, stage_rows, workflow_evidence

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = "examples/api-phase3/comparison"


def copy_archive(root):
    for path in (ROOT / ARCHIVE).rglob("*"):
        if path.is_file() and path.name in FILES:
            dest = root / path.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)


def test_archived_paths_are_relocated_and_evidence_is_not_modified(tmp_path):
    copy_archive(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = workflow_evidence(tmp_path, ARCHIVE)
    assert not result["warnings"]
    versions = result["versions"]
    assert len(versions) == 3
    failed = versions["candidates/text_logistic/attempt-0"]
    fixed = versions["candidates/text_logistic/attempt-1"]
    assert failed["report.json"]["status"] == "failed"
    assert fixed["report.json"]["status"] == "validated"
    assert fixed["repair-input.json"]["previous_code"]
    assert fixed["candidate.py"] != failed["candidate.py"]
    assert result["summary"]["report.json"]["test_attempted"]
    assert all(p.read_bytes() == contents for p, contents in before.items())


def test_partial_run_no_false_success_and_no_symlink_reads(tmp_path):
    relative = "runtime/web-jobs/" + "d" * 32 + "/run"
    directory = tmp_path / relative
    write_json(directory.parent / "state.json", {"status": "running"})
    write_json(directory / "task.json", {"target": "intent"})
    (directory / "plan.json").write_text('{"unfinished":')
    secret = tmp_path / ".env"
    secret.write_text("SECRET_TEST_SENTINEL")
    (directory / "candidate.py").symlink_to(secret)
    result = workflow_evidence(tmp_path, relative)
    bundle = result["versions"]["single"]
    assert "candidate.py" not in bundle
    assert result["warnings"] == ["plan.json"]
    statuses = [r["当前版本的证据"] for r in stage_rows(bundle)]
    assert statuses[0] == "已解析" and statuses[2:5] == ["待产出"] * 3
    assert statuses[-1] == "待产出"
    assert "SECRET_TEST_SENTINEL" not in json.dumps(result)
    with pytest.raises(ValueError):
        workflow_evidence(tmp_path, "../.env")
    with pytest.raises(ValueError):
        workflow_evidence(tmp_path, "runtime/unregistered")


def test_early_failure_writeback_does_not_claim_algorithm_success():
    bundle = {
        "report.json": {"status": "failed", "persisted": True},
        "plan-proposal.json": {"algorithm_id": "unvalidated"},
    }
    rows = stage_rows(bundle, terminal=True)
    assert rows[2]["当前版本的证据"] == "仅有提案，未通过校验"
    assert rows[4]["当前版本的证据"] == "未产出 / 未留存"
    assert rows[5]["当前版本的证据"] == "未记录修复"
    assert rows[6]["当前版本的证据"] == "已回写（含失败记录）"


def test_seven_step_history_browsing_has_real_evidence_and_no_calls(tmp_path, monkeypatch):
    copy_archive(tmp_path)
    monkeypatch.setenv("ALGOFACTORY_PROJECT_ROOT", str(tmp_path))
    popen = Mock()
    monkeypatch.setattr("algofactory.web.service.subprocess.Popen", popen)
    app = AppTest.from_file(str(ROOT / "src/algofactory/web/app.py"), default_timeout=30).run()
    next(
        b for b in app.button if b.label == "先看真实 API 完整历史案例（不产生费用）"
    ).click().run()
    assert any("正在查看历史归档案例" in i.value for i in app.info)
    for step in range(7):
        next(r for r in app.radio if r.label == "查看流程步骤").set_value(step).run()
        assert not app.exception
        if step == 1:
            assert any("TF-IDF + Logistic Regression" in m.value for m in app.markdown)
        if step == 3:
            assert any("build_pipeline" in c.value for c in app.code)
        if step == 5:
            assert any("修复前" in c.value and "ColumnTransformer" in c.value for c in app.code)
            assert any("验证集通过" in m.value for m in app.markdown)
        if step == 6:
            assert any("运行结果已回写" in s.value for s in app.success)
    assert popen.call_count == 0
    assert not list((tmp_path / "runtime/web-jobs").glob("*/settings.json"))


def test_introduction_explains_deliverables_and_navigates_without_submission(tmp_path, monkeypatch):
    copy_archive(tmp_path)
    monkeypatch.setenv("ALGOFACTORY_PROJECT_ROOT", str(tmp_path))
    popen = Mock()
    monkeypatch.setattr("algofactory.web.service.subprocess.Popen", popen)
    app = AppTest.from_file(str(ROOT / "src/algofactory/web/app.py"), default_timeout=30).run()
    assert app.session_state["workspace_tab"] == "从这里开始"
    assert any("① 算法代码" in m.value for m in app.markdown)
    assert any("② 验证报告" in m.value for m in app.markdown)
    next(b for b in app.button if b.label == "看一个已经完成的例子").click().run()
    assert not app.exception
    assert app.session_state["workspace_tab"] == "我的开发任务"
    assert next(s for s in app.selectbox if s.label == "选择开发任务").value == ARCHIVE
    next(b for b in app.button if b.label == "体验银行客服分类示例").click().run()
    assert not app.exception
    assert app.session_state["workspace_tab"] == "创建算法开发任务"
    assert popen.call_count == 0


def test_single_validation_only_has_no_repair_or_final_test(tmp_path, monkeypatch):
    relative = "runtime/web-jobs/" + "e" * 32 + "/run"
    write_json(
        tmp_path / relative / "report.json",
        {
            "status": "validated",
            "workflow_id": "single",
            "provider_mode": "mock",
            "test_attempted": False,
            "persisted": True,
            "validation": {"status": "passed", "validation_metrics": {"macro_f1": 0.87}},
        },
    )
    write_json(tmp_path / relative / "../state.json", {"status": "validated"})
    monkeypatch.setenv("ALGOFACTORY_PROJECT_ROOT", str(tmp_path))
    app = AppTest.from_file(str(ROOT / "src/algofactory/web/app.py"), default_timeout=30).run()
    for step in (4, 5):
        next(r for r in app.radio if r.label == "查看流程步骤").set_value(step).run()
        assert not app.exception
    assert any("本次尚无修复反馈记录" in i.value for i in app.info)
    assert any("未运行最终测试" in i.value for i in app.info)


def test_submission_opens_same_task_before_report_and_refresh_does_not_replay(
    tmp_path, monkeypatch
):
    copy_archive(tmp_path)
    monkeypatch.setenv("ALGOFACTORY_PROJECT_ROOT", str(tmp_path))
    popen = Mock()
    monkeypatch.setattr("algofactory.web.service.subprocess.Popen", popen)
    app = AppTest.from_file(ROOT / "src/algofactory/web/app.py", default_timeout=30).run()
    next(b for b in app.button if b.label == "开始生成并验证").click().run()
    assert not app.exception and popen.call_count == 1
    identifier = app.session_state["current_job"]
    relative = f"runtime/web-jobs/{identifier}/run"
    assert app.session_state["workspace_tab"] == "我的开发任务"
    assert next(s for s in app.selectbox if s.label == "选择开发任务").value == relative
    assert not any(b.label == "预测这条咨询" for b in app.button)
    assert any("等待启动" in s.value for s in app.subheader)
    assert not any("正在查看历史归档案例" in s.value for s in app.info)
    # Simulate the durable runner completing; refresh reveals this exact job's result.
    shutil.copytree(tmp_path / ARCHIVE, tmp_path / relative)
    write_json(tmp_path / relative / "../state.json", {"status": "accepted"})
    app.run()
    assert not app.exception and popen.call_count == 1
    assert next(s for s in app.selectbox if s.label == "选择开发任务").value == relative
    assert any("已绑定当前任务的交付版本" in c.value for c in app.caption)
    assert any(t.label == "试用本次算法" for t in app.tabs)
    # Browsing history must not leave this job's progress attached to the archived report.
    next(s for s in app.selectbox if s.label == "选择开发任务").select(ARCHIVE).run()
    assert not app.exception and popen.call_count == 1
    assert not any(s.value.startswith("当前任务：") for s in app.subheader)
    assert any("正在查看历史归档案例" in s.value for s in app.info)
