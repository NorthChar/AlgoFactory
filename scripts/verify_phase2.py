"""Verify the Mock single-candidate workflow with real Docker, retaining reproducible evidence."""

import argparse
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from algofactory.datasets import sha256_file, write_json
from algofactory.knowledge.graph import export_graphml, load_graphml
from algofactory.knowledge.store import KnowledgeStore
from algofactory.schemas.knowledge import KnowledgeBatch

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("runtime/phase2-verification"))
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error("Output directory must be new or empty; evidence is never overwritten")
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "phase": 2,
        "scope": "Mock LLM with real isolated execution; single candidate, no repair",
        "status": "in_progress",
        "live_api": "not_run",
        "api_adapter": "simulated transport tested, not a live API",
        "checks": [],
    }
    report_path = out / "verification.json"
    write_json(report_path, summary)

    def command(arguments, expected=0):
        result = subprocess.run(
            [sys.executable, *arguments],
            cwd=ROOT,
            env=os.environ.copy() | {"ALGOFACTORY_DOCKER_TESTS": "1"},
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        log = f"check-{len(summary['checks']) + 1}.log"
        (out / log).write_text(result.stdout + result.stderr)
        summary["checks"].append(
            {
                "command": ["python", *arguments],
                "exit_code": result.returncode,
                "expected_exit_code": expected,
                "log": log,
            }
        )
        write_json(report_path, summary)
        if result.returncode != expected:
            raise RuntimeError("Check failed: " + log)

    try:
        command(["-m", "ruff", "check", "src", "tests", "scripts"])
        command(["-m", "ruff", "format", "--check", "src", "tests", "scripts"])
        command(["scripts/check_scaffold.py"])
        command(["-m", "pytest", "-q", f"--junitxml={out / 'tests.xml'}"])
        suite = ET.parse(out / "tests.xml").getroot().find("testsuite")
        summary["tests"] = {
            key: int(suite.attrib[key]) for key in ("tests", "failures", "errors", "skipped")
        }
        assert summary["tests"]["skipped"] == 0, "Docker tests must actually execute"
        command(["-m", "algofactory.cli", "prepare-data", "--output-dir", str(out / "dataset")])
        command(["-m", "algofactory.cli", "calibrate", "--dataset-dir", str(out / "dataset")])
        runs = {}
        for name, fault, category in (
            ("normal", None, None),
            ("repeat", None, None),
            ("missing-interface", "missing_predict_proba", "interface_missing_predict_proba"),
            ("unsafe-code", "unsafe_code", "unapproved_import"),
            ("invalid-response", "invalid_json", "invalid_structured_response"),
        ):
            arguments = [
                "-m",
                "algofactory.cli",
                "demo",
                "--mode",
                "mock",
                "--output-dir",
                str(out / name),
                "--dataset-dir",
                str(out / "dataset"),
                "--db",
                str(out / "knowledge.sqlite"),
            ]
            if fault:
                arguments += ["--fault", fault]
            command(arguments, expected=1 if fault else 0)
            result = json.loads((out / name / "report.json").read_text())
            assert result["status"] == ("failed" if fault else "accepted")
            assert result["persisted"] and result["error_category"] == category
            if fault:
                assert not result["test_attempted"]
                assert not (out / name / "test-access.json").exists()
            runs[name] = result
        normal, repeat = runs["normal"]["validation"], runs["repeat"]["validation"]
        for key in ("validation_metrics", "test_metrics", "code_hash", "config_hash", "split_id"):
            assert normal[key] == repeat[key], key
        with KnowledgeStore(out / "knowledge.sqlite") as store:
            for result in runs.values():
                assert store.get_workflow(result["workflow_id"])["status"] == result["status"]
            batch = KnowledgeBatch.model_validate(store.snapshot())
            store.export_json(out / "knowledge.json")
            export_graphml(batch, out / "knowledge.graphml")
            reloaded = load_graphml(out / "knowledge.graphml")
            for field in ("sources", "entities", "relations"):
                assert sorted(getattr(reloaded, field), key=lambda item: item.id) == sorted(
                    getattr(batch, field), key=lambda item: item.id
                )
            assert not store.connection.execute("PRAGMA foreign_key_check").fetchall()
            assert store.search(entity_type="Experience") == []
        shutil.copy2(ROOT / "runtime/docker-image.json", out / "docker-image.json")
        summary.update(
            status="passed",
            timestamp=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            tests_repeat_identical=True,
            validation_metrics=normal["validation_metrics"],
            test_metrics=normal["test_metrics"],
            workflow_ids={name: result["workflow_id"] for name, result in runs.items()},
            host_environment={
                "python": platform.python_version(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "packages": {
                    name: importlib.metadata.version(name)
                    for name in ("algofactory", "scikit-learn", "numpy", "pandas", "pydantic")
                },
            },
            docker_image=json.loads((out / "docker-image.json").read_text()),
        )
        code_files = sorted(
            {
                *ROOT.glob("src/**/*.py"),
                *ROOT.glob("src/**/*.json"),
                *ROOT.glob("src/**/*.txt"),
                *ROOT.glob("tests/**/*.py"),
                *ROOT.glob("scripts/*.py"),
                ROOT / "docker/Dockerfile",
                ROOT / "pyproject.toml",
                ROOT / "uv.lock",
                ROOT / "requirements.txt",
                ROOT / "requirements-dev.txt",
                ROOT / "data/customer_churn.txt",
            }
        )
        summary["code_sha256"] = {str(p.relative_to(ROOT)): sha256_file(p) for p in code_files}
        summary["git_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        summary["code_worktree_dirty"] = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain", "--", *summary["code_sha256"]], cwd=ROOT, text=True
            ).strip()
        )
        summary["artifacts_sha256"] = {
            str(p.relative_to(out)): sha256_file(p)
            for p in sorted(out.rglob("*"))
            if p.is_file() and p != report_path
        }
        write_json(report_path, summary)
        print(
            json.dumps({"status": "passed", "report": str(report_path), "tests": summary["tests"]})
        )
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        summary.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        write_json(report_path, summary)
        print(f"FAILED: see {report_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
