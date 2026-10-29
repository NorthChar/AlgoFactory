#!/usr/bin/env python3
"""Resume an actual API failure, repair and compare under one explicit call budget."""

import argparse
import gzip
import json
import platform
import shutil
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from verify_phase3 import code_files

from algofactory.datasets import sha256_file, verify_dataset, write_json
from algofactory.execution.docker import DockerExecutor
from algofactory.knowledge.graph import export_graphml, load_graphml
from algofactory.knowledge.store import KnowledgeStore
from algofactory.llm.providers import APIConfig, APIProvider
from algofactory.planning import SearchPolicy
from algofactory.resume import validate_resume
from algofactory.schemas.knowledge import KnowledgeBatch
from algofactory.search import run_search
from algofactory.tasks import BANKING77
from algofactory.validation.protocol import calibrate

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resume-failure", type=Path, required=True)
    parser.add_argument("--resume-db", type=Path, required=True)
    parser.add_argument("--tests-xml", type=Path, required=True)
    parser.add_argument("--call-budget", type=int, default=20, choices=range(1, 21))
    parser.add_argument("--dataset-dir", type=Path, default=ROOT / "runtime/banking77-data")
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    summary = {
        "status": "failed",
        "scope": "real Azure API repair and two-candidate comparison",
        "started_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "command": [sys.executable, *sys.argv],
        "request_limit": args.call_budget,
        "automatic_retries": 0,
        "max_repairs_per_candidate": 2,
        "max_attempts_including_historical_failure": 6,
        "historical_failure_reexecuted": False,
        "code_sha256": {str(p.relative_to(ROOT)): sha256_file(p) for p in code_files()},
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "host": {"python": platform.python_version(), "platform": platform.platform()},
    }
    provider = None
    try:
        if subprocess.check_output(
            ["git", "status", "--porcelain", "--", *summary["code_sha256"]], cwd=ROOT, text=True
        ).strip():
            raise ValueError("commit_implementation_before_live_verification")
        suite = ET.parse(args.tests_xml).getroot().find("testsuite")
        summary["tests"] = {
            k: int(suite.attrib[k]) for k in ("tests", "failures", "errors", "skipped")
        }
        assert summary["tests"]["tests"] > 0
        assert all(summary["tests"][k] == 0 for k in ("failures", "errors", "skipped"))
        shutil.copy2(args.tests_xml, out / "tests.xml")
        manifest = verify_dataset(args.dataset_dir)
        protocol = calibrate(args.dataset_dir, args.dataset_dir / "protocol.json")
        assert manifest["task_profile"] == "banking77"
        DockerExecutor(ROOT / "runtime/docker-image.json", ROOT / "requirements.txt")
        original = args.resume_failure.resolve()
        source_db = args.resume_db.resolve()
        # Copy through SQLite backup; never modify the historical database.
        with sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(out / "knowledge.sqlite") as target:
                source.backup(target)
        prior = validate_resume(
            original, out / "knowledge.sqlite", "text_logistic", manifest, protocol
        )
        assert prior["provider_mode"] == "api"
        summary["resumed_failure"] = {
            "workflow_id": prior["workflow_id"],
            "report": str(original / "report.json"),
            "report_sha256": sha256_file(original / "report.json"),
            "code_hash": prior["code_hash"],
            "error_category": prior["error_category"],
        }
        config = APIConfig.from_env(args.env_file).model_copy(
            update={
                "max_calls": args.call_budget,
                "max_retries": 0,
            }
        )
        provider = APIProvider(config)
        report = run_search(
            directory=out / "comparison",
            dataset_dir=args.dataset_dir.resolve(),
            db_path=out / "knowledge.sqlite",
            approval_path=ROOT / "runtime/docker-image.json",
            requirements_path=ROOT / "requirements.txt",
            knowledge_document=ROOT / "data/banking77-phase3.txt",
            request=BANKING77.request,
            provider=provider,
            policy=SearchPolicy(),
            resume_failures={"text_logistic": original},
        )
        summary.update(
            workflow_status=report["status"],
            error_category=report["error_category"],
            budget_usage=report["budget_usage"],
            test_attempted=report["test_attempted"],
            persisted=report["persisted"],
            selected_algorithm=report.get("selected_algorithm"),
        )
        assert report["status"] == "accepted" and report["persisted"]
        assert len(report["ranking"]) == 2
        assert {a["algorithm"] for a in report["ranking"]} == {"text_logistic", "text_nb"}
        assert all(not a["test_attempted"] for a in report["attempts"])
        assert len(list((out / "comparison").rglob("test-access.json"))) == 1
        repaired = [a for a in report["attempts"] if a["parent_id"] and a["status"] == "validated"]
        assert repaired and any(
            a.operation == "repair_code" and a.status == "ok" for a in provider.audit
        )
        assert all(a.attempt == 1 for a in provider.audit)
        assert provider.calls <= args.call_budget
        with KnowledgeStore(out / "knowledge.sqlite") as store:
            for attempt in report["attempts"]:
                assert store.get_workflow(attempt["workflow_id"])["status"] == attempt["status"]
                entity = store.evidence(attempt["implementation_id"])["record"]
                assert entity["code_hash"] == attempt["code_hash"]
                assert entity.get("parent_id") == attempt["parent_id"]
                assert entity["version"] == attempt["attempt"] + 1
            assert store.get_workflow(report["workflow_id"])["status"] == "accepted"
            batch = KnowledgeBatch.model_validate(store.snapshot())
            store.export_json(out / "knowledge.json")
            export_graphml(batch, out / "knowledge.graphml")
            restored = load_graphml(out / "knowledge.graphml")
            for field in ("sources", "entities", "relations"):
                assert sorted(getattr(batch, field), key=lambda a: a.id) == sorted(
                    getattr(restored, field), key=lambda a: a.id
                )
            assert not store.connection.execute("PRAGMA foreign_key_check").fetchall()
        summary.update(
            status="passed",
            repair_lineage_verified=True,
            knowledge_reopened=True,
            graph_roundtrip_verified=True,
            one_selected_final_test=True,
            ranking=[
                {k: a[k] for k in ("algorithm", "attempt", "code_hash", "validation_metrics")}
                for a in report["ranking"]
            ],
            final_test_metrics=report["validation"]["test_metrics"],
        )
    except (Exception, KeyboardInterrupt) as exc:
        # Never print raw HTTP responses, model content, or environment values on failures.
        summary.update(status="failed", verification_error_type=type(exc).__name__)
    finally:
        if provider is not None:
            summary["usage"] = provider.usage_summary()
            write_json(
                out / "provider-audit.json", [a.model_dump(mode="json") for a in provider.audit]
            )
        shutil.copy2(ROOT / "runtime/docker-image.json", out / "docker-image.json")
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
        summary["predictions_archives"] = archives
        if summary["code_sha256"] != {
            str(p.relative_to(ROOT)): sha256_file(p) for p in code_files()
        }:
            summary.update(status="failed", verification_error_type="SourceChanged")
        summary["finished_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
        summary["artifacts_sha256"] = {
            str(p.relative_to(out)): sha256_file(p) for p in sorted(out.rglob("*")) if p.is_file()
        }
        write_json(out / "verification.json", summary)
    print(
        json.dumps(
            {
                k: summary.get(k)
                for k in (
                    "status",
                    "workflow_status",
                    "error_category",
                    "verification_error_type",
                    "budget_usage",
                    "usage",
                    "final_test_metrics",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
