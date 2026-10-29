#!/usr/bin/env python3
"""Phase 4: sealed memory, matched on/off trials, real Docker; optional 12-call API budget."""

import argparse
import gzip
import hashlib
import json
import os
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
from algofactory.experience_reuse import synthesize_repair
from algofactory.knowledge.graph import export_graphml, load_graphml
from algofactory.knowledge.store import KnowledgeStore, canonical
from algofactory.llm.providers import APIConfig, APIProvider
from algofactory.llm.workflow_mock import MockWorkflowProvider
from algofactory.planning import SearchPolicy
from algofactory.schemas.knowledge import KnowledgeBatch
from algofactory.search import run_search
from algofactory.tasks import BANKING77_REUSE_REQUEST
from algofactory.validation.protocol import calibrate

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/api-phase3"


def backup(source, destination):
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as old:
        with sqlite3.connect(destination) as new:
            old.backup(new)


def compressed_evidence(out):
    archives = {}
    for path in sorted(out.rglob("predictions.json")):
        data = path.read_bytes()
        archived = path.with_suffix(".json.gz")
        archived.write_bytes(gzip.compress(data, mtime=0))
        assert gzip.decompress(archived.read_bytes()) == data
        archives[str(path.relative_to(out))] = {
            "archive": str(archived.relative_to(out)),
            "uncompressed_sha256": sha256_file(path),
            "archive_sha256": sha256_file(archived),
        }
        path.unlink()
    return archives


