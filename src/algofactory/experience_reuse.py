"""Conservative repair evidence synthesis and scoped retrieval, without LLM self-scoring."""

import ast
import gzip
import hashlib
import json
from pathlib import Path

from algofactory.datasets import sha256_file
from algofactory.generation.configuration import required_configuration, validate_configuration
from algofactory.knowledge.store import KnowledgeStore, canonical
from algofactory.planning import ALGORITHMS
from algofactory.schemas.contracts import ExperienceRecord, ExperienceScope, RepairEvidence
from algofactory.schemas.knowledge import (
    ExperienceEntity,
    KnowledgeBatch,
    Relation,
    SourceDocument,
    SourceSpan,
)
from algofactory.workflow_models import WorkflowFailure

ADAPTER_GUIDANCE = (
    "fit/predict 接收 pandas DataFrame。将 TfidfVectorizer 放在 ColumnTransformer 中，"
    "使用 config['text_features'][0] 这个字符串列选择器得到一维文本，再连接分类器。"
    "保留既定 TF-IDF 与分类器参数，词表/IDF 只在训练集拟合。"
)


def checked_report(directory: Path, store: KnowledgeStore):
    report = json.loads((directory / "report.json").read_text())
    saved = store.get_workflow(report["workflow_id"])
    if (
        not report["persisted"]
        or report["test_attempted"]
        or report["validation"]["final_test_evaluated"]
        or list(directory.rglob("test-access.json"))
        or saved["status"] != report["status"]
        or saved["validation"] != report["validation"]
        or saved["knowledge_ids"] != report["knowledge_ids"]
        or sha256_file(directory / "candidate.py") != report["code_hash"]
    ):
        raise WorkflowFailure("experience_evidence_mismatch")
    for name, digest in report["artifacts_sha256"].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise WorkflowFailure("experience_artifact_path_invalid")
        data = (
            path.read_bytes()
            if path.exists()
            else gzip.decompress(path.with_suffix(path.suffix + ".gz").read_bytes())
        )
        if hashlib.sha256(data).hexdigest() != digest:
            raise WorkflowFailure("experience_artifact_changed")
    return report


def classifier_signature(code):
    """Only constructor AST data: no generated module is imported."""
    return sorted(
        (
            n.func.id,
            tuple(ast.dump(a) for a in n.args),
            tuple(sorted((k.arg, ast.dump(k.value)) for k in n.keywords)),
        )
        for n in ast.walk(ast.parse(code))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in {"TfidfVectorizer", "LogisticRegression", "MultinomialNB"}
    )


