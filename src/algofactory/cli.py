"""Phase 1 knowledge commands. Failures return JSON and a nonzero exit status."""

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
            "phase": 1,
            "status": "knowledge_layer",
            "core_workflow": "not_implemented",
            "live_api": "requires_configuration_and_verification",
        }
    from importlib.resources import files

    from algofactory.knowledge.extraction import ingest_document
    from algofactory.knowledge.graph import export_graphml
    from algofactory.knowledge.store import KnowledgeStore
    from algofactory.llm.providers import APIConfig, APIProvider, MockProvider, ProviderError
    from algofactory.schemas import contracts
    from algofactory.schemas.knowledge import Extraction, KnowledgeBatch, SourceDocument

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
    if args.command in {"search", "show", "export"} and not args.db.is_file():
        raise ValueError("Knowledge database does not exist; ingest a document first")
    with KnowledgeStore(args.db) as store:
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
    failed = result.get("status") == "failed"
    print(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        file=sys.stderr if failed else sys.stdout,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
