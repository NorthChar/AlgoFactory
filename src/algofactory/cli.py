"""Knowledge and isolated algorithm workflows with machine-readable outcomes."""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path


def parser():
    root = argparse.ArgumentParser(description="AlgoFactory 知识抽取与检索")
    root.add_argument(
        "--env-file", type=Path, help="显式读取本地配置；系统环境变量优先，不执行 shell"
    )
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("plugins", help="列出已注册的可信模板和指标插件")
    commands.add_parser("status", help="显示已实现阶段")
    commands.add_parser("sandbox-status", help="检查 Docker 是否可用")
    data = commands.add_parser("prepare-data", help="生成固定种子的合成客户数据")
    data.add_argument("--output-dir", type=Path, default=Path("runtime/phase2-data"))
    data.add_argument("--rows", type=int, default=1500)
    data.add_argument("--seed", type=int, default=42)
    regression = commands.add_parser("prepare-regression", help="生成轻量合成回归数据")
    regression.add_argument("--output-dir", type=Path, default=Path("runtime/regression-data"))
    regression.add_argument("--rows", type=int, default=600)
    regression.add_argument("--seed", type=int, default=42)
    banking = commands.add_parser(
        "prepare-banking77", help="导入固定版本 BANKING77，保存来源、去重及划分证据"
    )
    banking.add_argument("--output-dir", type=Path, default=Path("runtime/banking77-data"))
    banking.add_argument(
        "--raw-dir",
        type=Path,
        help="已下载的 train.csv/test.csv/LICENSE 目录；省略时从固定官方版本下载",
    )
    calibration = commands.add_parser("calibrate", help="只用训练/验证集校准并冻结指标门槛")
    calibration.add_argument("--dataset-dir", type=Path, default=Path("runtime/phase2-data"))
    demo = commands.add_parser("demo", help="单候选生成、Docker 执行、独立评分与回写")
    demo.add_argument("--mode", choices=["mock", "api"], default="mock")
    demo.add_argument("--task", choices=["churn", "banking77", "regression"], default="churn")
    demo.add_argument("--request")
    demo.add_argument(
        "--experiment", type=Path, help="冻结的 BANKING77 实验 JSON；候选及参数使用有限白名单"
    )
    demo.add_argument("--output-dir", type=Path)
    demo.add_argument("--dataset-dir", type=Path)
    demo.add_argument("--db", type=Path, default=Path("runtime/phase2.sqlite"))
    demo.add_argument("--image-approval", type=Path, default=Path("runtime/docker-image.json"))
    demo.add_argument("--knowledge-document", type=Path)
    demo.add_argument(
        "--fault",
        choices=[
            "missing_predict_proba",
            "unsafe_code",
            "invalid_json",
            "repairable_interface",
            "persistent_interface",
            "unrepairable",
            "text_adapter",
        ],
    )
    demo.add_argument(
        "--compare", action="store_true", help="Phase 3：BANKING77 两候选比较与有界修复"
    )
    demo.add_argument("--max-repairs", type=int, choices=[0, 1, 2], default=2)
    demo.add_argument("--attempt-budget", type=int, choices=range(1, 7), default=6)
    demo.add_argument(
        "--experiences", action="store_true", help="检索适用的已验证经验并记录模型采用情况"
    )
    demo.add_argument(
        "--learn-experiences", action="store_true", help="比较流程中从通过重测的修复链沉淀经验"
    )
    demo.add_argument(
        "--validation-only", action="store_true", help="只运行验证集，经验对照不打开最终测试"
    )
    demo.add_argument(
        "--reuse-knowledge", action="store_true", help="比较时复用数据库中同内容文档的已校验知识"
    )
    demo.add_argument(
        "--llm-call-budget",
        type=int,
        choices=range(1, 101),
        help="整个流程共享调用上限；Mock 比较默认 32，单候选默认 8",
    )
    workflow = commands.add_parser("workflow-show", help="查询持久化的流程结果")
    workflow.add_argument("workflow_id")
    workflow.add_argument("--db", type=Path, default=Path("runtime/phase2.sqlite"))
    learn = commands.add_parser(
        "learn-experience", help="从持久化失败和通过重测的版本提炼可追溯经验"
    )
    learn.add_argument("--failed-dir", type=Path, required=True)
    learn.add_argument("--repaired-dir", type=Path, required=True)
    learn.add_argument("--algorithm", choices=["text_logistic", "text_nb"], required=True)
    learn.add_argument("--db", type=Path, required=True)
    experience_search = commands.add_parser(
        "experience-search", help="按任务、算法、冻结协议和错误类型检索已验证经验"
    )
    experience_search.add_argument("--db", type=Path, required=True)
    experience_search.add_argument("--dataset-dir", type=Path, required=True)
    experience_search.add_argument(
        "--algorithm", choices=["text_logistic", "text_nb"], required=True
    )
    experience_search.add_argument("--failure-category")
    ingest = commands.add_parser("ingest", help="从 UTF-8 业务文档抽取知识并入库")
    ingest.add_argument("document", type=Path)
    ingest.add_argument(
        "--mode", choices=["mock", "api"], default=os.environ.get("ALGOFACTORY_LLM_MODE", "mock")
    )
    ingest.add_argument("--fixture", type=Path, help="显式 Mock fixture JSON")
    search = commands.add_parser("search", help="检索知识与来源")
    search.add_argument("--text", default="")
    search.add_argument(
        "--task-type", choices=["binary_classification", "multiclass_classification", "regression"]
    )
    search.add_argument(
        "--entity-type",
        choices=[
            "Task",
            "Capability",
            "Algorithm",
            "Implementation",
            "Dataset",
            "ValidationRun",
            "FailureCase",
            "Experience",
            "Dependency",
        ],
    )
    search.add_argument("--limit", type=int, default=20)
    show = commands.add_parser("show", help="按 ID 查询完整证据")
    show.add_argument("identifier")
    export = commands.add_parser("export", help="导出 JSON 与 GraphML")
    export.add_argument("--output-dir", type=Path, default=Path("runtime/knowledge-export"))
    restore = commands.add_parser("import", help="校验并导入知识 JSON")
    restore.add_argument("document", type=Path)
    for command in (ingest, search, show, export, restore):
        command.add_argument("--db", type=Path, default=Path("runtime/knowledge.sqlite"))
    schemas = commands.add_parser("schemas", help="导出版本化 JSON Schema")
    schemas.add_argument("--output-dir", type=Path, default=Path("runtime/schemas"))
    return root


