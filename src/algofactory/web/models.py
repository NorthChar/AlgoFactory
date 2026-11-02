"""Provenance-bound local model trials. Pickle is only loaded in the approved sandbox."""

import hashlib
import re
import tempfile
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from algofactory.datasets import sha256_file
from algofactory.execution.docker import DockerExecutor
from algofactory.generation.configuration import required_configuration, validate_configuration
from algofactory.generation.safety import check_code
from algofactory.schemas.contracts import ExecutionBudget
from algofactory.tasks import profile_for
from algofactory.web.data_view import dataset_snapshot, safe_file
from algofactory.web.evidence import workflow_evidence
from algofactory.web.service import read_json
from algofactory.workflow_models import WorkflowFailure


def eligible_versions(root, relative):
    return {
        name: bundle
        for name, bundle in workflow_evidence(root, relative)["versions"].items()
        if bundle.get("report.json", {}).get("task_profile") == "banking77"
        and bundle.get("report.json", {}).get("status") in {"validated", "accepted"}
    }


def source_version(root, relative, version):
    versions = eligible_versions(root, relative)
    if version not in versions:
        raise ValueError("validated_version_required")
    report = versions[version]["report.json"]
    dataset, manifest, _ = dataset_snapshot(root, relative)
    if report.get("selection") != manifest.get("selection"):
        raise ValueError("model_selection_mismatch")
    if any(report.get(k) != manifest[k] for k in ("data_fingerprint", "split_id", "class_names")):
        raise ValueError("model_dataset_mismatch")
    directory = safe_file(root, relative + ("/" + version if version != "single" else ""))
    code = safe_file(directory, "candidate.py")
    if sha256_file(code) != report["code_hash"]:
        raise ValueError("model_code_mismatch")
    check_code(code.read_text())
    check = versions[version].get("configuration-check.json")
    required = (
        check["required_configuration"]
        if check and check.get("status") == "passed"
        else required_configuration("text_logistic")
    )
    validate_configuration(code.read_text(), required)
    return directory, dataset, manifest, report


def prepared_directory(root, relative, version):
    # Only internal IDs; the page never accepts an arbitrary model file or model upload.
    identifier = hashlib.sha256((relative + "/" + version).encode()).hexdigest()
    return safe_file(root, "runtime/prepared-models/" + identifier)


def model_location(root, relative, version):
    directory, _, _, _ = source_version(root, relative, version)
    prepared = prepared_directory(root, relative, version)
    if (prepared / "model-provenance.json").is_file():
        return prepared, "用户显式重新准备的模型（仅训练集拟合）"
    return safe_file(
        root, str((directory / "validation-execution").relative_to(Path(root).resolve()))
    ), "此版本验证时保存的模型"


def executor(root):
    return DockerExecutor(Path(root) / "runtime/docker-image.json", Path(root) / "requirements.txt")


def checked_model(root, relative, version, engine):
    directory, _, manifest, report = source_version(root, relative, version)
    location, origin = model_location(root, relative, version)
    metadata = read_json(safe_file(location, "model-provenance.json"))
    model = safe_file(location, "model.pkl.gz")
    config = metadata["config"]
    if (
        sha256_file(model) != metadata["model_sha256"]
        or metadata["code_hash"] != report["code_hash"]
        or metadata["train_sha256"] != manifest["files"]["train.csv"]
        or metadata["training_rows"] != len(manifest["split_indices"]["train"])
        or metadata["classes"] != manifest["class_labels"]
        or metadata["image_id"] != engine.approval["image_id"]
        or not metadata["environment"]
        or any(
            config.get(k) != manifest[k] for k in ("data_fingerprint", "split_id", "class_names")
        )
        or config.get("experiment_hash") != report.get("experiment_hash")
    ):
        raise ValueError("model_provenance_mismatch")
    if location == directory / "validation-execution":
        for name in ("model.pkl.gz", "model-provenance.json"):
            if sha256_file(safe_file(location, name)) != report["artifacts_sha256"].get(
                "validation-execution/" + name
            ):
                raise ValueError("model_report_hash_mismatch")
    return model, metadata, origin


