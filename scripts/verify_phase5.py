#!/usr/bin/env python3
"""Phase 5 acceptance: CLI/Web, plugins, three tasks, recovery and real timeout; no paid API."""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from zoneinfo import ZoneInfo

from verify_phase3 import code_files
from verify_phase4 import compressed_evidence

from algofactory.datasets import generate_dataset, sha256_file, verify_dataset, write_json
from algofactory.execution.docker import DockerExecutor
from algofactory.knowledge.graph import export_graphml, load_graphml
from algofactory.knowledge.store import KnowledgeStore
from algofactory.plugins import default_registry
from algofactory.regression import generate_regression
from algofactory.schemas.contracts import ExecutionBudget
from algofactory.schemas.knowledge import KnowledgeBatch
from algofactory.tasks import BANKING77
from algofactory.web.service import Jobs, read_json
from algofactory.workflow_models import WorkflowFailure

ROOT = Path(__file__).resolve().parents[1]


def sources():
    return sorted(set(code_files()) | {ROOT / "requirements-web.txt"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    summary = {
        "phase": 5,
        "status": "in_progress",
        "live_api": "not_run",
        "paid_api_calls": 0,
        "started_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "code_sha256": {str(p.relative_to(ROOT)): sha256_file(p) for p in sources()},
        "checks": [],
        "command": [sys.executable, *sys.argv],
    }
    path = out / "verification.json"
    write_json(path, summary)
    environment = os.environ.copy() | {
        "ALGOFACTORY_DOCKER_TESTS": "1",
        "ALGOFACTORY_BANKING_DATA": str(ROOT / "runtime/banking77-data"),
    }

    def command(arguments, expected=0):
        result = subprocess.run(
            [sys.executable, *arguments],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=900,
        )
        name = f"check-{len(summary['checks']) + 1}.log"
        (out / name).write_text(result.stdout + result.stderr)
        summary["checks"].append(
            {
                "command": ["python", *arguments],
                "exit_code": result.returncode,
                "expected_exit_code": expected,
                "log": name,
            }
        )
        write_json(path, summary)
        assert result.returncode == expected, name

    try:
        assert not subprocess.check_output(
            ["git", "status", "--porcelain", "--", *summary["code_sha256"]], cwd=ROOT
        ).strip(), "Commit implementation before acceptance"
        command(["-m", "ruff", "check", "src", "tests", "scripts"])
        command(["-m", "ruff", "format", "--check", "src", "tests", "scripts"])
        command(["scripts/check_scaffold.py"])
        command(["-m", "pytest", "-q", f"--junitxml={out / 'tests.xml'}"])
        suite = ET.parse(out / "tests.xml").getroot().find("testsuite")
        summary["tests"] = {
            k: int(suite.attrib[k]) for k in ("tests", "failures", "errors", "skipped")
        }
        assert all(summary["tests"][k] == 0 for k in ("failures", "errors", "skipped"))
        write_json(out / "plugins.json", default_registry().describe())
        shutil.copytree(ROOT / "runtime/banking77-data", out / "banking77-data")
        generate_dataset(out / "churn-data")
        generate_regression(out / "regression-data")
        reports = {}
        for name, task, fault in (
            ("banking77", "banking77", None),
            ("churn", "churn", None),
            ("regression", "regression", None),
            ("unsafe", "regression", "unsafe_code"),
        ):
            arguments = [
                "-m",
                "algofactory.cli",
                "demo",
                "--mode",
                "mock",
                "--task",
                task,
                "--dataset-dir",
                str(out / (task + "-data")),
                "--db",
                str(out / (name + ".sqlite")),
                "--output-dir",
                str(out / name),
            ]
            if fault:
                arguments += ["--fault", fault]
            command(arguments, 1 if fault else 0)
            report = read_json(out / name / "report.json")
            assert report["status"] == ("failed" if fault else "accepted"), name
            assert report["persisted"] and report["test_attempted"] is (not bool(fault))
            if fault:
                assert (
                    report["error_category"] == "unapproved_import"
                    and not (out / name / "validation-execution").exists()
                )
            with KnowledgeStore(out / (name + ".sqlite")) as store:
                assert store.get_workflow(report["workflow_id"])["status"] == report["status"]
                batch = KnowledgeBatch.model_validate(store.snapshot())
                export_graphml(batch, out / (name + ".graphml"))
                reloaded = load_graphml(out / (name + ".graphml"))
                for field in ("sources", "entities", "relations"):
                    assert sorted(getattr(batch, field), key=lambda x: x.id) == sorted(
                        getattr(reloaded, field), key=lambda x: x.id
                    )
            reports[name] = report
        previous = read_json(ROOT / "examples/phase2/normal/report.json")["validation"]
        for key in ("validation_metrics", "test_metrics", "code_hash", "split_id"):
            assert reports["churn"]["validation"][key] == previous[key], key
        # Exercise a real enforced timeout, rather than labeling a mocked subprocess as a stress test.
        executor = DockerExecutor(ROOT / "runtime/docker-image.json", ROOT / "requirements.txt")
        manifest = verify_dataset(out / "banking77-data")
        try:
            executor.execute(
                out / "banking77/candidate.py",
                out / "banking77-data/train.csv",
                out / "banking77-data/validation_features.csv",
                BANKING77.intent()
                | {"class_labels": manifest["class_labels"], "seed": 42, "stage": "validation"},
                out / "timeout",
                ExecutionBudget(timeout_seconds=1),
            )
            raise AssertionError("Expected timeout was not observed")
        except WorkflowFailure as exc:
            assert exc.category == "execution_timeout", exc.category
            assert read_json(out / "timeout/cleanup.json")["exit_code"] == 0
            summary["real_timeout_and_cleanup"] = True
        # AppTest uses real form callbacks and launches the same child runner as the live UI.
        from streamlit.testing.v1 import AppTest

        os.environ["ALGOFACTORY_PROJECT_ROOT"] = str(ROOT)
        jobs = Jobs(ROOT)
        ui_trials = []
        for task, use_experiences in (("banking77", True), ("regression", False)):
            app = AppTest.from_file(
                str(ROOT / "src/algofactory/web/app.py"), default_timeout=30
            ).run()
            assert not app.exception
            next(s for s in app.selectbox if s.label == "任务").select(task).run()
            if use_experiences:
                next(c for c in app.checkbox if c.label == "使用适用的已验证经验").check().run()
            before = set(jobs.list())
            next(b for b in app.button if b.label == "开始验证").click().run()
            assert not app.exception
            added = set(jobs.list()) - before
            assert len(added) == 1
            identifier = added.pop()
            app.run()
            assert set(jobs.list()) - before == {identifier}, "Rerun duplicated a job"
            deadline = time.monotonic() + 600
            while (
                jobs.state(identifier)["status"] in {"queued", "running"}
                and time.monotonic() < deadline
            ):
                time.sleep(0.3)
            assert jobs.state(identifier)["status"] == "validated", jobs.state(identifier)
            report = read_json(jobs.path(identifier) / "run/report.json")
            assert report["persisted"] and not report["test_attempted"]
            # Fresh browser session discovers persisted work without another submission.
            restored = AppTest.from_file(
                str(ROOT / "src/algofactory/web/app.py"), default_timeout=30
            ).run()
            next(s for s in restored.selectbox if s.label == "本地任务").select(identifier).run()
            next(b for b in restored.button if b.label == "恢复查看此任务").click().run()
            next(s for s in restored.selectbox if s.label == "查看报告").select(
                str((jobs.path(identifier) / "run").relative_to(ROOT))
            ).run()
            assert not restored.exception and len(restored.get("download_button")) >= 3
            assert set(jobs.list()) - before == {identifier}
            dest = out / ("web-" + task)
            shutil.copytree(jobs.path(identifier), dest)
            ui_trials.append(
                {
                    "task": task,
                    "job_id": identifier,
                    "status": report["status"],
                    "form_submission": True,
                    "rerun_duplicate_count": 0,
                    "fresh_session_recovery": True,
                    "report_downloads_present": True,
                    "experience_enabled": use_experiences,
                    "validation_metrics": report["validation"]["validation_metrics"],
                }
            )
        # Cooperative cancellation before work begins; full execution cleanup is tested separately.
        token = uuid.uuid4().hex
        job = jobs.path(token)
        job.mkdir()
        from algofactory.web.runner import execute
        from algofactory.web.service import RunSettings

        write_json(job / "settings.json", RunSettings().model_dump(mode="json"))
        write_json(job / "state.json", {"status": "queued", "created": time.time()})
        jobs.cancel(token)
        assert execute(ROOT, token) == 1 and jobs.state(token)["status"] == "stopped"
        assert not (job / "run/provider-audit.json").exists()
        shutil.copytree(job, out / "cancelled-before-start")
        summary.update(
            web_trials=ui_trials,
            cancellation_before_start=True,
            churn_compatible=True,
            cli_runs={
                name: {
                    "status": r["status"],
                    "validation_metrics": r.get("validation", {}).get("validation_metrics", {}),
                    "test_metrics": r.get("validation", {}).get("test_metrics", {}),
                }
                for name, r in reports.items()
            },
        )
        shutil.copy2(ROOT / "runtime/docker-image.json", out / "docker-image.json")
        summary["predictions_archives"] = compressed_evidence(out)
        assert summary["code_sha256"] == {
            str(p.relative_to(ROOT)): sha256_file(p) for p in sources()
        }
        summary.update(
            status="passed",
            finished_at=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            host={
                "python": platform.python_version(),
                "machine": platform.machine(),
                "packages": {
                    name: version(name)
                    for name in ("streamlit", "pandas", "scikit-learn", "graphviz")
                },
            },
        )
        summary["artifacts_sha256"] = {
            str(p.relative_to(out)): sha256_file(p)
            for p in sorted(out.rglob("*"))
            if p.is_file() and p != path
        }
        write_json(path, summary)
        print(json.dumps({"status": "passed", "tests": summary["tests"], "report": str(path)}))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        summary.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        write_json(path, summary)
        print("FAILED: " + str(path), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
