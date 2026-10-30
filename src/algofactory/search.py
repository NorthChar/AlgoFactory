"""Bounded coordinator over the shared workflow; only its winner can enter final testing."""

import hashlib
import json
import shutil
import sqlite3
import uuid
from pathlib import Path

from algofactory.datasets import sha256_file, verify_dataset, write_json
from algofactory.execution.docker import DockerExecutor
from algofactory.experience import persist_execution
from algofactory.experience_reuse import synthesize_repair
from algofactory.knowledge.store import KnowledgeStore, canonical
from algofactory.orchestrator import Trace, run_workflow
from algofactory.planning import SearchPolicy, diagnose, rank_candidates
from algofactory.reporting import save_report
from algofactory.resume import validate_resume
from algofactory.schemas.contracts import (
    AgentDecision,
    AlgorithmPlan,
    Candidate,
    TaskSpec,
    ValidationResult,
)
from algofactory.schemas.knowledge import KnowledgeBatch, SourceDocument
from algofactory.tasks import BANKING77, profile_for
from algofactory.validation.final_test import evaluate_final
from algofactory.validation.protocol import calibrate
from algofactory.workflow_models import RepairContext, WorkflowFailure


class SearchStop(WorkflowFailure):
    pass


def run_search(
    *,
    directory: Path,
    dataset_dir: Path,
    db_path: Path,
    approval_path: Path,
    requirements_path: Path,
    knowledge_document: Path,
    request: str,
    provider,
    policy: SearchPolicy | None = None,
    resume_failures: dict[str, Path] | None = None,
    use_experiences: bool = False,
    learn_experiences: bool = False,
    validation_only: bool = False,
    reuse_knowledge: bool = False,
    experiment=None,
):
    policy = policy or SearchPolicy()
    if experiment is not None:
        experiment.validate_request(request)
        if policy.algorithms != experiment.algorithms or resume_failures or learn_experiences:
            raise ValueError("experiment_policy_or_resume_mismatch")
    if directory.exists() and any(directory.iterdir()):
        raise WorkflowFailure("run_directory_must_be_new")
    directory.mkdir(parents=True, exist_ok=True)
    workflow_id = "search:" + uuid.uuid4().hex
    trace = Trace(directory, workflow_id)
    report = {
        "workflow_id": workflow_id,
        "provider_mode": provider.mode,
        "task_profile": "banking77",
        "status": "failed",
        "persisted": False,
        "error_category": None,
        "test_attempted": False,
        "execution_evidence": [],
        "evaluation_scope": "comparison_validation_only"
        if validation_only
        else "comparison_and_final_test",
        "experience_enabled": use_experiences,
        "learned_experiences": [],
        "fault_fixture": getattr(provider, "fault", None),
        "attempts": [],
        "candidate_stops": [],
        "policy": policy.model_dump(mode="json"),
        "ranking": [],
    }
    if experiment is not None:
        report.update(
            experiment=experiment.frozen(),
            experiment_hash=experiment.digest,
            candidate_mode="comparison" if len(policy.algorithms) > 1 else "single",
        )
        write_json(
            directory / "experiment.json",
            {"configuration": experiment.frozen(), "experiment_hash": experiment.digest},
        )
    calls_at_start = provider.calls
    decisions = []
    knowledge_cache: set[str] = set()
    manifest = task = plan = selected = protocol = None

    def decision(action, reason, evidence):
        item = AgentDecision(
            decision_id=workflow_id + f":decision:{len(decisions)}",
            run_id=workflow_id,
            role="review",
            action=action,
            reason=reason,
            evidence_ids=evidence,
            budget_remaining=policy.attempt_budget - len(report["attempts"]),
        )
        decisions.append(item.model_dump(mode="json"))
        write_json(directory / "decisions.json", decisions)
        trace.add(action.lower(), reason)

    try:
        trace.add("received", "启动有界候选比较，所有候选与修复仅使用验证集")
        manifest = verify_dataset(dataset_dir)
        if profile_for(manifest) != BANKING77:
            raise WorkflowFailure("unsupported_search_task")
        protocol = calibrate(dataset_dir, dataset_dir / "protocol.json")
        with KnowledgeStore(db_path) as store:
            snapshot = store.snapshot()
        initial = KnowledgeBatch.model_validate(snapshot) if snapshot["entities"] else None
        experience_ids = (
            {e.id for e in initial.entities if e.type == "Experience"} if initial else set()
        )
        if reuse_knowledge:
            source = SourceDocument.from_text(
                knowledge_document.name, knowledge_document.read_text()
            )
            if (
                initial
                and source in initial.sources
                and any(
                    e.source_id == source.id and e.type == "Algorithm" for e in initial.entities
                )
            ):
                knowledge_cache.add(source.id)
        write_json(
            directory / "experience-library.json",
            {
                "eligible_ids": sorted(experience_ids),
                "enabled": use_experiences,
                "library_snapshot_hash": hashlib.sha256(canonical(snapshot).encode()).hexdigest(),
                "learned_during_search_not_consumed": True,
            },
        )
        resumed = {}
        for algorithm, origin in (resume_failures or {}).items():
            if algorithm not in policy.algorithms or policy.max_repairs < 1:
                raise WorkflowFailure("invalid_resume_policy")
            resumed[algorithm] = validate_resume(origin, db_path, algorithm, manifest, protocol)
            if resumed[algorithm]["provider_mode"] != provider.mode:
                raise WorkflowFailure("resume_provider_mismatch")
        report.update(
            thresholds=protocol["thresholds"],
            data_fingerprint=manifest["data_fingerprint"],
            split_id=manifest["split_id"],
            class_names=manifest["class_names"],
        )
        frozen = {
            "experiment_hash": report.get("experiment_hash"),
            "policy": policy.model_dump(mode="json"),
            "config_hash": protocol["config_hash"],
            "data_fingerprint": manifest["data_fingerprint"],
            "split_id": manifest["split_id"],
            "seed": manifest["seed"],
            "experience_enabled": use_experiences,
            "learn_experiences": learn_experiences,
            "validation_only": validation_only,
            "reuse_knowledge": reuse_knowledge,
        }
        report["search_config_hash"] = hashlib.sha256(canonical(frozen).encode()).hexdigest()
        write_json(
            directory / "search-config.json",
            frozen | {"search_config_hash": report["search_config_hash"]},
        )
        write_json(directory / "protocol.json", protocol)
        write_json(directory / "data-manifest.json", manifest)
        for algorithm in policy.algorithms:
            repair = None
            for attempt in range(policy.max_repairs + 1):
                if len(report["attempts"]) >= policy.attempt_budget:
                    raise SearchStop("attempt_budget_exhausted")
                if (
                    verify_dataset(dataset_dir) != manifest
                    or calibrate(dataset_dir, dataset_dir / "protocol.json") != protocol
                ):
                    raise WorkflowFailure("search_inputs_changed")
                attempt_dir = directory / "candidates" / algorithm / f"attempt-{attempt}"
                historical = attempt == 0 and algorithm in resumed
                decision(
                    "REPAIR"
                    if historical
                    else repair.diagnosis["action"]
                    if repair
                    else "GENERATE",
                    "恢复已核验的历史失败，保留原始执行证据"
                    if historical
                    else repair.diagnosis["reason"]
                    if repair
                    else "基于适用知识生成候选：" + algorithm,
                    [resumed[algorithm]["knowledge_ids"]["implementation_id"]]
                    if historical
                    else [repair.parent_id]
                    if repair
                    else [workflow_id],
                )
                if historical:
                    origin = resume_failures[algorithm]
                    shutil.copytree(origin, attempt_dir)
                    child = resumed[algorithm]
                    write_json(
                        attempt_dir / "resume-origin.json",
                        {
                            "directory": str(origin.resolve()),
                            "report_sha256": sha256_file(origin / "report.json"),
                            "workflow_id": child["workflow_id"],
                            "reexecuted": False,
                            "new_provider_calls": 0,
                        },
                    )
                else:
                    child = run_workflow(
                        directory=attempt_dir,
                        dataset_dir=dataset_dir,
                        db_path=db_path,
                        approval_path=approval_path,
                        requirements_path=requirements_path,
                        knowledge_document=knowledge_document,
                        request=request,
                        provider=provider,
                        validation_only=True,
                        algorithm=algorithm,
                        repair=repair,
                        repair_limit=policy.max_repairs,
                        knowledge_cache=knowledge_cache,
                        use_experiences=use_experiences,
                        experience_ids=experience_ids,
                        experiment=experiment,
                    )
                result = child.get("validation", {})
                entry = {
                    "algorithm": algorithm,
                    "experiment_hash": child.get("experiment_hash"),
                    "attempt": attempt,
                    "workflow_id": child["workflow_id"],
                    "status": child["status"],
                    "error_category": child["error_category"],
                    "report": str(attempt_dir / "report.json"),
                    "code_hash": child.get("code_hash"),
                    "implementation_id": child.get("knowledge_ids", {}).get("implementation_id"),
                    "validation_run_id": child.get("knowledge_ids", {}).get("validation_run_id"),
                    "parent_id": repair.parent_id if repair else None,
                    "validation_metrics": result.get("validation_metrics", {}),
                    "config_hash": result.get("config_hash"),
                    "split_id": result.get("split_id"),
                    "test_attempted": child["test_attempted"],
                    "historical_failure": historical,
                    "experience_usage": child.get("experience_usage"),
                }
                report["attempts"].append(entry)
                write_json(directory / "attempts.json", report["attempts"])
                if child["test_attempted"]:
                    raise WorkflowFailure("candidate_test_leakage")
                if not child["persisted"]:
                    raise WorkflowFailure("knowledge_writeback_failed")
                if child["status"] == "validated":
                    if learn_experiences and repair:
                        with KnowledgeStore(db_path) as store:
                            learned = synthesize_repair(
                                store,
                                attempt_dir.parent / f"attempt-{attempt - 1}",
                                attempt_dir,
                                algorithm,
                            )
                        report["learned_experiences"].append(learned)
                        write_json(
                            directory / "learned-experiences.json", report["learned_experiences"]
                        )
                    break
                diagnostic = diagnose(child)
                write_json(attempt_dir / "diagnosis.json", diagnostic)
                if child["status"] == "stopped":
                    raise SearchStop(child["error_category"] or "cancelled")
                if diagnostic["action"] == "STOP":
                    if child["error_category"] == "repair_unchanged_code":
                        report["candidate_stops"].append(
                            {
                                "algorithm": algorithm,
                                "reason": "unrepairable_no_change",
                                "attempt": attempt,
                            }
                        )
                        decision(
                            "STOP", "当前候选修复没有代码变化，停止该候选", [child["workflow_id"]]
                        )
                        break
                    if child["error_category"] in {
                        "call_budget_exhausted",
                        "cost_budget_exhausted",
                    }:
                        raise SearchStop(child["error_category"])
                    raise WorkflowFailure(child["error_category"] or "candidate_failed")
                if attempt == policy.max_repairs:
                    report["candidate_stops"].append(
                        {
                            "algorithm": algorithm,
                            "reason": "repair_budget_exhausted",
                            "attempt": attempt,
                        }
                    )
                    decision("STOP", "当前候选已用完修复次数", [child["workflow_id"]])
                    break
                if not entry["implementation_id"]:
                    raise WorkflowFailure("repair_parent_missing")
                previous_code = (attempt_dir / "candidate.py").read_text()
                repair = RepairContext(
                    parent_id=entry["implementation_id"],
                    attempt=attempt + 1,
                    previous_code=previous_code,
                    previous_code_hash=entry["code_hash"],
                    diagnosis=diagnostic,
                )
            if algorithm != policy.algorithms[-1]:
                decision(
                    "SWITCH",
                    "转到下一候选；比较使用同一冻结协议",
                    [report["attempts"][-1]["workflow_id"]],
                )
        ranked = rank_candidates(report["attempts"], policy, protocol)
        report["ranking"] = ranked
        write_json(
            directory / "ranking.json",
            {
                "rule": policy.ranking,
                "candidates": ranked,
                "candidate_stops": report["candidate_stops"],
            },
        )
        if not ranked:
            raise SearchStop("no_valid_candidate")
        selected = ranked[0]
        selected_dir = Path(selected["report"]).parent
        child = json.loads((selected_dir / "report.json").read_text())
        if sha256_file(selected_dir / "candidate.py") != selected["code_hash"]:
            raise WorkflowFailure("selected_code_changed")
        report.update(
            code_hash=selected["code_hash"],
            selected_implementation_id=selected["implementation_id"],
            selected_algorithm=selected["algorithm"],
            candidate=child["candidate"],
        )
        for name in (
            "candidate.py",
            "candidate.json",
            "task.json",
            "plan.json",
            "validation-class-details.json",
        ):
            shutil.copy2(selected_dir / name, directory / name)
        task = TaskSpec.model_validate_json((directory / "task.json").read_text())
        task.constraints.candidate_limit = len(policy.algorithms)
        task.constraints.max_repairs_per_candidate = policy.max_repairs
        write_json(directory / "task.json", task.model_dump(mode="json"))
        plan = AlgorithmPlan.model_validate_json((directory / "plan.json").read_text())
        candidate = Candidate.model_validate(child["candidate"])
        report["validation"] = child["validation"] | {
            "run_id": workflow_id + ":final",
            "report_paths": [str(directory / "report.json"), str(directory / "report.md")],
        }
        trace.context.update(
            candidate_id=selected["implementation_id"],
            code_hash=selected["code_hash"],
            config_hash=protocol["config_hash"],
        )
        trace.add("selected", "按验证集 Macro-F1、Accuracy、预设候选顺序选定版本；测试失败不换候选")
        if validation_only:
            report["status"] = "validated"
        else:
            config = BANKING77.intent() | {
                "seed": task.seed,
                "class_labels": task.class_labels,
                "stage": "test",
            }
            executor = DockerExecutor(approval_path, requirements_path)
            final, scores = evaluate_final(
                directory,
                dataset_dir,
                manifest,
                task,
                candidate,
                protocol,
                executor,
                config,
                report,
                selected["validation_metrics"],
            )
            report["validation"].update(test_metrics=scores["metrics"], final_test_evaluated=True)
            report["validation"]["resources"]["elapsed_seconds"] += final.elapsed_seconds
            report["validation"]["resources"]["peak_memory_mib"] = max(
                report["validation"]["resources"]["peak_memory_mib"], final.peak_memory_mib
            )
            write_json(directory / "test-class-details.json", scores["class_details"])
            if not scores["metrics_passed"]:
                report["validation"]["metrics"] = {
                    "status": "failed",
                    "details": "最终测试未达到冻结门槛，不重选、不修复",
                }
                raise WorkflowFailure("final_test_threshold_failed")
            report["status"] = "accepted"

    except SearchStop as exc:
        report.update(status="stopped", error_category=exc.category)
    except (WorkflowFailure, ValueError, OSError, KeyError, sqlite3.Error) as exc:
        report.update(status="failed", error_category=getattr(exc, "category", type(exc).__name__))
    except KeyboardInterrupt:
        report.update(status="stopped", error_category="cancelled")
    report["budget_usage"] = {
        "attempts": len(report["attempts"]),
        "attempt_limit": policy.attempt_budget,
        "provider_calls": provider.calls - calls_at_start,
        "provider_call_limit": provider.max_calls,
    }
    report["search_summary"] = {
        key: report[key]
        for key in ("policy", "budget_usage", "attempts", "candidate_stops", "ranking")
    }
    if "validation" in report:
        if report["status"] not in {"accepted", "validated"}:
            report["validation"].update(status="failed", error_category=report["error_category"])
            if report["test_attempted"] and not report["validation"]["final_test_evaluated"]:
                report["validation"]["functional"] = {
                    "status": "failed",
                    "details": report["error_category"],
                }
        report["validation"] = ValidationResult.model_validate(report["validation"]).model_dump(
            mode="json"
        )
    try:
        with KnowledgeStore(db_path) as store:
            if "validation" in report and task and plan:
                report.update(persist_execution(store, report, manifest, task, plan))
            else:
                store.record_workflow(
                    {
                        "workflow_id": workflow_id,
                        "status": report["status"],
                        "error_category": report["error_category"],
                        "search_summary": report["search_summary"],
                        "report_paths": [str(directory / "report.json")],
                    }
                )
        report["persisted"] = True
    except (ValueError, OSError, sqlite3.Error) as exc:
        report.update(
            status="failed",
            error_category="knowledge_writeback_failed",
            writeback_error_type=type(exc).__name__,
        )
    decision(
        "ACCEPT" if report["status"] in {"accepted", "validated"} else "STOP",
        report["error_category"]
        or (
            "验证集比较通过且已回写，未访问最终测试"
            if validation_only
            else "选定版本最终测试通过且结果已回写"
        ),
        [report.get("selected_implementation_id") or workflow_id],
    )
    write_json(
        directory / "provider-audit.json", [item.model_dump(mode="json") for item in provider.audit]
    )
    if hasattr(provider, "usage_summary"):
        write_json(directory / "provider-usage.json", provider.usage_summary())
    report["artifacts_sha256"] = {
        str(p.relative_to(directory)): sha256_file(p)
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }
    save_report(directory, report)
    return report
