"""One durable job process. Locks survive browser reruns and release on process death."""

import fcntl
import os
import shutil
import signal
import sqlite3
import sys
import threading
import time
from pathlib import Path

from algofactory.cli import parser, run
from algofactory.datasets import write_json
from algofactory.web.service import Jobs, RunSettings, confined, read_json


def execute(root, identifier):
    jobs = Jobs(root)
    job = jobs.path(identifier)
    with (job / "job.lock").open("a") as lock, (jobs.directory / "active.lock").open("a") as active:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 1
        if read_json(job / "state.json")["status"] != "queued":
            return 1
        try:
            fcntl.flock(active, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            write_json(
                job / "state.json", {"status": "failed", "error_category": "another_job_running"}
            )
            return 1
        stopped = threading.Event()

        def watch_cancel():
            while not stopped.wait(0.25):
                if (job / "cancel.request").exists():
                    os.kill(os.getpid(), signal.SIGINT)
                    return

        try:
            settings = RunSettings.model_validate(read_json(job / "settings.json"))
            if (job / "cancel.request").exists():
                raise KeyboardInterrupt
            write_json(job / "state.json", {"status": "running", "started": time.time()})
            threading.Thread(target=watch_cancel, daemon=True).start()
            # Copy only the needed data. Protocol/data files cannot race across UI jobs.
            dataset = job / "dataset"
            source_data = confined(
                root,
                "runtime/"
                + ("banking77-data" if settings.task == "banking77" else "regression-data"),
            )
            if settings.task == "regression" and not source_data.exists():
                from algofactory.regression import generate_regression

                generate_regression(dataset)
            else:
                if not source_data.is_dir():
                    raise ValueError("dataset_not_prepared")
                shutil.copytree(source_data, dataset)
            if settings.experiences:
                source_db = confined(root, "examples/phase4/library.sqlite")
                with (
                    sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True) as src,
                    sqlite3.connect(job / "knowledge.sqlite") as dest,
                ):
                    src.backup(dest)
            arguments = [
                "--env-file",
                str(Path(root) / ".env"),
                "demo",
                "--task",
                settings.task,
                "--mode",
                settings.mode,
                "--dataset-dir",
                str(dataset),
                "--output-dir",
                str(job / "run"),
                "--db",
                str(job / "knowledge.sqlite"),
                "--llm-call-budget",
                str(settings.call_budget),
            ]
            if settings.compare:
                arguments += [
                    "--compare",
                    "--max-repairs",
                    str(settings.max_repairs),
                    "--attempt-budget",
                    str(2 * (settings.max_repairs + 1)),
                ]
            if settings.experiences:
                arguments += ["--experiences", "--reuse-knowledge"]
            if settings.validation_only:
                arguments += ["--validation-only"]
            if settings.request:
                arguments += ["--request", settings.request]
            result = run(parser().parse_args(arguments))
            write_json(
                job / "state.json",
                {
                    "status": result["status"],
                    "error_category": result.get("error_category"),
                    "workflow_id": result.get("workflow_id"),
                    "finished": time.time(),
                },
            )
            return 0 if result["status"] in {"accepted", "validated"} else 1
        except KeyboardInterrupt:
            write_json(job / "state.json", {"status": "stopped", "error_category": "cancelled"})
            return 1
        except Exception as exc:
            # Never write raw provider exceptions, request text or local credentials to a web log.
            write_json(
                job / "state.json",
                {
                    "status": "failed",
                    "error_category": getattr(exc, "category", type(exc).__name__),
                },
            )
            return 1
        finally:
            stopped.set()


if __name__ == "__main__":
    raise SystemExit(execute(Path(sys.argv[1]).resolve(), sys.argv[2]))
