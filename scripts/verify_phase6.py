#!/usr/bin/env python3
"""Clean local clone, fresh hash-locked environment, wheel and no-cache Docker rebuild."""

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from algofactory.datasets import sha256_file, write_json

ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    snapshot = out / "checkout"
    evidence = out / "evidence"
    evidence.mkdir()
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("uv is required")
    summary = {
        "phase": 6,
        "status": "in_progress",
        "started_at": now(),
        "paid_api_calls": 0,
        "live_api": "prior_phase3_and_phase4_evidence_only",
        "checks": [],
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "command": [sys.executable, *sys.argv],
    }
    report_path = evidence / "verification.json"
    write_json(report_path, summary)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("ALGOFACTORY_", "UV_", "PYTHON")) and k != "VIRTUAL_ENV"
    }
    env.update(PYTHONNOUSERSITE="1", PIP_DISABLE_PIP_VERSION_CHECK="1")

    def command(arguments, *, cwd=snapshot, timeout=1200):
        log = f"check-{len(summary['checks']) + 1}.log"
        with (evidence / log).open("w") as stream:
            result = subprocess.run(
                list(map(str, arguments)),
                cwd=cwd,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
            )
        summary["checks"].append(
            {
                "command": list(map(str, arguments)),
                "cwd": str(cwd),
                "exit_code": result.returncode,
                "log": log,
            }
        )
        write_json(report_path, summary)
        if result.returncode:
            raise RuntimeError("Check failed: " + log)
        return (evidence / log).read_text()

    try:
        assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip(), (
            "Commit all delivery inputs before cold verification"
        )
        command(["git", "clone", "--no-local", "--quiet", ROOT, snapshot], cwd=ROOT)
        command(["git", "remote", "remove", "origin"])
        assert (
            not (snapshot / "runtime").exists()
            and not (snapshot / ".venv").exists()
            and not (snapshot / ".env").exists()
        )
        command([uv, "--version"])
        python = out / "environment/bin/python"
        command([uv, "venv", python.parent.parent, "--python", sys.executable])
        command(
            [
                uv,
                "pip",
                "sync",
                "--python",
                python,
                "--require-hashes",
                "--no-cache",
                snapshot / "requirements-dev.txt",
            ]
        )
        command(
            [
                uv,
                "build",
                "--wheel",
                "--no-build-isolation",
                "--python",
                python,
                "--out-dir",
                out / "dist",
                snapshot,
            ]
        )
        (wheel,) = (out / "dist").glob("*.whl")
        command([uv, "pip", "install", "--python", python, "--no-deps", "--no-cache", wheel])
        origin = json.loads(
            command(
                [
                    python,
                    "-I",
                    "-c",
                    "import algofactory,importlib.metadata,json,sys; d=importlib.metadata.distribution('algofactory'); print(json.dumps({'module':algofactory.__file__,'prefix':sys.prefix,'version':d.version,'direct_url':json.loads(d.read_text('direct_url.json')),'packages':{x.metadata['Name']:x.version for x in importlib.metadata.distributions()}}))",
                ]
            )
        )
        assert (
            Path(origin["module"]).is_relative_to(python.parent.parent)
            and "site-packages" in origin["module"]
        )
        assert not origin["direct_url"].get("dir_info", {}).get("editable")
        write_json(evidence / "installation.json", origin)
        shutil.copy2(wheel, evidence / wheel.name)
        summary["wheel_sha256"] = sha256_file(wheel)
        command(
            [
                python,
                "scripts/audit_release.py",
                "--history",
                "--output",
                evidence / "release-audit.json",
            ]
        )
        # Base image fixed by the previous verified environment; Python/package layers are rebuilt.
        base = json.loads((snapshot / "examples/phase5/docker-image.json").read_text())[
            "base_image_digest"
        ]
        command([python, "scripts/prepare_sandbox.py", "--base-image", base, "--no-cache"])
        command(
            [
                python,
                "-m",
                "algofactory.cli",
                "prepare-banking77",
                "--raw-dir",
                "examples/phase25/banking77-data/raw",
                "--output-dir",
                "runtime/banking77-data",
            ]
        )
        # Reuse the full acceptance entrypoint: all tests + CLI/Web + graph + actual timeout.
        command([python, "scripts/verify_phase5.py", "--output-dir", "runtime/phase6-acceptance"])
        acceptance = json.loads(
            (snapshot / "runtime/phase6-acceptance/verification.json").read_text()
        )
        assert acceptance["status"] == "passed" and acceptance["tests"]["skipped"] == 0
        shutil.copytree(snapshot / "runtime/phase6-acceptance", evidence / "acceptance")
        summary["tests"] = acceptance["tests"]
        summary["cli_runs"] = acceptance["cli_runs"]
        summary["web_trials"] = acceptance["web_trials"]
        summary["code_sha256"] = acceptance["code_sha256"]
        # Exercise the installed Streamlit server, not just imports/AppTest.
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with (evidence / "web-server.log").open("w") as log:
            server = subprocess.Popen(
                [
                    str(python),
                    "-m",
                    "streamlit",
                    "run",
                    "src/algofactory/web/app.py",
                    "--server.address",
                    "127.0.0.1",
                    "--server.port",
                    str(port),
                    "--server.headless",
                    "true",
                    "--browser.gatherUsageStats",
                    "false",
                ],
                cwd=snapshot,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                deadline = time.monotonic() + 30
                healthy = False
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        break
                    try:
                        with urlopen(
                            f"http://127.0.0.1:{port}/_stcore/health", timeout=2
                        ) as response:
                            healthy = response.status == 200 and response.read().strip() == b"ok"
                        if healthy:
                            break
                    except OSError:
                        time.sleep(0.2)
                assert healthy, "installed_web_server_not_healthy"
                summary["installed_web_health"] = "passed"
            finally:
                server.terminate()
                server.wait(timeout=20)
        command([python, "-m", "algofactory.cli", "schemas", "--output-dir", evidence / "schemas"])
        # Keep the complete historical dataset bundle outside the Git evidence archive.
        # Individual source/evidence files remain versioned; the ZIP can exceed GitHub's limit.
        source_bundle = out / "dist/source.zip"
        command(["git", "archive", "--format=zip", f"--output={source_bundle}", "HEAD"])
        summary["source_bundle"] = {
            "path": str(source_bundle),
            "sha256": sha256_file(source_bundle),
            "bytes": source_bundle.stat().st_size,
            "recreate": "git archive --format=zip --output=source.zip " + summary["source_commit"],
            "distribution": "local download; not duplicated inside the Git evidence archive",
        }
        assert not subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=snapshot
        ).strip(), "Snapshot changed during verification"
        summary.update(
            status="passed",
            finished_at=now(),
            host={
                "platform": platform.platform(),
                "python": platform.python_version(),
                "machine": platform.machine(),
            },
            isolation={
                "checkout": "independent git clone; no runtime, .env or .venv copied",
                "python": "fresh venv; no-cache hash-locked install; non-editable wheel",
                "docker": "pinned base image; no-cache dependency build; runtime network disabled",
                "limitations": "same physical host, existing Python interpreter and Docker daemon/base image availability; not a second machine or offline first installation",
            },
            github={
                "target": "Northchar/AlgoFactory",
                "visibility_requested": "private",
                "status": "separate_publication_check_required",
            },
        )
        summary["artifacts_sha256"] = {
            str(p.relative_to(evidence)): sha256_file(p)
            for p in sorted(evidence.rglob("*"))
            if p.is_file() and p != report_path
        }
        write_json(report_path, summary)
        print(
            json.dumps({"status": "passed", "report": str(report_path), "tests": summary["tests"]})
        )
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        summary.update(
            status="failed", error_type=type(exc).__name__, error=str(exc), finished_at=now()
        )
        write_json(report_path, summary)
        print("FAILED: " + str(report_path), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