def run(args):
    if args.command == "status":
        return {
            "phase": 7,
            "tasks": ["banking77", "churn", "regression"],
            "status": "interactive_experiment_workbench",
            "core_workflow": "implemented_docker_required",
            "live_api": "phase3_evidence_available; current credentials and environment required",
            "experience_reuse": "scoped_repair_evidence_and_opt_in_retrieval",
        }
    from importlib.resources import files

    from algofactory.knowledge.extraction import ingest_document
    from algofactory.knowledge.graph import export_graphml
    from algofactory.knowledge.store import KnowledgeStore
    from algofactory.llm.providers import APIConfig, APIProvider, MockProvider, ProviderError
    from algofactory.schemas import contracts
    from algofactory.schemas.knowledge import Extraction, KnowledgeBatch, SourceDocument

    if args.command == "plugins":
        from algofactory.plugins import default_registry

        return default_registry().describe()
    if args.command == "prepare-regression":
        from algofactory.regression import generate_regression

        return generate_regression(args.output_dir, args.rows, args.seed)
    if args.command == "learn-experience":
        from algofactory.experience_reuse import synthesize_repair

        with KnowledgeStore(args.db) as store:
            return synthesize_repair(store, args.failed_dir, args.repaired_dir, args.algorithm)
    if args.command == "experience-search":
        from algofactory.datasets import verify_dataset
        from algofactory.experience_reuse import retrieve_repairs
        from algofactory.tasks import profile_for
        from algofactory.validation.protocol import calibrate

        manifest = verify_dataset(args.dataset_dir)
        protocol = calibrate(args.dataset_dir, args.dataset_dir / "protocol.json")
        with KnowledgeStore(args.db) as store:
            return retrieve_repairs(
                store,
                profile=profile_for(manifest),
                algorithm=args.algorithm,
                manifest=manifest,
                protocol=protocol,
                category=args.failure_category,
            )

    if args.command in {"prepare-data", "prepare-banking77", "calibrate", "demo", "sandbox-status"}:
        from algofactory.datasets import generate_dataset
        from algofactory.execution.docker import docker_ready, locate_docker
        from algofactory.llm.workflow_mock import MockWorkflowProvider
        from algofactory.orchestrator import run_workflow
        from algofactory.validation.protocol import calibrate

        if args.command == "sandbox-status":
            return docker_ready(locate_docker())
        if args.command == "prepare-banking77":
            from algofactory.banking import import_banking77

            return import_banking77(args.output_dir, args.raw_dir)
        if args.command == "prepare-data":
            return generate_dataset(args.output_dir, args.rows, args.seed)
        if args.command == "calibrate":
            return calibrate(args.dataset_dir, args.dataset_dir / "protocol.json")
        from algofactory.datasets import verify_dataset

        # CLI callers must explicitly bind nonstandard text to a checked experiment.
        # Legacy canonical examples retain their established behavior.
        from algofactory.tasks import BANKING77_REUSE_REQUEST, PROFILES, profile_for

        if (
            args.task == "banking77"
            and args.request
            not in {
                None,
                "",
                PROFILES["banking77"].request,
                BANKING77_REUSE_REQUEST,
            }
            and not args.experiment
        ):
            raise ValueError(
                "requirement_needs_bound_configuration: provide a checked --experiment"
            )
        experiment = None
        if args.experiment:
            from algofactory.experiments import ExperimentConfig

            experiment = ExperimentConfig.model_validate_json(args.experiment.read_text())
            if args.task != "banking77":
                raise ValueError("experiment_requires_banking77")
            experiment.validate_request(args.request or "")
            if args.learn_experiences:
                raise ValueError("configured_experiment_synthesis_not_supported")
            # A one-candidate search still uses the bounded repair machinery.
            args.compare = True
        profile = PROFILES[args.task]
        args.dataset_dir = args.dataset_dir or Path(
            "runtime/"
            + {
                "banking77": "banking77-data",
                "churn": "phase2-data",
                "regression": "regression-data",
            }[args.task]
        )
        if args.compare and args.task != "banking77":
            raise ValueError(
                "Phase 3 comparison supports BANKING77; churn remains a fixed compatibility candidate"
            )
        if not args.compare and args.fault in {
            "repairable_interface",
            "persistent_interface",
            "unrepairable",
            "text_adapter",
        }:
            raise ValueError("This fault fixture requires --compare")
        if not args.compare and (args.learn_experiences or args.reuse_knowledge):
            raise ValueError("Learning and persisted knowledge reuse require --compare")
        args.knowledge_document = args.knowledge_document or Path("data") / (
            "banking77-phase3.txt" if args.compare else profile.document
        )
        args.request = args.request or profile.request
        if args.fault and args.mode != "mock":
            raise ValueError("Explicit fault fixtures are only available in Mock mode")
        if not args.dataset_dir.exists():
            if args.task == "banking77":
                raise ValueError("Run prepare-banking77 first")
            if args.task == "regression":
                from algofactory.regression import generate_regression

                generate_regression(args.dataset_dir)
            else:
                generate_dataset(args.dataset_dir)
        manifest = verify_dataset(args.dataset_dir)
        if profile_for(manifest).name != profile.name:
            raise ValueError("Task selection does not match dataset profile")
        if experiment and experiment.goal != "full" and not manifest.get("selection"):
            import uuid

            from algofactory.banking import derive_banking77

            derived = Path("runtime/derived-datasets") / uuid.uuid4().hex
            manifest = derive_banking77(args.dataset_dir, derived, experiment)
            args.dataset_dir = derived
        if experiment:
            experiment.validate_manifest(manifest)
        elif manifest.get("selection"):
            raise ValueError("derived_task_requires_experiment")
        if manifest.get("selection") and args.knowledge_document == Path(
            "data/banking77-phase3.txt"
        ):
            args.knowledge_document = Path("data/banking-intent-tasks.txt")
        if args.output_dir is None:
            import uuid

            args.output_dir = Path("runtime/runs") / uuid.uuid4().hex
        provider = (
            MockWorkflowProvider(
                args.fault, max_calls=args.llm_call_budget or (32 if args.compare else 8)
            )
            if args.mode == "mock"
            else APIProvider(APIConfig.from_env(args.env_file))
        )
        if args.llm_call_budget is not None:
            provider.max_calls = args.llm_call_budget
        workflow = run_workflow
        extra = {
            "use_experiences": args.experiences,
            "validation_only": args.validation_only,
            "experiment": experiment,
        }
        if args.compare:
            from algofactory.planning import SearchPolicy
            from algofactory.search import run_search

            workflow = run_search
            extra["policy"] = SearchPolicy(
                algorithms=experiment.algorithms if experiment else ["text_logistic", "text_nb"],
                max_repairs=args.max_repairs,
                attempt_budget=args.attempt_budget,
            )
            extra.update(
                learn_experiences=args.learn_experiences, reuse_knowledge=args.reuse_knowledge
            )
        report = workflow(
            directory=args.output_dir.resolve(),
            dataset_dir=args.dataset_dir.resolve(),
            db_path=args.db.resolve(),
            approval_path=args.image_approval.resolve(),
            requirements_path=Path("requirements.txt").resolve(),
            knowledge_document=args.knowledge_document.resolve(),
            request=args.request,
            provider=provider,
            **extra,
        )
        return {
            "status": report["status"],
            "error_category": report["error_category"],
            "workflow_id": report["workflow_id"],
            "persisted": report["persisted"],
            "report_json": str(args.output_dir / "report.json"),
            "report_markdown": str(args.output_dir / "report.md"),
            "validation_metrics": report.get("validation", {}).get("validation_metrics", {}),
            "test_metrics": report.get("validation", {}).get("test_metrics", {}),
        }

    if args.command == "schemas":
        args.output_dir.mkdir(parents=True, exist_ok=True)
        models = [
            contracts.TaskSpec,
            contracts.AlgorithmPlan,
            contracts.Candidate,
            contracts.ValidationResult,
            contracts.AgentDecision,
            contracts.ExperienceRecord,
            Extraction,
            KnowledgeBatch,
        ]
        for model in models:
            (args.output_dir / f"{model.__name__}.json").write_text(
                json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return {"schemas": [model.__name__ for model in models], "schema_version": 1}
    if args.command == "ingest":
        if args.mode == "mock":
            fixture = (
                args.fixture
                if args.fixture
                else files("algofactory.llm").joinpath("fixtures/churn.json")
            )
            provider = MockProvider.from_file(fixture)
        elif args.mode == "api":
            if args.fixture:
                raise ValueError("An API request cannot use a Mock fixture")
            provider = APIProvider(APIConfig.from_env(args.env_file))
        else:
            raise ValueError("Provider mode must be mock or api")
        source = SourceDocument.from_text(
            args.document.name, args.document.read_bytes().decode("utf-8")
        )
        with KnowledgeStore(args.db) as store:
            try:
                return ingest_document(source, provider, store)
            except ProviderError as exc:
                return {
                    "status": "failed",
                    "error": exc.category,
                    "provider_mode": provider.mode,
                    "audit": [r.model_dump() for r in provider.audit],
                }
    if args.command in {"search", "show", "export", "workflow-show"} and not args.db.is_file():
        raise ValueError("Knowledge database does not exist; ingest a document first")
    with KnowledgeStore(args.db) as store:
        if args.command == "workflow-show":
            return store.get_workflow(args.workflow_id)
        if args.command == "search":
            return {
                "results": store.search(args.text, args.task_type, args.entity_type, args.limit)
            }
        if args.command == "show":
            return store.evidence(args.identifier)
        if args.command == "import":
            batch = KnowledgeBatch.model_validate_json(args.document.read_bytes())
            if any(
                e.type not in {"Task", "Capability", "Algorithm", "Dependency"}
                for e in batch.entities
            ):
                raise ValueError("Phase 1 CLI import only accepts document knowledge")
            return {"inserted": store.put_batch(batch)}
        if args.command == "export":
            store.export_json(args.output_dir / "knowledge.json")
            export_graphml(
                KnowledgeBatch.model_validate(store.snapshot()),
                args.output_dir / "knowledge.graphml",
            )
            return {
                "json": str(args.output_dir / "knowledge.json"),
                "graphml": str(args.output_dir / "knowledge.graphml"),
            }
    raise ValueError("Unsupported command")


def main():
    args = parser().parse_args()
    try:
        result = run(args)
    except (ValueError, OSError, KeyError, sqlite3.Error, RuntimeError) as exc:
        # Do not echo raw validation/HTTP errors, which may contain request text or secrets.
        result = {"status": "failed", "error": getattr(exc, "category", type(exc).__name__)}
    failed = result.get("status") in {"failed", "stopped"}
    print(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        file=sys.stderr if failed else sys.stdout,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
