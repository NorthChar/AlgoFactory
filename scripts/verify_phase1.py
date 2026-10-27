"""Run Phase 1 checks and produce evidence; never claim algorithm/API-live acceptance."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo

from algofactory.knowledge.extraction import ingest_document
from algofactory.knowledge.graph import export_graphml, load_graphml
from algofactory.knowledge.store import KnowledgeStore
from algofactory.llm.providers import MockProvider
from algofactory.schemas.knowledge import KnowledgeBatch, SourceDocument

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def sorted_batch(batch):
    return {
        key: sorted(values, key=lambda obj: obj["id"])
        for key, values in batch.model_dump(mode="json").items()
        if isinstance(values, list)
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("runtime/phase1"))
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / "verification.json"
    # Replace any stale passing report before running checks, including on interruption.
    write_json(report_path, {"status": "in_progress", "phase": 1})
    commands = [
        [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"],
        [sys.executable, "-m", "ruff", "format", "--check", "src", "tests", "scripts"],
        [sys.executable, "scripts/check_scaffold.py"],
        [sys.executable, "-m", "pytest", "-q", f"--junitxml={out / 'tests.xml'}"],
    ]
    command_records = []
    for index, command in enumerate(commands, 1):
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        log_name = f"check-{index}.log"
        (out / log_name).write_text(result.stdout + result.stderr, encoding="utf-8")
        command_records.append(
            {"command": ["python", *command[1:]], "exit_code": result.returncode, "log": log_name}
        )
        if result.returncode:
            write_json(report_path, {"status": "failed", "phase": 1, "checks": command_records})
            print(f"FAILED: see {out / log_name}", file=sys.stderr)
            return 1
    path = ROOT / "data/customer_churn.txt"
    source = SourceDocument.from_text(path.name, path.read_bytes().decode("utf-8"))
    provider = MockProvider.from_file(files("algofactory.llm").joinpath("fixtures/churn.json"))
    db_path = out / "knowledge.sqlite"
    with KnowledgeStore(db_path) as store:
        first = ingest_document(source, provider, store)
        second = ingest_document(source, provider, store)
        assert second["inserted"] == {"sources": 0, "entities": 0, "relations": 0}
        batch = KnowledgeBatch.model_validate(store.snapshot())
        assert len(batch.sources) == 1 and len(batch.entities) == 6 and len(batch.relations) == 7
        store.export_json(out / "knowledge.json")
        export_graphml(batch, out / "knowledge.graphml")
        assert sorted_batch(load_graphml(out / "knowledge.graphml")) == sorted_batch(batch)
        assert not store.connection.execute("PRAGMA foreign_key_check").fetchall()
    # Reopen to prove persistence and source-backed retrieval, not in-memory results.
    with KnowledgeStore(db_path) as store:
        matches = store.search(task_type="binary_classification", entity_type="Algorithm")
        assert len(matches) == 3
        assert store.search(task_type="regression") == []
        write_json(out / "retrieval.json", matches)
    write_json(
        out / "provider-audit.json",
        {
            "first_import": first,
            "repeat_import": second,
            "note": "Fixed Mock fixtures; not a live LLM call.",
        },
    )
    suite = ET.parse(out / "tests.xml").getroot().find("testsuite")
    test_summary = {
        key: int(suite.attrib[key]) for key in ("tests", "failures", "errors", "skipped")
    }
    code_files = sorted(
        [
            *ROOT.glob("src/**/*.py"),
            *ROOT.glob("src/**/*.json"),
            *ROOT.glob("tests/**/*.py"),
            *ROOT.glob("scripts/*.py"),
            ROOT / "pyproject.toml",
            ROOT / "uv.lock",
            ROOT / "requirements.txt",
            ROOT / "requirements-dev.txt",
            path,
        ]
    )
    code_hashes = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code_files
    }
    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain", "--", *code_hashes], cwd=ROOT, text=True
        ).strip()
    )
    artifacts = [
        "knowledge.json",
        "knowledge.graphml",
        "knowledge.sqlite",
        "retrieval.json",
        "provider-audit.json",
        "tests.xml",
        *[item["log"] for item in command_records],
    ]
    report = {
        "phase": 1,
        "status": "verified",
        "scope": "knowledge_foundation_and_provider_contracts",
        "timestamp": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "architecture": platform.machine(),
            "platform": platform.platform(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in ("pydantic", "networkx", "pytest", "ruff")
            },
        },
        "git": {
            "base_commit": git_head,
            "implementation_commit": None if dirty else git_head,
            "implementation_dirty": dirty,
        },
        "implementation_files_sha256": code_hashes,
        "tests": test_summary,
        "checks": command_records,
        "knowledge": {
            "sources": 1,
            "entities": 6,
            "relations": 7,
            "retrieved_algorithms": 3,
            "idempotent_import": True,
            "graphml_roundtrip": True,
            "persistent_reopen": True,
        },
        "live_api": {
            "status": "blocked",
            "reason": "No real endpoint/model/credentials/prices configured; local HTTP contract tests only.",
        },
        "algorithm_workflow": "not_implemented_phase2",
        "global_gates": "not_passed",
        "artifacts_sha256": {
            name: hashlib.sha256((out / name).read_bytes()).hexdigest() for name in artifacts
        },
    }
    write_json(report_path, report)
    print(
        json.dumps(
            {"status": "verified", "tests": test_summary, "report": str(report_path)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
