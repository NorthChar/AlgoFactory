"""Durable local jobs and read-only evidence browsing; no shell or uploaded code."""

import fcntl
import hashlib
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
from algofactory.experiments import ExperimentConfig
from algofactory.requirement_understanding import Understanding
from algofactory.schemas.contracts import Contract
from algofactory.tasks import PROFILES

WEB_API_CALL_LIMIT = 24


def generation_budget(compare: bool, max_repairs: int, task: str = "banking77"):
    """Reserve for all configured attempts, without assuming a knowledge-cache hit.

    The first attempt costs four calls; subsequent candidates and repairs cost
    three with within-run knowledge caching. Transport retries are additional.
    """
    candidates = 2 if compare and task == "banking77" else 1
    base = 1 + 3 * candidates
    repairs = 3 * candidates * max_repairs if task == "banking77" else 0
    return base, repairs


class RunSettings(Contract):
    understanding: Understanding | None = None
    requirement_confirmation: str | None = None
    experiment: ExperimentConfig | None = None
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
        if self.understanding:
            if self.task != "banking77" or self.understanding.request != self.request:
                raise ValueError("understanding_request_mismatch")
            if (
                self.understanding.problems()
                or self.understanding.proposal.configuration != self.experiment
            ):
                raise ValueError("understanding_not_ready_or_configuration_mismatch")
            self.understanding.execution_request()
            if self.requirement_confirmation != self.confirmation_digest():
                raise ValueError("understanding_needs_current_confirmation")
        if self.experiment:
            if self.task != "banking77":
                raise ValueError("experiment_requires_banking77")
            self.experiment.validate_request(self.execution_request())
            if self.compare != (len(self.experiment.algorithms) == 2):
                raise ValueError("experiment_comparison_mismatch")
        if self.task == "regression" and (self.compare or self.experiences):
            raise ValueError("regression_single_candidate_only")
        if self.experiences and self.experiment and self.experiment.goal != "full":
            raise ValueError("derived_task_experience_reuse_not_validated")
        if self.experiences and not (self.compare or self.experiment):
            raise ValueError("experience_search_required")
        if self.mode == "api" and self.call_budget > WEB_API_CALL_LIMIT:
            raise ValueError(f"web_api_budget_maximum_{WEB_API_CALL_LIMIT}")
        if self.task == "banking77" and self.request not in {"", PROFILES[self.task].request}:
            if self.experiment is None:
                raise ValueError("requirement_needs_bound_configuration")
            if self.requirement_confirmation != self.confirmation_digest():
                raise ValueError("requirement_needs_current_confirmation")
        elif self.mode == "mock" and self.request not in {"", PROFILES[self.task].request}:
            raise ValueError("mock_uses_fixed_request")
        if (
            self.requirement_confirmation is not None
            and self.requirement_confirmation != self.confirmation_digest()
        ):
            raise ValueError("requirement_confirmation_stale")
        return self

    def execution_request(self):
        return self.understanding.execution_request() if self.understanding else self.request

    def confirmation_digest(self):
        from algofactory.knowledge.store import canonical

        return hashlib.sha256(
            canonical(self.model_dump(mode="json", exclude={"requirement_confirmation"})).encode()
        ).hexdigest()


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
        if settings.requirement_confirmation:
            from algofactory.requirements import interpret_requirement

            parsed = (
                interpret_requirement(settings.request) if settings.task == "banking77" else None
            )
            write_json(
                job / "confirmed-requirement.json",
                {
                    "original_request": settings.request,
                    "execution_request": settings.execution_request(),
                    "understanding": settings.understanding.model_dump(mode="json")
                    if settings.understanding
                    else None,
                    "configuration": settings.experiment.model_dump(mode="json")
                    if settings.experiment
                    else None,
                    "explicit_fields": {
                        field: getattr(settings.experiment, field)
                        for assessment in settings.understanding.proposal.assessments
                        if assessment.disposition == "supported"
                        for field in assessment.fields
                    }
                    if settings.understanding
                    else parsed.explicit
                    if parsed
                    else {},
                    "settings_digest": settings.requirement_confirmation,
                    "interpreter": "llm-reviewed-v1"
                    if settings.understanding
                    else "controlled-language-v1"
                    if parsed
                    else "fixed-regression",
                },
            )
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
            "examples/banking-classification/comparison",
            "examples/experience-reuse/run",
            "examples/mock-repair",
            "examples/rejected-code",
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
        "validation-class-details.json",
        "data-manifest.json",
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