def metrics_by_arm(trials):
    results = {}
    for enabled in (False, True):
        selected = [t for t in trials if t["enabled"] is enabled]
        results["on" if enabled else "off"] = {
            "trials": len(selected),
            "validated": sum(t["status"] == "validated" for t in selected),
            "repair_calls": sum(t["repair_calls"] for t in selected),
            "new_provider_calls": sum(t["new_provider_calls"] for t in selected),
            "known_input_tokens": sum(t["known_input_tokens"] for t in selected),
            "known_output_tokens": sum(t["known_output_tokens"] for t in selected),
            "mean_validation_macro_f1": sum(
                t["macro_f1"] for t in selected if t["macro_f1"] is not None
            )
            / max(1, sum(t["macro_f1"] is not None for t in selected)),
        }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, default=ROOT / "runtime/banking77-data")
    parser.add_argument("--live-api", action="store_true")
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.live_api and args.env_file is None:
        parser.error("--live-api requires explicit --env-file")
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    summary = {
        "phase": 4,
        "status": "in_progress",
        "live_api": "not_run",
        "started_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "command": [sys.executable, *sys.argv],
        "checks": [],
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "code_sha256": {str(p.relative_to(ROOT)): sha256_file(p) for p in code_files()},
        "host": {"python": platform.python_version(), "platform": platform.platform()},
        "api_request_limit": 12 if args.live_api else 0,
        "automatic_api_retries": 0,
        "trials": {},
        "causal_benefit_claim": False,
    }
    report_path = out / "verification.json"
    write_json(report_path, summary)
    provider = None
    environment = os.environ.copy() | {
        "ALGOFACTORY_DOCKER_TESTS": "1",
        "ALGOFACTORY_BANKING_DATA": str(args.dataset_dir.resolve()),
    }

    def command(arguments):
        done = subprocess.run(
            [sys.executable, *arguments],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=900,
        )
        log = f"check-{len(summary['checks']) + 1}.log"
        (out / log).write_text(done.stdout + done.stderr)
        summary["checks"].append(
            {"command": ["python", *arguments], "exit_code": done.returncode, "log": log}
        )
        write_json(report_path, summary)
        if done.returncode:
            raise RuntimeError("local_check_failed")

    try:
        if subprocess.check_output(
            ["git", "status", "--porcelain", "--", *summary["code_sha256"]], cwd=ROOT, text=True
        ).strip():
            raise ValueError("commit_implementation_first")
        command(["-m", "ruff", "check", "src", "tests", "scripts"])
        command(["-m", "ruff", "format", "--check", "src", "tests", "scripts"])
        command(["scripts/check_scaffold.py"])
        command(["-m", "pytest", "-q", f"--junitxml={out / 'tests.xml'}"])
        suite = ET.parse(out / "tests.xml").getroot().find("testsuite")
        summary["tests"] = {
            k: int(suite.attrib[k]) for k in ("tests", "failures", "errors", "skipped")
        }
        assert summary["tests"]["tests"] > 0 and all(
            summary["tests"][k] == 0 for k in ("failures", "errors", "skipped")
        )
        manifest = verify_dataset(args.dataset_dir)
        protocol = calibrate(args.dataset_dir, args.dataset_dir / "protocol.json")
        DockerExecutor(ROOT / "runtime/docker-image.json", ROOT / "requirements.txt")
        shutil.copy2(ROOT / "runtime/docker-image.json", out / "docker-image.json")
        backup(SOURCE / "knowledge.sqlite", out / "library.sqlite")
        chain = SOURCE / "comparison/candidates/text_logistic"
        with KnowledgeStore(out / "library.sqlite") as store:
            learned = synthesize_repair(
                store, chain / "attempt-0", chain / "attempt-1", "text_logistic"
            )
            assert learned["experience"]["record"]["verification_status"] == "verified"
            assert all(
                v == 0
                for v in synthesize_repair(
                    store, chain / "attempt-0", chain / "attempt-1", "text_logistic"
                )["inserted"].values()
            )
            snapshot = store.snapshot()
            store.export_json(out / "knowledge.json")
            batch = KnowledgeBatch.model_validate(snapshot)
            export_graphml(batch, out / "knowledge.graphml")
            restored = load_graphml(out / "knowledge.graphml")
            for field in ("sources", "entities", "relations"):
                assert sorted(getattr(batch, field), key=lambda e: e.id) == sorted(
                    getattr(restored, field), key=lambda e: e.id
                )
        write_json(out / "learned-experience.json", learned)
        policy = SearchPolicy(algorithms=["text_logistic"], max_repairs=1, attempt_budget=2)
        initial_failure = out / "historical-failure"
        shutil.copytree(chain / "attempt-0", initial_failure)
        for archived in initial_failure.rglob("*.json.gz"):
            archived.with_suffix("").write_bytes(gzip.decompress(archived.read_bytes()))
            archived.unlink()
        plan = {
            "source_experience_id": learned["experience"]["id"],
            "source_failed_report_sha256": sha256_file(chain / "attempt-0/report.json"),
            "source_passed_report_sha256": sha256_file(chain / "attempt-1/report.json"),
            "library_snapshot_hash": hashlib.sha256(canonical(snapshot).encode()).hexdigest(),
            "request": BANKING77_REUSE_REQUEST,
            "policy": policy.model_dump(mode="json"),
            "data_fingerprint": manifest["data_fingerprint"],
            "split_id": manifest["split_id"],
            "config_hash": protocol["config_hash"],
            "seed": manifest["seed"],
            "order": [False, True, True, False],
            "pairs": 2,
            "validation_only": True,
            "knowledge_from_prior_verified_api": True,
            "api_max_new_calls_per_trial": 3,
            "api_total_call_limit": summary["api_request_limit"],
            "mock_initial_fault": "explicit text_adapter fixture; same faulty code regardless of toggle",
            "api_initial_failure_hash": sha256_file(initial_failure / "candidate.py"),
            "interpretation": "Paired descriptive workflow check, not a statistically powered performance study; unchanged prompts/configuration within each mode except the experience payload and unavoidable run identifiers.",
        }
        write_json(out / "experiment-plan.json", plan)
        # Local compatibility on the same implementation; do not expand the churn case.
        command(
            [
                "-m",
                "algofactory.cli",
                "demo",
                "--task",
                "churn",
                "--output-dir",
                str(out / "churn"),
                "--db",
                str(out / "churn.sqlite"),
            ]
        )
        churn = json.loads((out / "churn/report.json").read_text())
        historical_churn = json.loads((ROOT / "examples/phase2/normal/report.json").read_text())
        assert churn["status"] == "accepted"
        for key in ("validation_metrics", "test_metrics", "code_hash", "split_id"):
            assert churn["validation"][key] == historical_churn["validation"][key]
        summary["churn_compatible"] = True
        for mode in ["mock", "api"] if args.live_api else ["mock"]:
            if mode == "api":
                provider = APIProvider(
                    APIConfig.from_env(args.env_file).model_copy(
                        update={"max_calls": 12, "max_retries": 0}
                    )
                )
            else:
                provider = MockWorkflowProvider("text_adapter", max_calls=24)
                provider.max_retries = 0
            summary["trials"][mode] = []
            builder_instructions = set()
            initial_hashes = set()
            for index, enabled in enumerate(plan["order"]):
                name = f"{mode}-{index + 1}-{'on' if enabled else 'off'}"
                db = out / f"{name}.sqlite"
                backup(out / "library.sqlite", db)
                audit_start = len(provider.audit)
                calls_start = provider.calls
                if mode == "api":
                    provider.max_calls = min(12, calls_start + 3)
                report = run_search(
                    directory=out / name,
                    dataset_dir=args.dataset_dir.resolve(),
                    db_path=db,
                    approval_path=ROOT / "runtime/docker-image.json",
                    requirements_path=ROOT / "requirements.txt",
                    knowledge_document=ROOT / "data/banking77-phase3.txt",
                    request=BANKING77_REUSE_REQUEST,
                    provider=provider,
                    policy=policy,
                    use_experiences=enabled,
                    validation_only=True,
                    reuse_knowledge=True,
                    resume_failures={"text_logistic": initial_failure} if mode == "api" else None,
                )
                records = provider.audit[audit_start:]
                assert all(a.attempt == 1 for a in records)
                assert not report["test_attempted"] and not list(
                    (out / name).rglob("test-access.json")
                )
                assert report["persisted"]
                assert all(not a["test_attempted"] for a in report["attempts"])
                usage = [
                    a["experience_usage"] for a in report["attempts"] if a.get("experience_usage")
                ]
                adopted = any(
                    d["decision"] == "adopted" for u in usage for d in u["model_decisions"]
                )
                observed = any(u["observed_rule_satisfied"] for u in usage)
                assert enabled or not any(u["matches"] or u["model_decisions"] for u in usage)
                for path in (out / name).rglob("builder-input.json"):
                    request = json.loads(path.read_text())
                    builder_instructions.add(request["instruction"])
                    assert "test_metrics" not in json.dumps(request)
                    assert bool(request["source"]["retrieved_experiences"]) is enabled
                initial_hashes.add(report["attempts"][0]["code_hash"])
                with KnowledgeStore(db) as store:
                    assert store.get_workflow(report["workflow_id"])["status"] == report["status"]
                    for attempt in report["attempts"]:
                        assert (
                            store.get_workflow(attempt["workflow_id"])["status"]
                            == attempt["status"]
                        )
                    assert {
                        e["id"] for e in store.snapshot()["entities"] if e["type"] == "Experience"
                    } == {learned["experience"]["id"]}
                trial = {
                    "name": name,
                    "pair": index // 2 + 1,
                    "enabled": enabled,
                    "status": report["status"],
                    "error_category": report["error_category"],
                    "workflow_id": report["workflow_id"],
                    "new_provider_calls": provider.calls - calls_start,
                    "repair_calls": sum(a.operation == "repair_code" for a in records),
                    "known_input_tokens": sum(a.input_tokens or 0 for a in records),
                    "known_output_tokens": sum(a.output_tokens or 0 for a in records),
                    "usage_available": mode == "api",
                    "model_declared_adoption": adopted,
                    "observed_rule_satisfied": observed,
                    "macro_f1": report.get("validation", {})
                    .get("validation_metrics", {})
                    .get("macro_f1"),
                    "test_attempted": False,
                    "persisted": True,
                }
                summary["trials"][mode].append(trial)
                write_json(
                    out / f"{name}/trial-audit.json", [a.model_dump(mode="json") for a in records]
                )
                write_json(report_path, summary)
                print(
                    json.dumps(
                        {
                            "trial": name,
                            "status": trial["status"],
                            "calls": trial["new_provider_calls"],
                            "adopted": adopted,
                        }
                    ),
                    flush=True,
                )
            if mode == "api":
                provider.max_calls = 12
                summary["api_usage"] = provider.usage_summary()
                summary["live_api"] = (
                    "passed"
                    if all(t["status"] == "validated" for t in summary["trials"][mode])
                    else "completed_with_failures"
                )
            assert len(builder_instructions) == 1 and len(initial_hashes) == 1
            assert all(t["status"] == "validated" for t in summary["trials"][mode])
            assert all(
                t["model_declared_adoption"] and t["observed_rule_satisfied"]
                for t in summary["trials"][mode]
                if t["enabled"]
            )
            summary[mode + "_comparison"] = metrics_by_arm(summary["trials"][mode])
        summary.update(
            status="passed",
            knowledge_reopened=True,
            graph_roundtrip=True,
            memory_synthesis_idempotent=True,
            no_banking77_final_test_access=True,
        )
    except (Exception, KeyboardInterrupt) as exc:
        summary.update(status="failed", error_type=type(exc).__name__)
    finally:
        if isinstance(provider, APIProvider):
            provider.max_calls = 12
            summary["api_usage"] = provider.usage_summary()
            write_json(
                out / "api-provider-audit.json", [a.model_dump(mode="json") for a in provider.audit]
            )
        summary["predictions_archives"] = compressed_evidence(out)
        summary["finished_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
        if summary["code_sha256"] != {
            str(p.relative_to(ROOT)): sha256_file(p) for p in code_files()
        }:
            summary.update(status="failed", error_type="SourceChanged")
        summary["artifacts_sha256"] = {
            str(p.relative_to(out)): sha256_file(p)
            for p in sorted(out.rglob("*"))
            if p.is_file() and p != report_path
        }
        write_json(report_path, summary)
    print(
        json.dumps(
            {
                k: summary.get(k)
                for k in (
                    "status",
                    "error_type",
                    "tests",
                    "live_api",
                    "mock_comparison",
                    "api_comparison",
                    "api_usage",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