def prepare_model(root, relative, version):
    directory, dataset, manifest, report = source_version(root, relative, version)
    destination = prepared_directory(root, relative, version)
    if destination.exists():
        destination.rename(
            destination.with_name(destination.name + "-previous-" + uuid.uuid4().hex)
        )
    config = {
        **profile_for(manifest).intent(),
        "class_labels": manifest["class_labels"],
        "seed": manifest["seed"],
        "stage": "prepare",
        **{k: manifest[k] for k in ("data_fingerprint", "split_id", "class_names")},
        "experiment_hash": report.get("experiment_hash"),
    }
    # The check row comes from training; preparation has no validation/test mount.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        feature_file = Path(temp) / "features.csv"
        pd.read_csv(dataset / "train.csv", keep_default_na=False).head(1)[
            ["row_id", "text"]
        ].to_csv(feature_file, index=False)
        result = executor(root).execute(
            directory / "candidate.py",
            dataset / "train.csv",
            feature_file,
            config,
            destination,
            ExecutionBudget(),
        )
    if result.status != "ok":
        raise WorkflowFailure(result.error_category or "model_preparation_failed")
    return read_json(destination / "model-provenance.json")


def checked_text(root, text):
    if (
        not isinstance(text, str)
        or not 1 <= len(text.strip()) <= 1000
        or not text.isascii()
        or not re.search("[a-zA-Z]", text)
    ):
        raise ValueError("use_1_to_1000_characters_of_English_text")
    dataset, manifest, _ = dataset_snapshot(root)
    path = safe_file(dataset, "test_features.csv")
    if sha256_file(path) != manifest["files"]["test_features.csv"]:
        raise ValueError("test_guard_fingerprint_mismatch")

    def normalized(value):
        return " ".join(value.strip().casefold().split())

    # Only host guard sees test text. No labels or test inputs reach the model.
    heldout = pd.read_csv(path, keep_default_na=False)
    if normalized(text) in set(heldout.text.map(normalized)):
        raise ValueError("frozen_test_text_not_allowed")
    return text.strip()


def predict_text(root, relative, version, text):
    text = checked_text(root, text)
    engine = executor(root)
    model, metadata, origin = checked_model(root, relative, version, engine)
    directory, _, manifest, report = source_version(root, relative, version)
    runs = safe_file(root, "runtime/model-trials")
    runs.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=runs) as temp:
        features = Path(temp) / "features.csv"
        pd.DataFrame({"row_id": [0], "text": [text]}).to_csv(features, index=False)
        result = engine.execute(
            directory / "candidate.py",
            None,
            features,
            {
                **profile_for(manifest).intent(),
                "stage": "predict",
                "class_labels": manifest["class_labels"],
                "model_environment": metadata["environment"],
            },
            runs / uuid.uuid4().hex,
            ExecutionBudget(timeout_seconds=30),
            model_path=model,
        )
    if result.status != "ok":
        raise WorkflowFailure(result.error_category or "model_prediction_failed")
    probabilities = np.asarray(result.probabilities)
    if (
        result.classes != manifest["class_labels"]
        or result.row_ids != [0]
        or probabilities.shape != (1, len(result.classes))
        or not np.isfinite(probabilities).all()
        or (probabilities < 0).any()
        or (probabilities > 1).any()
        or not np.allclose(probabilities.sum(axis=1), 1, rtol=0, atol=1e-8)
    ):
        raise ValueError("invalid_trial_probabilities")
    indices = np.argsort(-probabilities[0], kind="stable")[:3]
    return {
        "top3": [
            {"意图": manifest["class_names"][i], "概率": float(probabilities[0, i])}
            for i in indices
        ],
        "code_hash": report["code_hash"],
        "model_sha256": metadata["model_sha256"],
        "origin": origin,
    }


def selected_trial_version(root, relative):
    """Bind trials to the delivered version; never substitute another successful candidate."""
    summary = workflow_evidence(root, relative)["summary"].get("report.json", {})
    if summary.get("status") not in {"validated", "accepted"} or not summary.get("code_hash"):
        return None
    return next(
        (
            name
            for name, bundle in eligible_versions(root, relative).items()
            if bundle["report.json"].get("code_hash") == summary["code_hash"]
        ),
        None,
    )


