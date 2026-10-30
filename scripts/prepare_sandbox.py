"""Build an approved dependency image from a minimal context, without any project secrets."""

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from algofactory.datasets import sha256_file, write_json
from algofactory.execution.docker import docker_env, docker_ready, locate_docker

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-image",
        default="python:3.11-slim",
        help="Use the recorded python@sha256 digest to reproduce the base image",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Rebuild dependency layers for cold-start verification",
    )
    args = parser.parse_args()
    binary = locate_docker()
    environment = docker_ready(binary)
    subprocess.run(
        [binary, "pull", args.base_image], check=True, timeout=900, env=docker_env(binary)
    )
    base = json.loads(
        subprocess.check_output(
            [binary, "image", "inspect", args.base_image], text=True, env=docker_env(binary)
        )
    )[0]
    base_digest = base["RepoDigests"][0]
    worker = ROOT / "src/algofactory/execution/worker.py"
    requirements = ROOT / "requirements.txt"
    worker_hash, requirements_hash = sha256_file(worker), sha256_file(requirements)
    with tempfile.TemporaryDirectory(prefix="algofactory-build-") as temporary:
        context = Path(temporary)
        shutil.copy2(worker, context / "worker.py")
        shutil.copy2(requirements, context / "requirements.txt")
        shutil.copy2(ROOT / "docker/Dockerfile", context / "Dockerfile")
        subprocess.run(
            [
                binary,
                "build",
                *(["--no-cache"] if args.no_cache else []),
                "--tag",
                "algofactory-sandbox:phase2",
                "--build-arg",
                "BASE_IMAGE=python:3.11-slim@" + base_digest.split("@", 1)[1],
                "--build-arg",
                "WORKER_SHA256=" + worker_hash,
                "--build-arg",
                "REQUIREMENTS_SHA256=" + requirements_hash,
                str(context),
            ],
            check=True,
            timeout=1200,
            env=docker_env(binary),
        )
    image = json.loads(
        subprocess.check_output(
            [binary, "image", "inspect", "algofactory-sandbox:phase2"],
            text=True,
            env=docker_env(binary),
        )
    )[0]
    versions = json.loads(
        subprocess.check_output(
            [
                binary,
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--user=65534:65534",
                "--memory=256m",
                "--pids-limit=128",
                image["Id"],
                "python",
                "-I",
                "-c",
                "import importlib.metadata,json,platform; "
                "print(json.dumps({'python':platform.python_version(),'machine':platform.machine(),"
                "'packages':{n:importlib.metadata.version(n) for n in "
                "['numpy','pandas','scikit-learn','pydantic','networkx']}}))",
            ],
            text=True,
            env=docker_env(binary),
            timeout=30,
        )
    )
    approval = {
        "schema_version": 1,
        "image_id": image["Id"],
        "base_image_digest": base_digest,
        "worker_sha256": worker_hash,
        "requirements_sha256": requirements_hash,
        "environment": environment,
        "container_environment": versions,
    }
    write_json(ROOT / "runtime/docker-image.json", approval)
    print(json.dumps(approval, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