def synthesize_repair(store: KnowledgeStore, failed_dir: Path, repaired_dir: Path, algorithm: str):
    if algorithm not in ALGORITHMS:
        raise WorkflowFailure("experience_algorithm_unsupported")
    before = checked_report(failed_dir, store)
    after = checked_report(repaired_dir, store)
    if before["status"] != "failed" or after["status"] != "validated":
        raise WorkflowFailure("experience_requires_failed_then_validated")
    previous = store.evidence(before["knowledge_ids"]["implementation_id"])["record"]
    repaired = store.evidence(after["knowledge_ids"]["implementation_id"])["record"]
    if repaired["parent_id"] != previous["id"] or repaired["code_hash"] == previous["code_hash"]:
        raise WorkflowFailure("experience_lineage_mismatch")
    task = json.loads((repaired_dir / "task.json").read_text())
    if before["task_profile"] != "banking77" or after["task_profile"] != "banking77":
        raise WorkflowFailure("experience_task_unsupported")
    scope = ExperienceScope(
        algorithm=algorithm,
        data_fingerprint=after["data_fingerprint"],
        config_hash=after["validation"]["config_hash"],
        split_id=after["split_id"],
        text_features=[f["name"] for f in task["feature_schema"] if f["dtype"] == "text"],
    )
    old_code = (failed_dir / "candidate.py").read_text()
    new_code = (repaired_dir / "candidate.py").read_text()
    validate_configuration(new_code, required_configuration(algorithm, task["seed"]))
    old_calls = {
        n.func.id
        for n in ast.walk(ast.parse(old_code))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    recognized = (
        before["error_category"] in {"worker_ValueError", "worker_TypeError"}
        and "ColumnTransformer" not in old_calls
        and "TfidfVectorizer" in old_calls
        and classifier_signature(old_code) == classifier_signature(new_code)
    )
    proof = RepairEvidence(
        rule="text_dataframe_adapter" if recognized else "unclassified",
        scope=scope,
        failed_run_id=before["knowledge_ids"]["validation_run_id"],
        failed_implementation_id=previous["id"],
        repaired_implementation_id=repaired["id"],
        failed_code_hash=previous["code_hash"],
        repaired_code_hash=repaired["code_hash"],
        failure_category=before["error_category"],
    )
    source = SourceDocument.from_text(
        "Measured repair experience",
        canonical(
            {
                "method": "deterministic_adapter_delta_v1",
                "repair_evidence": proof.model_dump(mode="json"),
                "passed_validation_run_id": after["knowledge_ids"]["validation_run_id"],
                "failed_report_sha256": sha256_file(failed_dir / "report.json"),
                "repaired_report_sha256": sha256_file(repaired_dir / "report.json"),
                "validation_metrics": after["validation"]["validation_metrics"],
                "limitation": "Observed repair on this frozen BANKING77 protocol; no causal or cross-business performance claim.",
            }
        ),
    )
    span = SourceSpan(start=0, end=len(source.content), quote=source.content)

    def provenance(local):
        return dict(id=source.id + ":" + local, source_id=source.id, source_span=span)

    entity_id = source.id + ":experience"
    entity = ExperienceEntity(
        **provenance("experience"),
        name="BANKING77 DataFrame 文本适配修复" if recognized else "待核查修复建议",
        record=ExperienceRecord(
            experience_id=entity_id,
            condition="冻结 BANKING77 协议下的 DataFrame→一维文本接口",
            action=ADAPTER_GUIDANCE if recognized else "未识别出受支持的单点修复，不自动复用。",
            outcome="修复后通过验证集四维检查；不表示普遍效果提升。",
            source_run_id=after["knowledge_ids"]["validation_run_id"],
            verification_status="verified" if recognized else "proposed",
            repair_evidence=proof,
        ),
    )
    relations = [
        Relation(
            **provenance(f"derived:{i}"), type="DERIVED_FROM", head_id=entity_id, tail_id=run_id
        )
        for i, run_id in enumerate([proof.failed_run_id, entity.record.source_run_id])
    ]
    snapshot = store.snapshot()
    for field, additions in (
        ("sources", [source]),
        ("entities", [entity]),
        ("relations", relations),
    ):
        merged = {obj["id"]: obj for obj in snapshot[field]}
        merged.update({obj.id: obj.model_dump(mode="json") for obj in additions})
        snapshot[field] = list(merged.values())
    inserted = store.put_batch(KnowledgeBatch.model_validate(snapshot))
    return {"experience": entity.model_dump(mode="json"), "inserted": inserted}


def retrieve_repairs(
    store: KnowledgeStore,
    *,
    profile,
    algorithm,
    manifest,
    protocol,
    category=None,
    allowed_ids=None,
):
    """Exact conservative scope matching; legacy/unclassified/proposed records never auto-apply."""
    snapshot = store.snapshot()
    if not snapshot["entities"]:
        return {"matches": [], "excluded": []}
    batch = KnowledgeBatch.model_validate(snapshot)
    matches, excluded = [], []
    for entity in batch.entities:
        if not isinstance(entity, ExperienceEntity):
            continue
        record, reason = entity.record, None
        proof = record.repair_evidence
        if allowed_ids is not None and entity.id not in allowed_ids:
            reason = "outside_frozen_library"
        elif (
            record.verification_status != "verified"
            or proof is None
            or proof.rule != "text_dataframe_adapter"
        ):
            reason = "not_verified_scoped_repair"
        elif (
            profile.name != proof.scope.task_profile
            or profile.data_kind != proof.scope.data_kind
            or profile.task_type != proof.scope.task_type
            or list(profile.text) != proof.scope.text_features
            or algorithm != proof.scope.algorithm
        ):
            reason = "task_or_algorithm_mismatch"
        elif (
            manifest["data_fingerprint"] != proof.scope.data_fingerprint
            or manifest["split_id"] != proof.scope.split_id
            or protocol["config_hash"] != proof.scope.config_hash
        ):
            reason = "frozen_protocol_mismatch"
        elif category is not None and category != proof.failure_category:
            reason = "failure_category_mismatch"
        if reason:
            excluded.append({"id": entity.id, "reason": reason})
        else:
            matches.append(
                {
                    "experience_id": entity.id,
                    "rule": proof.rule,
                    "guidance": ADAPTER_GUIDANCE,
                    "source_run_ids": [proof.failed_run_id, record.source_run_id],
                    "failure_category": proof.failure_category,
                    "matched_scope": proof.scope.model_dump(mode="json"),
                    "match_reason": "verified repair; exact task, algorithm, fields, data and frozen protocol match",
                }
            )
    return {"matches": sorted(matches, key=lambda x: x["experience_id"])[:3], "excluded": excluded}