def show_trial(root, relative):
    import streamlit as st

    st.subheader("试用本次生成的算法")
    st.write(
        "输入一句新的英文咨询，让已训练的算法给出类别及概率（最多展示三类）。此处不调用 GPT，也不重新训练；模型尚未保存时，需要先明确点击准备。"
    )
    version = selected_trial_version(root, relative)
    if version is None:
        st.info(
            "本任务尚无可试用的已选定银行咨询分类通过版本。请先查看开发过程和评估结果；"
            "这里不会改用其他任务或候选的模型。合成回归案例仅提供代码与评估报告。"
        )
        return
    from algofactory.web.workflow_view import version_label

    st.caption("已绑定当前任务的交付版本：" + version_label(version))
    selected_report = eligible_versions(root, relative)[version]["report.json"]
    scope = selected_report.get("selection")
    if scope:
        from algofactory.intent_catalog import intent_title

        st.info("本模型的目标意图：" + "；".join(intent_title(n) for n in scope["intents"]))
        st.warning(
            "只在选定类别范围内使用，范围外咨询仍会被分入某个已选类别。"
            if scope["goal"] == "subset"
            else "输出属于/不属于所选意图；不属于只由其余 76 类已知咨询训练，不代表未知业务检测。"
        )
    widget_key = relative + "/" + version
    try:
        location, origin = model_location(root, relative, version)
        ready = all(
            safe_file(location, name).is_file()
            for name in ("model-provenance.json", "model.pkl.gz")
        )
        if not ready:
            st.info(
                "此历史记录尚未保存训练模型。准备时会用该版本代码重新拟合训练集，单独保存，不代表原次训练权重。"
            )
            if st.button("准备此版本模型（不调用 API）", key="prepare_" + widget_key):
                with st.spinner("正在隔离环境中训练并保存模型…"):
                    prepare_model(root, relative, version)
                st.rerun()
        else:
            st.caption(origin + " · " + version_label(version))
            with st.expander("模型环境更新或产物损坏时"):
                st.caption(
                    "重新准备会保留已有产物，并使用此版本代码和冻结训练集产生新模型。不会运行最终测试。"
                )
                if st.button("重新准备此版本模型（不调用 API）", key="reprepare_" + widget_key):
                    with st.spinner("正在隔离环境中重新准备模型…"):
                        prepare_model(root, relative, version)
                    st.rerun()
            with st.form("trial_" + widget_key):
                text = st.text_area(
                    "新的英文咨询",
                    placeholder="例如：I lost my bank card.",
                    help="这里输入一条待分类的英文咨询，不是要求系统开发代码。示意句不保证被正确分类。",
                    max_chars=1000,
                    key="trial_text_" + widget_key,
                )
                submitted = st.form_submit_button("预测这条咨询")
            if submitted:
                with st.spinner("正在隔离环境中预测…"):
                    result = predict_text(root, relative, version, text)
                from algofactory.intent_catalog import INTENTS

                st.dataframe(
                    [
                        {
                            "含义": INTENTS.get(
                                row["意图"],
                                "其他已知咨询"
                                if row["意图"] == "other_known_intents"
                                else row["意图"],
                            ),
                            **row,
                        }
                        for row in result["top3"]
                    ],
                    hide_index=True,
                    width="stretch",
                )
                st.caption(
                    "模型版本："
                    + result["model_sha256"][:16]
                    + " · 代码："
                    + result["code_hash"][:16]
                )
        st.caption(
            "概率表示模型对本次所选类别的相对判断，不是正确率保证。本原型不检测未知意图；试用结果不计入标准评估，也不用于改选最终测试版本。"
        )
    except (ValueError, OSError, KeyError, WorkflowFailure) as exc:
        category = getattr(exc, "category", str(exc))
        if category == "frozen_test_text_not_allowed":
            st.warning("这条文本属于冻结测试集，请换一句自己编写的咨询。")
        elif category == "use_1_to_1000_characters_of_English_text":
            st.warning("请输入 1–1000 字符的非空英文咨询。")
        else:
            st.error(
                "模型缺失、来源校验未通过或隔离执行失败，已停止预测。请检查模型产物和运行环境；不会自动换模型或重新训练。"
            )
