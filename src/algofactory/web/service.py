"""Durable local jobs and read-only evidence browsing; no shell or uploaded code."""

import fcntl
import json
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from algofactory.datasets import write_json
from algofactory.schemas.contracts import Contract
from algofactory.tasks import PROFILES


class RunSettings(Contract):
    task: Literal["banking77", "regression"] = "banking77"
    mode: Literal["mock", "api"] = "mock"
    compare: bool = True
    validation_only: bool = True
    experiences: bool = False
    max_repairs: int = Field(default=1, ge=0, le=2)
    call_budget: int = Field(default=24, ge=1, le=32)
    request: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def supported(self):
        if self.task == "regression" and (self.compare or self.experiences):
            raise ValueError("regression_single_candidate_only")
        if self.experiences and not self.compare:
            raise ValueError("experience_search_required")
        if self.mode == "api" and self.call_budget > 12:
            raise ValueError("web_api_budget_maximum_12")
        if self.mode == "mock" and self.request not in {"", PROFILES[self.task].request}:
            raise ValueError("mock_uses_fixed_request")
        return self


def confined(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("path_outside_workspace")
    return path


def read_json(path):
    if path.stat().st_size > 10_000_000:
        raise ValueError("evidence_too_large")
    return json.loads(path.read_text())


class Jobs:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = confined(self.root, "runtime/web-jobs")
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, identifier):
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("invalid_job_id")
        return confined(self.directory, identifier)

    def submit(self, settings, identifier):
        settings = RunSettings.model_validate(settings.model_dump())
        job = self.path(identifier)
        try:
            job.mkdir()
        except FileExistsError:
            if read_json(job / "settings.json") != settings.model_dump(mode="json"):
                raise ValueError("job_id_conflict") from None
            return identifier  # Idempotency across browser reruns; never duplicate API calls.
        write_json(job / "settings.json", settings.model_dump(mode="json"))
        write_json(job / "state.json", {"status": "queued", "created": time.time()})
        try:
            with (job / "runner.log").open("wb") as output:
                subprocess.Popen(
                    [sys.executable, "-m", "algofactory.web.runner", str(self.root), identifier],
                    cwd=self.root,
                    stdout=output,
                    stderr=output,
                    start_new_session=True,
                )
        except OSError:
            write_json(
                job / "state.json", {"status": "failed", "error_category": "job_launch_failed"}
            )
        return identifier

    def state(self, identifier):
        job = self.path(identifier)
        state = read_json(job / "state.json")
        if state["status"] in {"running", "queued"}:
            with (job / "job.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return state
                if state["status"] == "running" or time.time() - state.get("created", 0) > 30:
                    # A dead worker has released its lock. Preserve outputs and never replay a test.
                    report_path = job / "run/report.json"
                    state = (
                        {"status": read_json(report_path)["status"], "recovered_from_report": True}
                        if report_path.exists()
                        else {"status": "interrupted", "error_category": "worker_interrupted"}
                    )
                    write_json(job / "state.json", state)
        return state

    def cancel(self, identifier):
        if self.state(identifier)["status"] in {"running", "queued"}:
            (self.path(identifier) / "cancel.request").touch()

    def list(self):
        return sorted(
            (
                p.name
                for p in self.directory.iterdir()
                if p.is_dir()
                and re.fullmatch(r"[a-f0-9]{32}", p.name)
                and (p / "state.json").is_file()
            ),
            reverse=True,
        )


def report_catalog(root):
    root = Path(root)
    paths = [
        root / p
        for p in (
            "examples/api-phase3/comparison",
            "examples/phase4/api-2-on",
            "examples/phase3/repair",
            "examples/phase3/unsafe-code",
        )
    ]
    jobs = Jobs(root)
    paths += [jobs.path(i) / "run" for i in jobs.list()]
    return [
        str(p.relative_to(root))
        for p in paths
        if (p / "report.json").is_file() and p.resolve().is_relative_to(root.resolve())
    ]


def artifacts(root, relative):
    if relative not in report_catalog(root):
        raise ValueError("unknown_report")
    directory = confined(root, relative)
    allowed = {
        "report.json",
        "report.md",
        "candidate.py",
        "trace.json",
        "decisions.json",
        "ranking.json",
        "experience-use.json",
        "provider-usage.json",
        "selection.json",
        "protocol.json",
    }
    return {
        p.name: p
        for p in directory.iterdir()
        if p.name in allowed and p.is_file() and p.resolve().is_relative_to(directory)
    }


def graph_snapshot(path):
    # Opening an archive must not migrate its schema or mutate historical evidence.
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        return {
            table: [
                json.loads(row[0])
                for row in connection.execute(f"SELECT payload FROM {table} ORDER BY id")
            ]
            for table in ("entities", "relations", "sources")
        }


def graph_view(snapshot, focus):
    entities = {e["id"]: e for e in snapshot["entities"]}
    if focus not in entities:
        raise ValueError("unknown_graph_entity")
    edges = [e for e in snapshot["relations"] if focus in {e["head_id"], e["tail_id"]}][:40]
    ids = {focus} | {e[k] for e in edges for k in ("head_id", "tail_id")}
    lines = ['digraph { rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#e9f2f7"];']
    for identifier in sorted(ids):
        entity = entities[identifier]
        label = entity["type"] + "\n" + entity["name"][:45]
        if entity["type"] == "ValidationRun":
            label += "\n" + entity["result"]["status"]
        if entity["type"] == "Implementation":
            label += "\nversion " + str(entity["version"])
        lines.append(f"{json.dumps(identifier)} [label={json.dumps(label, ensure_ascii=False)}];")
    for edge in edges:
        lines.append(
            f"{json.dumps(edge['head_id'])} -> {json.dumps(edge['tail_id'])} [label={json.dumps(edge['type'])}];"
        )
    return "\n".join([*lines, "}"]), entities[focus]
