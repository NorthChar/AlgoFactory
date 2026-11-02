"""Verify committed source in a fresh venv and independent checkout.

Reuses the approved Docker image and package caches; not a second-machine/cold-cache claim.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from algofactory.datasets import sha256_file, write_json

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    checkout = out / "checkout"
    summary = {
        "status": "in_progress",
        "paid_api_calls": 0,
        "checks": [],
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "scope": "same host, independent clone, fresh venv and noneditable wheel; dependency caches and approved Docker image reused",
    }
    expected_version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("ALGOFACTORY_", "PYTHON", "UV_")) and k != "VIRTUAL_ENV"
    }
    env["PYTHONNOUSERSITE"] = "1"
    uv = shutil.which("uv")

    def command(args, cwd=checkout):
        log = out / f"check-{len(summary['checks']) + 1}.log"
        with log.open("w") as stream:
            result = subprocess.run(
                [str(a) for a in args],
                cwd=cwd,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=1200,
            )
        summary["checks"].append(
            {"command": [str(a) for a in args], "exit_code": result.returncode, "log": log.name}
        )
        write_json(out / "verification.json", summary)
        if result.returncode:
            raise RuntimeError("reproduction_check_failed:" + log.name)
        return log.read_text()

    try:
        assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip()
        command(["git", "clone", "--depth", "1", "--quiet", ROOT.as_uri(), checkout], cwd=ROOT)
        python = out / "environment/bin/python"
        command([uv, "venv", python.parent.parent, "--python", sys.executable])
        command([uv, "pip", "sync", "--python", python, "--require-hashes", "requirements-dev.txt"])
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
                checkout,
            ]
        )
        (wheel,) = (out / "dist").glob("*.whl")
        command([uv, "pip", "install", "--python", python, "--no-deps", wheel])
        origin = json.loads(
            command(
                [
                    python,
                    "-I",
                    "-c",
                    "import algofactory,json;print(json.dumps({'module':algofactory.__file__,'version':algofactory.__version__}))",
                ]
            )
        )
        assert (
            Path(origin["module"]).is_relative_to(python.parent.parent)
            and origin["version"] == expected_version
        )
        summary["installation"] = origin
        summary["wheel_sha256"] = sha256_file(wheel)
        assert not (checkout / ".env").exists()
        (checkout / "runtime").mkdir()
        shutil.copy2(ROOT / "runtime/docker-image.json", checkout / "runtime/docker-image.json")
        command(
            [
                python,
                "-m",
                "algofactory.cli",
                "prepare-banking77",
                "--raw-dir",
                "data/banking77/raw",
            ]
        )
        env["ALGOFACTORY_DOCKER_TESTS"] = "1"
        command([python, "-m", "pytest", "-q", "--junitxml=" + str(out / "tests.xml")])
        command([python, "scripts/verify_intent_goals.py", "--output-dir", out / "acceptance"])
        command([python, "scripts/verify_requirements.py", "--output-dir", out / "requirements"])
        import xml.etree.ElementTree as ET

        suite = ET.parse(out / "tests.xml").getroot().find("testsuite")
        summary["tests"] = {
            k: int(suite.attrib[k]) for k in ("tests", "failures", "errors", "skipped")
        }
        assert all(summary["tests"][k] == 0 for k in ("failures", "errors", "skipped"))
        assert read_json(out / "acceptance/verification.json")["status"] == "passed"
        assert read_json(out / "requirements/verification.json")["status"] == "passed"
        summary["status"] = "passed"
    except BaseException as exc:
        summary.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        write_json(out / "verification.json", summary)
    print(json.dumps({"status": summary["status"], "report": str(out / "verification.json")}))


def read_json(path):
    return json.loads(path.read_text())


if __name__ == "__main__":
    main()
