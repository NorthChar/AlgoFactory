"""Shared candidate workflow for single-run and bounded search, with host-owned acceptance."""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from algofactory.datasets import sha256_file, verify_dataset, write_json
from algofactory.execution.docker import DockerExecutor
from algofactory.experience import persist_execution
from algofactory.generation.safety import check_code
from algofactory.knowledge.extraction import ingest_document
from algofactory.knowledge.store import KnowledgeStore
from algofactory.llm.providers import APIProvider, Provider, ProviderError, ProviderRequest
from algofactory.reporting import save_report
from algofactory.schemas.contracts import (
    AgentDecision,
    AlgorithmPlan,
    Candidate,
    FeatureSpec,
    MetricRule,
    TaskConstraints,
    TaskSpec,
    ValidationResult,
)
from algofactory.schemas.knowledge import SourceDocument
from algofactory.tasks import compatible_evidence, profile_for
from algofactory.validation.final_test import evaluate_final
from algofactory.validation.protocol import calibrate
from algofactory.validation.scoring import score_predictions
from algofactory.workflow_models import GeneratedCode, RepairContext, TaskIntent, WorkflowFailure


class Trace:
    def __init__(self, directory: Path, workflow_id: str):
        self.directory, self.workflow_id = directory, workflow_id
        self.items = []
        self.context = {
            "candidate_id": None,
            "code_hash": None,
            "source_ids": [],
            "config_hash": None,
        }

    def add(self, state: str, reason: str):
        self.items.append(
            {
                "sequence": len(self.items),
                "workflow_id": self.workflow_id,
                "state": state,
                "reason": reason,
                "timestamp": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                **self.context,
            }
        )
        write_json(self.directory / "trace.json", self.items)


