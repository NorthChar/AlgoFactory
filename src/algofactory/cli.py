"""Knowledge and isolated algorithm workflows with machine-readable outcomes."""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path


def parser():
    root = argparse.ArgumentParser(description="AlgoFactory 知识抽取与检索")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="显示已实现阶段")
    commands.add_parser("sandbox-status", help="检查 Docker 是否可用")
    data = commands.add_parser("prepare-data", help="生成固定种子的合成客户数据")
    data.add_argument("--output-dir", type=Path, default=Path("runtime/phase2-data"))
    data.add_argument("--rows", type=int, default=1500)
    data.add_argument("--seed", type=int, default=42)
    calibration = commands.add_parser("calibrate", help="只用训练/验证集校准并冻结指标门槛")
    calibration.add_argument("--dataset-dir", type=Path, default=Path("runtime/phase2-data"))
    demo = commands.add_parser("demo", help="单候选生成、Docker 执行、独立评分与回写")
    demo.add_argument("--mode", choices=["mock", "api"], default="mock")
    demo.add_argument("--request", default="根据客户特征预测客户是否流失，输出流失类别和概率。")
    demo.add_argument("--output-dir", type=Path)
    demo.add_argument("--dataset-dir", type=Path, default=Path("runtime/phase2-data"))
    demo.add_argument("--db", type=Path, default=Path("runtime/phase2.sqlite"))
    demo.add_argument("--image-approval", type=Path, default=Path("runtime/docker-image.json"))
    demo.add_argument("--knowledge-document", type=Path, default=Path("data/customer_churn.txt"))
    demo.add_argument("--fault", choices=["missing_predict_proba", "unsafe_code", "invalid_json"])
    workflow = commands.add_parser("workflow-show", help="查询持久化的流程结果")
    workflow.add_argument("workflow_id")
    workflow.add_argument("--db", type=Path, default=Path("runtime/phase2.sqlite"))
    ingest = commands.add_parser("ingest", help="从 UTF-8 业务文档抽取知识并入库")
    ingest.add_argument("document", type=Path)
    ingest.add_argument(
        "--mode", choices=["mock", "api"], default=os.environ.get("ALGOFACTORY_LLM_MODE", "mock")
    )
    ingest.add_argument("--fixture", type=Path, help="显式 Mock fixture JSON")
    search = commands.add_parser("search", help="检索知识与来源")
    search.add_argument("--text", default="")
    search.add_argument("--task-type", choices=["binary_classification", "regression"])
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
            "phase": 2,
            "status": "single_candidate_workflow",
            "core_workflow": "implemented_docker_required",
            "live_api": "requires_configuration_and_verification",
        }
    from importlib.resources import files

    from algofactory.knowledge.extraction import ingest_document
    from algofactory.knowledge.graph import export_graphml
    from algofactory.knowledge.store import KnowledgeStore
    from algofactory.llm.providers import APIConfig, APIProvider, MockProvider, ProviderError
    from algofactory.schemas import contracts
    from algofactory.schemas.knowledge import Extraction, KnowledgeBatch, SourceDocument

    if args.command in {"prepare-data", "calibrate", "demo", "sandbox-status"}:
        from algofactory.datasets import generate_dataset
        from algofactory.execution.docker import docker_ready, locate_docker
        from algofactory.llm.workflow_mock import MockWorkflowProvider
        from algofactory.orchestrator import run_workflow
        from algofactory.validation.protocol import calibrate

        if args.command == "sandbox-status":
            return docker_ready(locate_docker())
        if args.command == "prepare-data":
            return generate_dataset(args.output_dir, args.rows, args.seed)
        if args.command == "calibrate":
            return calibrate(args.dataset_dir, args.dataset_dir / "protocol.json")
        if args.fault and args.mode != "mock":
            raise ValueError("Explicit fault fixtures are only available in Mock mode")
        if not args.dataset_dir.exists():
            generate_dataset(args.dataset_dir)
        if args.output_dir is None:
            import uuid

            args.output_dir = Path("runtime/runs") / uuid.uuid4().hex
        provider = (
            MockWorkflowProvider(args.fault)
            if args.mode == "mock"
            else APIProvider(APIConfig.from_env())
        )
        report = run_workflow(
            directory=args.output_dir.resolve(),
            dataset_dir=args.dataset_dir.resolve(),
            db_path=args.db.resolve(),
            approval_path=args.image_approval.resolve(),
            requirements_path=Path("requirements.txt").resolve(),
            knowledge_document=args.knowledge_document.resolve(),
            request=args.request,
            provider=provider,
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
            provider = APIProvider(APIConfig.from_env())
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
