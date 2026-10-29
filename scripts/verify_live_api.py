#!/usr/bin/env python3
"""Opt-in live smoke + one BANKING77 candidate; at most five calls, no retries."""

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from algofactory.datasets import sha256_file, verify_dataset, write_json
from algofactory.execution.docker import DockerExecutor
from algofactory.llm.providers import APIConfig, APIProvider, ProviderError, ProviderRequest
from algofactory.orchestrator import run_workflow
from algofactory.schemas.contracts import Contract
from algofactory.tasks import BANKING77

ROOT = Path(__file__).resolve().parents[1]


class SmokeReply(Contract):
    status: Literal["ok"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, default=ROOT / "runtime/banking77-data")
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    summary = {
        "status": "failed",
        "error_category": None,
        "started_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "request_limit": 5,
        "automatic_retries": 0,
        "candidate_limit": 1,
        "code_sha256": {
            str(p.relative_to(ROOT)): sha256_file(p) for p in sorted((ROOT / "src").rglob("*.py"))
        },
    }
    summary["code_sha256"]["scripts/verify_live_api.py"] = sha256_file(Path(__file__))
    summary["git_commit"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    summary["implementation_dirty"] = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain", "--", *summary["code_sha256"]], cwd=ROOT, text=True
        ).strip()
    )
    provider = None
    try:
        config = APIConfig.from_env(args.env_file)
        # Validate local prerequisites before spending any tokens.
        manifest = verify_dataset(args.dataset_dir)
        if manifest.get("task_profile") != "banking77":
            raise ValueError("BANKING77 dataset required")
        DockerExecutor(ROOT / "runtime/docker-image.json", ROOT / "requirements.txt")
        # One shared reservation budget spans smoke and workflow when configured.
        provider = APIProvider(
            config.model_copy(
                update={
                    "max_calls": min(config.max_calls, 4) + 1,
                    "max_retries": 0,
                    "max_output_tokens": min(config.max_output_tokens, 256),
                }
            )
        )
        provider.complete(
            ProviderRequest(
                role="builder",
                operation="connection_check",
                instruction="Return JSON with status equal to ok.",
                source={},
            ),
            SmokeReply,
        )
        summary["smoke_status"] = "passed"
        write_json(out / "smoke-audit.json", [a.model_dump(mode="json") for a in provider.audit])
        provider.config = provider.config.model_copy(
            update={
                "max_output_tokens": min(config.max_output_tokens, 8192),
            }
        )
        report = run_workflow(
            directory=out / "single-candidate",
            dataset_dir=args.dataset_dir.resolve(),
            db_path=out / "knowledge.sqlite",
            approval_path=ROOT / "runtime/docker-image.json",
            requirements_path=ROOT / "requirements.txt",
            knowledge_document=ROOT / "data/banking77.txt",
            request=BANKING77.request,
            provider=provider,
        )
        summary.update(
            status=report["status"],
            error_category=report["error_category"],
            validation_metrics=report.get("validation", {}).get("validation_metrics", {}),
            test_metrics=report.get("validation", {}).get("test_metrics", {}),
            test_attempted=report["test_attempted"],
            persisted=report["persisted"],
        )
    except (ProviderError, OSError, ValueError, RuntimeError) as exc:
        summary["error_category"] = getattr(exc, "category", type(exc).__name__)
    finally:
        if provider is not None:
            summary["usage"] = provider.usage_summary()
            write_json(
                out / "provider-audit.json", [a.model_dump(mode="json") for a in provider.audit]
            )
        summary["finished_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
        write_json(out / "verification.json", summary)
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "code_sha256"}, ensure_ascii=False, indent=2
        )
    )
    return 0 if summary["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
