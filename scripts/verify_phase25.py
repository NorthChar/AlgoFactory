"""Phase 2.5: both task profiles, real Docker, strict gates and replayable evidence."""

import argparse
import gzip
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

from algofactory.banking import import_banking77
from algofactory.datasets import generate_dataset, sha256_file, write_json
from algofactory.knowledge.graph import export_graphml, load_graphml
from algofactory.knowledge.store import KnowledgeStore
from algofactory.schemas.knowledge import KnowledgeBatch
from algofactory.validation.protocol import calibrate

ROOT = Path(__file__).resolve().parents[1]


def code_files():
    return sorted(
        p
        for p in {
            *ROOT.glob("src/**/*.py"),
            *ROOT.glob("src/**/*.json"),
            *ROOT.glob("src/**/*.txt"),
            *ROOT.glob("tests/**/*.py"),
            *ROOT.glob("scripts/*.py"),
            *ROOT.glob("data/*.txt"),
            ROOT / "docker/Dockerfile",
            ROOT / "pyproject.toml",
            ROOT / "uv.lock",
            ROOT / "requirements.txt",
            ROOT / "requirements-dev.txt",
        }
        if not any(part.endswith(".egg-info") for part in p.parts)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("runtime/phase25-verification"))
    parser.add_argument(
        "--raw-dir", type=Path, help="Pinned BANKING77 train.csv/test.csv/LICENSE; omit to download"
    )
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error("Output must be new or empty; evidence is never overwritten")
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "phase": "2.5",
        "scope": "BANKING77 main case and synthetic churn compatibility; Mock LLM, real Docker",
        "status": "in_progress",
        "live_api": "not_run",
        "checks": [],
        "started_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "code_sha256": {str(p.relative_to(ROOT)): sha256_file(p) for p in code_files()},
    }
    summary["code_worktree_dirty"] = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain", "--", *summary["code_sha256"]], cwd=ROOT, text=True
        ).strip()
    )
    report_path = out / "verification.json"
    write_json(report_path, summary)
    environment = os.environ.copy() | {
        "ALGOFACTORY_DOCKER_TESTS": "1",
        "ALGOFACTORY_BANKING_DATA": str(out / "banking77-data"),
    }

    def command(arguments, expected=0):
        result = subprocess.run(
            [sys.executable, *arguments],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=900,
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
        if summary["code_worktree_dirty"]:
            raise RuntimeError(
                "Commit implementation first so both tasks share a traceable clean source revision"
            )
        command(["-m", "ruff", "check", "src", "tests", "scripts"])
        command(["-m", "ruff", "format", "--check", "src", "tests", "scripts"])
        command(["scripts/check_scaffold.py"])
        import_banking77(out / "banking77-data", args.raw_dir)
        generate_dataset(out / "churn-data")
        for name in ("banking77", "churn"):
            calibrate(out / (name + "-data"), out / (name + "-data/protocol.json"))
        command(
            [
                "-m",
                "pytest",
                "-q",
                "--ignore=tests/test_phase3.py",
                f"--junitxml={out / 'tests.xml'}",
            ]
        )
        suite = ET.parse(out / "tests.xml").getroot().find("testsuite")
        summary["tests"] = {
            key: int(suite.attrib[key]) for key in ("tests", "failures", "errors", "skipped")
        }
        assert summary["tests"]["skipped"] == 0, "All required tests must actually run"
        runs = {}
        for name, task, fault, category in (
            ("banking77", "banking77", None, None),
            ("banking77-repeat", "banking77", None, None),
            ("churn-compatibility", "churn", None, None),
            (
                "banking77-interface-failure",
                "banking77",
                "missing_predict_proba",
                "interface_missing_predict_proba",
            ),
            ("banking77-unsafe-code", "banking77", "unsafe_code", "unapproved_import"),
            (
                "banking77-invalid-response",
                "banking77",
                "invalid_json",
                "invalid_structured_response",
            ),
        ):
            arguments = [
                "-m",
                "algofactory.cli",
                "demo",
                "--task",
                task,
                "--mode",
                "mock",
                "--dataset-dir",
                str(out / (task + "-data")),
                "--output-dir",
                str(out / name),
                "--db",
                str(out / "knowledge.sqlite"),
            ]
            if fault:
                arguments += ["--fault", fault]
            command(arguments, expected=1 if fault else 0)
            report = json.loads((out / name / "report.json").read_text())
            assert (
                report["status"] == ("failed" if fault else "accepted")
                and report["error_category"] == category
            )
            assert report["persisted"] and report["test_attempted"] is (not bool(fault))
            if fault:
                assert not (out / name / "test-access.json").exists()
            runs[name] = report
        first, repeat = runs["banking77"]["validation"], runs["banking77-repeat"]["validation"]
        for key in ("validation_metrics", "test_metrics", "code_hash", "config_hash", "split_id"):
            assert first[key] == repeat[key], key
        # Churn remains on its original fixed candidate/data; no tolerance change after observing scores.
        historical = json.loads((ROOT / "examples/phase2/normal/report.json").read_text())[
            "validation"
        ]
        compatibility = runs["churn-compatibility"]["validation"]
        for key in ("validation_metrics", "test_metrics", "code_hash", "split_id"):
            assert compatibility[key] == historical[key], "Churn regression: " + key
        with KnowledgeStore(out / "knowledge.sqlite") as store:
            for report in runs.values():
                assert store.get_workflow(report["workflow_id"])["status"] == report["status"]
            batch = KnowledgeBatch.model_validate(store.snapshot())
            store.export_json(out / "knowledge.json")
            export_graphml(batch, out / "knowledge.graphml")
            reloaded = load_graphml(out / "knowledge.graphml")
            for field in ("sources", "entities", "relations"):
                assert sorted(getattr(reloaded, field), key=lambda e: e.id) == sorted(
                    getattr(batch, field), key=lambda e: e.id
                )
            assert not store.connection.execute("PRAGMA foreign_key_check").fetchall()
            assert store.search(entity_type="Experience") == []
            summary["knowledge_reopened"] = True
        shutil.copy2(ROOT / "runtime/docker-image.json", out / "docker-image.json")
        # Lossless compression keeps complete probability matrices without bloating review diffs.
        # Original report hashes remain valid for decompressed bytes; archive map records both identities.
        archives = {}
        for path in sorted(out.rglob("predictions.json")):
            data = path.read_bytes()
            compressed = path.with_suffix(".json.gz")
            compressed.write_bytes(gzip.compress(data, mtime=0))
            assert gzip.decompress(compressed.read_bytes()) == data
            archives[str(path.relative_to(out))] = {
                "archive": str(compressed.relative_to(out)),
                "uncompressed_sha256": sha256_file(path),
                "archive_sha256": sha256_file(compressed),
            }
            path.unlink()
        summary.update(
            status="passed",
            finished_at=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            predictions_archives=archives,
            banking77_repeat_identical=True,
            churn_matches_historical_metrics=True,
            banking77={key: first[key] for key in ("validation_metrics", "test_metrics")},
            churn={key: compatibility[key] for key in ("validation_metrics", "test_metrics")},
            workflow_ids={name: report["workflow_id"] for name, report in runs.items()},
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
        assert summary["code_sha256"] == {
            str(p.relative_to(ROOT)): sha256_file(p) for p in code_files()
        }, "Source changed during verification"
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
