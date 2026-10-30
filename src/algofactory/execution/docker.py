"""Construct and run a fixed Docker sandbox; mount only a fresh, minimal input directory."""

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from algofactory.datasets import sha256_file, write_json
from algofactory.generation.safety import check_code
from algofactory.schemas.contracts import ExecutionBudget
from algofactory.workflow_models import WorkerResult, WorkflowFailure


def locate_docker() -> str:
    path = shutil.which("docker")
    if path:
        return path
    for candidate in (
        Path("/Applications/Docker.app/Contents/Resources/bin/docker"),
        Path.home() / ".docker/bin/docker",
    ):
        if candidate.is_file():
            return str(candidate)
    raise WorkflowFailure("docker_missing")


def docker_env(binary: str) -> dict[str, str]:
    """Expose bundled credential helpers without changing the user's shell settings."""
    environment = os.environ.copy()
    environment["PATH"] = (
        str(Path(binary).resolve().parent) + os.pathsep + environment.get("PATH", "")
    )
    return environment


def docker_ready(binary: str) -> dict:
    try:
        result = subprocess.run(
            [binary, "info", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=20,
            env=docker_env(binary),
            check=False,
        )
        if result.returncode:
            raise WorkflowFailure("docker_unavailable")
        info = json.loads(result.stdout)
        if info["OSType"] != "linux":
            raise WorkflowFailure("linux_container_engine_required")
        return {
            "server_version": info["ServerVersion"],
            "architecture": info["Architecture"],
            "os_type": info["OSType"],
        }
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        raise WorkflowFailure("docker_unavailable") from None


def create_command(
    binary: str, image_id: str, name: str, input_dir: Path, budget: ExecutionBudget
) -> list[str]:
    if not image_id.startswith("sha256:") or len(image_id) != 71:
        raise WorkflowFailure("immutable_image_id_required")
    if "," in str(input_dir):
        raise WorkflowFailure("unsupported_mount_path")
    return [
        binary,
        "create",
        "--name",
        name,
        "--pull=never",
        "--network=none",
        "--read-only",
        "--user=65534:65534",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=128",
        f"--cpus={budget.cpus}",
        f"--memory={budget.memory_mib}m",
        f"--memory-swap={budget.memory_mib}m",
        "--ulimit=nofile=256:256",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=256m,mode=1777",
        "--workdir=/tmp",
        "--env=ALGOFACTORY_SANDBOX=1",
        "--env=OMP_NUM_THREADS=1",
        "--env=OPENBLAS_NUM_THREADS=1",
        "--env=MKL_NUM_THREADS=1",
        "--env=PYTHONDONTWRITEBYTECODE=1",
        "--env=PYTHONHASHSEED=42",
        "--mount",
        f"type=bind,src={input_dir.resolve()},dst=/input,readonly",
        image_id,
        "python",
        "-I",
        "/opt/algofactory/worker.py",
    ]


class DockerExecutor:
    def __init__(self, approval_path: Path, requirements_path: Path):
        self.binary = locate_docker()
        self.environment = docker_ready(self.binary)
        if not approval_path.is_file():
            raise WorkflowFailure("sandbox_image_not_prepared")
        approval = json.loads(approval_path.read_text())
        if approval["worker_sha256"] != sha256_file(
            Path(__file__).with_name("worker.py")
        ) or approval["requirements_sha256"] != sha256_file(requirements_path):
            raise WorkflowFailure("sandbox_image_stale")
        try:
            result = subprocess.run(
                [self.binary, "image", "inspect", approval["image_id"]],
                capture_output=True,
                text=True,
                timeout=20,
                env=docker_env(self.binary),
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise WorkflowFailure("sandbox_image_inspection_timeout") from None
        if result.returncode:
            raise WorkflowFailure("sandbox_image_missing")
        inspected = json.loads(result.stdout)[0]
        labels = inspected["Config"].get("Labels") or {}
        if (
            inspected["Id"] != approval["image_id"]
            or labels.get("org.algofactory.worker-sha256") != approval["worker_sha256"]
            or labels.get("org.algofactory.requirements-sha256") != approval["requirements_sha256"]
        ):
            raise WorkflowFailure("sandbox_image_approval_mismatch")
        self.approval = approval

    def execute(
        self,
        code_path: Path,
        train_path: Path | None,
        features_path: Path,
        config: dict,
        stage_dir: Path,
        budget: ExecutionBudget,
        model_path: Path | None = None,
    ) -> WorkerResult:
        check_code(code_path.read_text())
        stage_dir.mkdir(parents=True, exist_ok=False)
        name = "algofactory-" + uuid.uuid4().hex
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="input-", dir=stage_dir) as temporary:
            inputs = Path(temporary)
            inputs.chmod(0o755)
            shutil.copyfile(code_path, inputs / "candidate.py")
            if train_path is not None:
                shutil.copyfile(train_path, inputs / "train.csv")
            if model_path is not None:
                shutil.copyfile(model_path, inputs / "model.pkl.gz")
            shutil.copyfile(features_path, inputs / "evaluation_features.csv")
            write_json(inputs / "config.json", config)
            for path in inputs.iterdir():
                path.chmod(0o444)
            command = create_command(self.binary, self.approval["image_id"], name, inputs, budget)
            write_json(
                stage_dir / "execution.json",
                {
                    "command": command,
                    "input_files": sorted(p.name for p in inputs.iterdir()),
                    "image_id": self.approval["image_id"],
                    "stage": config["stage"],
                    "environment": self.environment,
                },
            )
            container_created = False
            try:
                created = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    env=docker_env(self.binary),
                    check=False,
                )
                if created.returncode:
                    raise WorkflowFailure("container_creation_failed")
                container_created = True
                run = subprocess.run(
                    [self.binary, "start", "--attach", name],
                    capture_output=True,
                    text=True,
                    timeout=budget.timeout_seconds,
                    env=docker_env(self.binary),
                    check=False,
                )
                (stage_dir / "stderr.log").write_text(run.stderr[:65536])
                inspect = subprocess.run(
                    [self.binary, "inspect", "--format", "{{json .State}}", name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=docker_env(self.binary),
                    check=False,
                )
                state = json.loads(inspect.stdout) if inspect.returncode == 0 else {}
                write_json(stage_dir / "container-state.json", state)
                if state.get("OOMKilled"):
                    raise WorkflowFailure("resource_limit_exceeded")
                if run.returncode:
                    raise WorkflowFailure("container_nonzero_exit")
                if len(run.stdout.encode()) > 32_000_000:
                    raise WorkflowFailure("worker_output_too_large")
                try:
                    payload = json.loads(run.stdout)
                    model_payload = payload.pop("model_payload", None)
                    worker = WorkerResult.model_validate(payload)
                    if model_payload is not None:
                        if (
                            not (config.get("persist_model") or config["stage"] == "prepare")
                            or worker.status != "ok"
                        ):
                            raise ValueError("unexpected_model_artifact")
                        model_bytes = base64.b64decode(model_payload, validate=True)
                        if len(model_bytes) > 24_000_000:
                            raise ValueError("model_too_large")
                        (stage_dir / "model.pkl.gz").write_bytes(model_bytes)
                        write_json(
                            stage_dir / "model-provenance.json",
                            {
                                "schema_version": 1,
                                "model_sha256": sha256_file(stage_dir / "model.pkl.gz"),
                                "code_hash": sha256_file(code_path),
                                "train_sha256": sha256_file(train_path),
                                "config": config,
                                "image_id": self.approval["image_id"],
                                "environment": worker.model_environment,
                                "classes": worker.classes,
                                "training_rows": worker.training_rows,
                            },
                        )
                except ValueError:
                    raise WorkflowFailure("invalid_worker_response") from None
                write_json(stage_dir / "predictions.json", worker.model_dump(mode="json"))
                return worker
            except subprocess.TimeoutExpired:
                raise WorkflowFailure("execution_timeout") from None
            finally:
                try:
                    cleanup = subprocess.run(
                        [self.binary, "rm", "--force", name],
                        capture_output=True,
                        text=True,
                        timeout=15,
                        env=docker_env(self.binary),
                        check=False,
                    )
                    cleanup_code = cleanup.returncode
                except (OSError, subprocess.TimeoutExpired):
                    cleanup_code = -1
                write_json(
                    stage_dir / "cleanup.json",
                    {
                        "container": name,
                        "exit_code": cleanup_code,
                        "elapsed_seconds": time.monotonic() - started,
                    },
                )
                if cleanup_code and container_created:
                    raise WorkflowFailure("container_cleanup_failed")
