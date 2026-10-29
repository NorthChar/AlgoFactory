"""UI reruns, safe evidence paths and durable job recovery; no paid API calls."""

import fcntl
import json
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from algofactory.datasets import write_json
from algofactory.web.service import (
    Jobs,
    RunSettings,
    artifacts,
    confined,
    graph_snapshot,
    graph_view,
)

ROOT = Path(__file__).resolve().parents[1]


def test_job_submission_idempotent_and_cancel(tmp_path, monkeypatch):
    popen = Mock()
    monkeypatch.setattr("algofactory.web.service.subprocess.Popen", popen)
    jobs = Jobs(tmp_path)
    token = "a" * 32
    settings = RunSettings()
    jobs.submit(settings, token)
    jobs.submit(settings, token)
    assert popen.call_count == 1
    with pytest.raises(ValueError, match="conflict"):
        jobs.submit(RunSettings(max_repairs=2), token)
    jobs.cancel(token)
    assert (jobs.path(token) / "cancel.request").exists()
    assert "api_key" not in (jobs.path(token) / "settings.json").read_text()


def test_live_lock_and_interrupted_recovery_without_restart(tmp_path, monkeypatch):
    popen = Mock()
    monkeypatch.setattr("algofactory.web.service.subprocess.Popen", popen)
    jobs = Jobs(tmp_path)
    token = "b" * 32
    jobs.submit(RunSettings(), token)
    job = jobs.path(token)
    write_json(job / "state.json", {"status": "running"})
    with (job / "job.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert Jobs(tmp_path).state(token)["status"] == "running"
    assert jobs.state(token)["status"] == "interrupted"
    assert popen.call_count == 1
    write_json(job / "state.json", {"status": "running"})
    write_json(job / "run/report.json", {"status": "validated"})
    assert Jobs(tmp_path).state(token) == {"status": "validated", "recovered_from_report": True}
    assert popen.call_count == 1


@pytest.mark.parametrize(
    "settings",
    [
        {"mode": "api", "call_budget": 13},
        {"task": "regression", "compare": True},
        {"experiences": True, "compare": False},
        {"request": "unknown mock input"},
    ],
)
def test_invalid_settings_cannot_start(settings):
    with pytest.raises(ValueError):
        RunSettings(**settings)


def test_paths_and_symlinks_cannot_read_credentials(tmp_path):
    (tmp_path / "escape").symlink_to(ROOT)
    for relative in ("../.env", "escape/.env"):
        with pytest.raises(ValueError):
            confined(tmp_path, relative)
    with pytest.raises(ValueError):
        artifacts(ROOT, ".")
    with pytest.raises(ValueError):
        Jobs(tmp_path).path("../../.env")


def test_graph_read_only_hash_and_source_edges():
    path = ROOT / "examples/phase4/library.sqlite"
    before = path.read_bytes()
    snapshot = graph_snapshot(path)
    entity = next(e for e in snapshot["entities"] if e["type"] == "Experience")
    dot, record = graph_view(snapshot, entity["id"])
    assert "DERIVED_FROM" in dot and record == entity and path.read_bytes() == before


def test_app_default_and_reports_and_graph(tmp_path, monkeypatch):
    # Isolate UI job state but use immutable source archives for realistic report browsing.
    (tmp_path / "examples").symlink_to(ROOT / "examples", target_is_directory=True)
    # A symlink outside the workspace is intentionally excluded; copy only needed evidence instead.
    (tmp_path / "examples").unlink()
    for relative in (
        "examples/phase4/library.sqlite",
        "examples/phase3/unsafe-code/report.json",
        "examples/api-phase3/comparison/report.json",
    ):
        dest = tmp_path / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, dest)
    monkeypatch.setenv("ALGOFACTORY_PROJECT_ROOT", str(tmp_path))
    app = AppTest.from_file(str(ROOT / "src/algofactory/web/app.py"), default_timeout=30).run()
    assert not app.exception
    assert app.radio[0].value == "mock" and app.selectbox[0].value == "banking77"
    report = next(s for s in app.selectbox if s.label == "查看报告")
    report.select("examples/api-phase3/comparison").run()
    assert not app.exception and any(e.value == "最终测试通过" for e in app.subheader)
    app.selectbox[0].select("regression").run()
    assert not app.exception and not app.checkbox[0].value
    assert len(app.get("graphviz_chart")) == 1


def test_app_submit_only_on_click_and_refresh_no_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("ALGOFACTORY_PROJECT_ROOT", str(tmp_path))
    popen = Mock()
    monkeypatch.setattr("algofactory.web.service.subprocess.Popen", popen)
    app = AppTest.from_file(str(ROOT / "src/algofactory/web/app.py"), default_timeout=30).run()
    assert popen.call_count == 0
    next(b for b in app.button if b.label == "开始验证").click().run()
    assert not app.exception and popen.call_count == 1
    app.run()
    assert popen.call_count == 1
    state = json.loads(next((tmp_path / "runtime/web-jobs").glob("*/settings.json")).read_text())
    assert state["mode"] == "mock" and state["call_budget"] == 24