def run_workflow(
    *,
    directory: Path,
    dataset_dir: Path,
    db_path: Path,
    approval_path: Path,
    requirements_path: Path,
    knowledge_document: Path,
    request: str,
    provider: Provider,
    validation_only: bool = False,
    algorithm: str | None = None,
    repair: RepairContext | None = None,
    repair_limit: int = 0,
) -> dict:
    if not 0 <= repair_limit <= 2 or (repair and repair.attempt > repair_limit):
        raise WorkflowFailure("repair_budget_exceeded")
    if directory.exists() and any(directory.iterdir()):
        raise WorkflowFailure("run_directory_must_be_new")
    directory.mkdir(parents=True, exist_ok=True)
    workflow_id = "workflow:" + uuid.uuid4().hex
    trace = Trace(directory, workflow_id)
    report = {
        "workflow_id": workflow_id,
        "provider_mode": provider.mode,
        "status": "failed",
        "persisted": False,
        "code_hash": None,
        "error_category": None,
        "test_attempted": False,
        "execution_evidence": [],
        "evaluation_scope": "validation_only" if validation_only else "validation_and_final_test",
    }
    dimensions = {
        key: {"status": "not_run", "details": "尚未执行"}
        for key in ("functional", "metrics", "stability", "interface")
    }
    validation_metrics, test_metrics = {}, {}
    elapsed, peak_memory = 0.0, 0.0
    manifest = task = plan = protocol = None
    decisions = []
    trace.add("received", "收到显式任务，开始单候选流程")
    try:
        manifest = verify_dataset(dataset_dir)
        profile = profile_for(manifest)
        algorithm_name = profile.algorithm
        if algorithm is not None:
            from algofactory.planning import ALGORITHMS

            if profile.name != "banking77" or algorithm not in ALGORITHMS:
                raise WorkflowFailure("unsupported_candidate_algorithm")
            algorithm_name = ALGORITHMS[algorithm][0]
        if repair:
            import hashlib

            if (
                hashlib.sha256(repair.previous_code.encode()).hexdigest()
                != repair.previous_code_hash
            ):
                raise WorkflowFailure("repair_parent_code_mismatch")
            write_json(directory / "repair-input.json", repair.model_dump(mode="json"))
        report["task_profile"] = profile.name
        report["class_names"] = manifest.get("class_names", ["not_churn", "churn"])
        protocol = calibrate(dataset_dir, dataset_dir / "protocol.json")
        report["thresholds"] = protocol["thresholds"]
        report["data_fingerprint"], report["split_id"] = (
            manifest["data_fingerprint"],
            manifest["split_id"],
        )
        trace.context["config_hash"] = protocol["config_hash"]
        write_json(directory / "protocol.json", protocol)
        write_json(directory / "data-manifest.json", manifest)
        intent = provider.complete(
            ProviderRequest(
                role="knowledge",
                operation="parse_task",
                instruction="将需求解析为 TaskIntent JSON。仅使用给定任务类型和字段，不得把目标字段或 row_id 放入特征。",
                source={
                    "request": request,
                    **profile.intent(),
                },
            ),
            TaskIntent,
        )
        if intent.model_dump(exclude={"schema_version"}) != profile.intent():
            raise WorkflowFailure("intent_feature_mismatch")
        task = TaskSpec(
            task_id=workflow_id + ":task",
            description=request,
            task_type=intent.task_type,
            target=intent.target,
            feature_schema=[
                FeatureSpec(name=name, dtype="numeric", nullable=name != "support_tickets")
                for name in profile.numeric
            ]
            + [
                FeatureSpec(name=name, dtype="categorical", nullable=True)
                for name in profile.categorical
            ]
            + [FeatureSpec(name=name, dtype="text") for name in profile.text],
            data_fingerprint=manifest["data_fingerprint"],
            split_id=manifest["split_id"],
            seed=manifest["seed"],
            class_labels=manifest.get("class_labels", [0, 1]),
            metrics=[
                MetricRule(name=name, direction="maximize", threshold=value)
                for name, value in protocol["thresholds"].items()
            ],
            constraints=TaskConstraints(candidate_limit=1, max_repairs_per_candidate=repair_limit),
        )
        write_json(directory / "task.json", task.model_dump(mode="json"))
        trace.add("parsed", "需求契约已校验，并绑定数据指纹与冻结规则")
        source = SourceDocument.from_text(
            knowledge_document.name, knowledge_document.read_bytes().decode("utf-8")
        )
        with KnowledgeStore(db_path) as store:
            ingest_document(source, provider, store)
            evidence = store.search(
                task_type=task.task_type, source_id=source.id, data_kind=profile.data_kind
            )
        evidence = [entry for entry in evidence if compatible_evidence(entry, profile, source.id)]
        if not evidence:
            raise WorkflowFailure("empty_knowledge_retrieval")
        trace.context["source_ids"] = [source.id]
        write_json(directory / "retrieval.json", evidence)
        trace.add("retrieved", "检索到有原文依据的能力与候选算法")
        plan = provider.complete(
            ProviderRequest(
                role="builder",
                operation="plan_algorithm",
                instruction="根据检索证据返回 AlgorithmPlan JSON，使用给定 algorithm，引用适用的真实 evidence_ids。预处理仅在训练集拟合。",
                source={
                    "task_profile": profile.name,
                    "algorithm": algorithm_name,
                    "plan_id": workflow_id + ":plan",
                    "task_id": task.task_id,
                    "evidence": [entry["record"] for entry in evidence],
                },
            ),
            AlgorithmPlan,
        )
        records = {entry["record"]["id"]: entry["record"] for entry in evidence}
        if (
            plan.task_id != task.task_id
            or plan.plan_id != workflow_id + ":plan"
            or not set(plan.evidence_ids) <= set(records)
            or plan.algorithm_id not in plan.evidence_ids
        ):
            raise WorkflowFailure("plan_evidence_mismatch")
        if (
            records[plan.algorithm_id].get("type") != "Algorithm"
            or records[plan.algorithm_id].get("name") != algorithm_name
            or plan.dependencies != ["scikit-learn"]
        ):
            raise WorkflowFailure("unsupported_phase2_plan")
        write_json(directory / "plan.json", plan.model_dump(mode="json"))
        trace.add("planned", "选择适用的单候选并保存证据引用")
        generated = provider.complete(
            ProviderRequest(
                role="builder",
                operation="repair_code" if repair else "generate_code",
                instruction="返回 GeneratedCode JSON，code 为 Python 源码。仅允许 sklearn 的 ColumnTransformer、SimpleImputer、LogisticRegression、Pipeline、OneHotEncoder、StandardScaler、TfidfVectorizer、MultinomialNB 的 from 导入和一个 build_pipeline(config) 函数。函数内只用赋值、列表/元组、config 下标和这些构造器调用；禁止属性访问、任意 I/O、额外函数或顶层执行。config 提供 numeric_features、categorical_features、text_features、seed。文本用 ColumnTransformer 的字符串列选择器接入 TF-IDF；禁止在 Pipeline 外拟合。预处理在 Pipeline 内，返回支持 fit/predict/predict_proba 的估计器。",
                source={
                    "plan": plan.model_dump(mode="json"),
                    "task_profile": profile.name,
                    "algorithm_key": algorithm,
                    "repair": repair.model_dump(mode="json") if repair else None,
                    **profile.intent(),
                },
            ),
            GeneratedCode,
        )
        if generated.plan_id != plan.plan_id:
            raise WorkflowFailure("generated_plan_mismatch")
        code_path = directory / "candidate.py"
        code_path.write_text(generated.code, encoding="utf-8")
        report["code_hash"] = sha256_file(code_path)
        candidate = Candidate(
            implementation_id=workflow_id + ":candidate",
            plan_id=plan.plan_id,
            code_hash=report["code_hash"],
            attempt=repair.attempt if repair else 0,
            parent_id=repair.parent_id if repair else None,
        )
        report["candidate"] = candidate.model_dump(mode="json")
        write_json(directory / "candidate.json", report["candidate"])
        trace.context.update(
            candidate_id=candidate.implementation_id, code_hash=candidate.code_hash
        )
        decisions.append(
            AgentDecision(
                decision_id=workflow_id + ":generate",
                run_id=workflow_id,
                role="builder",
                action=repair.diagnosis["action"] if repair else "GENERATE",
                reason="根据检索证据生成单个候选",
                evidence_ids=plan.evidence_ids,
                budget_remaining=0,
            ).model_dump(mode="json")
        )
        trace.add("generated", "已生成独立 Python 文件并记录代码散列")
        if repair and candidate.code_hash == repair.previous_code_hash:
            raise WorkflowFailure("repair_unchanged_code")
        check_code(generated.code)
        trace.add("checked", "代码符合受限工厂语法；接下来使用 Docker 隔离执行")
        executor = DockerExecutor(approval_path, requirements_path)
        config = {
            **profile.intent(),
            "class_labels": task.class_labels,
            "seed": task.seed,
            "stage": "validation",
        }
        if verify_dataset(dataset_dir) != manifest or sha256_file(code_path) != candidate.code_hash:
            raise WorkflowFailure("execution_input_changed")
        report["execution_evidence"].append(str(directory / "validation-execution/execution.json"))
        worker = executor.execute(
            code_path,
            dataset_dir / "train.csv",
            dataset_dir / "validation_features.csv",
            config,
            directory / "validation-execution",
            task.constraints.execution,
        )
        elapsed += worker.elapsed_seconds
        peak_memory = max(peak_memory, worker.peak_memory_mib)
        trace.add("executed", "候选在隔离容器中完成训练与验证集预测")
        if worker.status != "ok":
            key = (
                "interface"
                if (worker.error_category or "").startswith("interface_")
                else "functional"
            )
            dimensions[key] = {"status": "failed", "details": worker.error_category}
            raise WorkflowFailure(worker.error_category or "worker_failed")
        if worker.training_rows != len(manifest["split_indices"]["train"]):
            raise WorkflowFailure("training_row_count_mismatch")
        measured = score_predictions(
            worker, pd.read_csv(dataset_dir / "validation_labels.csv"), protocol
        )
        validation_metrics = measured["metrics"]
        if "class_details" in measured:
            write_json(directory / "validation-class-details.json", measured["class_details"])
        dimensions["functional"] = {
            "status": "passed",
            "details": "真实 fit/predict，长度、顺序和有限数值校验通过",
        }
        dimensions["interface"] = {
            "status": "passed" if measured["interface"] else "failed",
            "details": "build_pipeline / fit / predict / predict_proba",
        }
        dimensions["stability"] = {
            "status": "passed" if measured["stability"] else "failed",
            "details": json.dumps(measured["stability_details"], ensure_ascii=False),
        }
        dimensions["metrics"] = {
            "status": "passed" if measured["metrics_passed"] else "failed",
            "details": "验证集对照预先冻结门槛",
        }
        if any(d["status"] != "passed" for d in dimensions.values()):
            raise WorkflowFailure("validation_checks_failed")
        trace.add(
            "validated",
            "四维验证通过；仅用于候选比较"
            if validation_only
            else "四维验证通过；锁定候选后开放一次最终测试",
        )
        if validation_only:
            report["status"] = "validated"
        else:
            final, final_scores = evaluate_final(
                directory,
                dataset_dir,
                manifest,
                task,
                candidate,
                protocol,
                executor,
                config,
                report,
                validation_metrics,
            )
            elapsed += final.elapsed_seconds
            peak_memory = max(peak_memory, final.peak_memory_mib)
            test_metrics = final_scores["metrics"]
            if "class_details" in final_scores:
                write_json(directory / "test-class-details.json", final_scores["class_details"])
            if not final_scores["metrics_passed"]:
                dimensions["metrics"] = {
                    "status": "failed",
                    "details": "最终测试未达到冻结门槛，停止且不调参",
                }
                raise WorkflowFailure("final_test_threshold_failed")
            report["status"] = "accepted"
            dimensions["metrics"]["details"] = "验证集及一次性独立测试均达到冻结门槛"
    except (WorkflowFailure, ProviderError, ValueError, OSError, KeyError, sqlite3.Error) as exc:
        report["error_category"] = getattr(exc, "category", type(exc).__name__)
        if isinstance(exc, ProviderError) and exc.diagnostics:
            report["error_details"] = exc.diagnostics
        report["status"] = "failed"
        if report["error_category"] in {
            "execution_timeout",
            "resource_limit_exceeded",
            "container_nonzero_exit",
        }:
            dimensions["stability"] = {"status": "failed", "details": report["error_category"]}
        elif report["test_attempted"] and not test_metrics:
            dimensions["functional"] = {
                "status": "failed",
                "details": "最终测试执行未成功：" + report["error_category"],
            }
    except KeyboardInterrupt:
        report["error_category"] = "cancelled"
        report["status"] = "stopped"
    if report["code_hash"] and task and protocol:
        result = ValidationResult(
            run_id=workflow_id + ":validation",
            implementation_id=workflow_id + ":candidate",
            code_hash=report["code_hash"],
            config_hash=protocol["config_hash"],
            split_id=manifest["split_id"],
            status="passed"
            if report["status"] in {"accepted", "validated"}
            else ("stopped" if report["status"] == "stopped" else "failed"),
            **dimensions,
            validation_metrics=validation_metrics,
            test_metrics=test_metrics,
            final_test_evaluated=bool(test_metrics),
            resources={"elapsed_seconds": elapsed, "peak_memory_mib": peak_memory},
            report_paths=[str(directory / "report.json"), str(directory / "report.md")],
            error_category=report["error_category"],
        )
        report["validation"] = result.model_dump(mode="json")
    try:
        with KnowledgeStore(db_path) as store:
            if report.get("validation") and plan:
                report.update(persist_execution(store, report, manifest, task, plan))
            else:
                store.record_workflow(
                    {
                        "workflow_id": workflow_id,
                        "status": report["status"],
                        "error_category": report["error_category"],
                        "error_details": report.get("error_details", []),
                        "report_paths": [str(directory / "report.json")],
                    }
                )
        report["persisted"] = True
        trace.add("persisted", "结果已通过事务写入知识库；失败记录保留失败状态")
    except (ValueError, OSError, sqlite3.Error) as exc:
        report["prior_error_category"] = report["error_category"]
        report["status"], report["error_category"] = "failed", "knowledge_writeback_failed"
        report["writeback_error_type"] = type(exc).__name__
    decisions.append(
        AgentDecision(
            decision_id=workflow_id + ":review",
            run_id=workflow_id,
            role="review",
            action="ACCEPT" if report["status"] in {"accepted", "validated"} else "STOP",
            reason="确定性独立验证结果：" + (report["error_category"] or "全部通过且已回写"),
            evidence_ids=[report["validation"]["run_id"]]
            if "validation" in report
            else [workflow_id],
            budget_remaining=0,
        ).model_dump(mode="json")
    )
    write_json(directory / "decisions.json", decisions)
    write_json(
        directory / "provider-audit.json", [item.model_dump(mode="json") for item in provider.audit]
    )
    if isinstance(provider, APIProvider):
        write_json(directory / "provider-usage.json", provider.usage_summary())
    trace.add(
        report["status"],
        report["error_category"]
        or (
            "验证集通过，等待统一比较，尚未使用测试集"
            if validation_only
            else "算法通过独立评分并完成知识回写"
        ),
    )
    report["artifacts_sha256"] = {
        str(p.relative_to(directory)): sha256_file(p)
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }
    save_report(directory, report)
    return report
