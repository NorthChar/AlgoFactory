"""Read-only training/validation views; no final-test rows and no execution."""

import gzip
import hashlib
import json
from pathlib import Path

import pandas as pd

from algofactory.datasets import sha256_file
from algofactory.web.evidence import workflow_evidence
from algofactory.web.service import read_json


def safe_file(root, relative):
    root = Path(root).resolve()
    path = root / relative
    if not path.resolve().is_relative_to(root) or any(
        p.is_symlink() for p in (path, *path.parents) if p != root and root in p.parents
    ):
        raise ValueError("unsafe_artifact_path")
    return path


def dataset_snapshot(root):
    directory = safe_file(root, "runtime/banking77-data")
    manifest = read_json(safe_file(directory, "manifest.json"))
    if manifest.get("task_profile") != "banking77":
        raise ValueError("banking77_required")
    # Deliberately do not read test_features/test_labels/all_rows in this browser.
    for name in ("audit.json", "train.csv", "validation_features.csv", "validation_labels.csv"):
        if sha256_file(safe_file(directory, name)) != manifest["files"][name]:
            raise ValueError("dataset_fingerprint_mismatch")
    audit = read_json(directory / "audit.json")
    if audit["split_counts"] != {k: len(v) for k, v in manifest["split_indices"].items()}:
        raise ValueError("split_counts_mismatch")
    return directory, manifest, audit


def samples(root, split="train"):
    if split not in {"train", "validation"}:
        raise ValueError("browsing_only_train_and_validation")
    directory, manifest, _ = dataset_snapshot(root)
    if split == "train":
        frame = pd.read_csv(directory / "train.csv", keep_default_na=False)
    else:
        frame = pd.read_csv(directory / "validation_features.csv", keep_default_na=False).merge(
            pd.read_csv(directory / "validation_labels.csv"), on="row_id", validate="one_to_one"
        )
    if frame.row_id.tolist() != manifest["split_indices"][split]:
        raise ValueError("row_alignment_mismatch")
    mapping = dict(zip(manifest["class_labels"], manifest["class_names"], strict=True))
    if not set(frame.intent) <= set(mapping):
        raise ValueError("label_mapping_mismatch")
    frame["真实意图"] = frame.intent.map(mapping)
    return frame


def validation_errors(root, relative, version):
    evidence = workflow_evidence(root, relative)
    if version not in evidence["versions"]:
        raise ValueError("unknown_version")
    report = evidence["versions"][version].get("report.json", {})
    _, manifest, _ = dataset_snapshot(root)
    if any(report.get(k) != manifest[k] for k in ("data_fingerprint", "split_id", "class_names")):
        raise ValueError("report_dataset_mismatch")
    directory = safe_file(root, relative + ("/" + version if version != "single" else ""))
    code = safe_file(directory, "candidate.py")
    if sha256_file(code) != report["code_hash"]:
        raise ValueError("code_hash_mismatch")
    name = "validation-execution/predictions.json"
    path = safe_file(directory, name)
    if path.is_file():
        if path.stat().st_size > 32_000_000:
            raise ValueError("predictions_too_large")
        raw = path.read_bytes()
    else:
        with gzip.open(safe_file(directory, name + ".gz"), "rb") as archive:
            raw = archive.read(32_000_001)
    if len(raw) > 32_000_000 or hashlib.sha256(raw).hexdigest() != report["artifacts_sha256"][name]:
        raise ValueError("predictions_hash_mismatch")
    stored = json.loads(raw)
    frame = samples(root, "validation")
    ids, predictions = stored["row_ids"], stored["predictions"]
    if (
        stored["status"] != "ok"
        or stored["classes"] != manifest["class_labels"]
        or len(ids) != len(set(ids))
        or set(ids) != set(frame.row_id)
        or len(ids) != len(predictions)
        or not set(predictions) <= set(manifest["class_labels"])
    ):
        raise ValueError("prediction_alignment_mismatch")
    frame = frame.merge(
        pd.DataFrame({"row_id": ids, "预测编号": predictions}), on="row_id", validate="one_to_one"
    )
    accuracy = float((frame.intent == frame["预测编号"]).mean())
    expected = report["validation"]["validation_metrics"]["accuracy"]
    if abs(accuracy - expected) > 1e-10:
        raise ValueError("report_metric_mismatch")
    frame["预测意图"] = frame["预测编号"].map(dict(enumerate(manifest["class_names"])))
    return frame[frame.intent != frame["预测编号"]], accuracy


def show_data(root):
    import streamlit as st

    st.subheader("这些咨询怎样帮助算法学会分类？")
    st.write(
        "每条数据是一句英文客服咨询和人工标注的意图。算法用训练集学习文本与类别的关系，再用未参与学习的验证集检查效果。这里的训练不涉及微调 GPT。"
    )
    try:
        _, manifest, audit = dataset_snapshot(root)
        columns = st.columns(3)
        for column, split, title in zip(
            columns,
            ("train", "validation", "test"),
            ("学习 · 训练集", "比较与改进 · 验证集", "最终评估 · 测试集"),
            strict=True,
        ):
            column.metric(title, audit["split_counts"][split])
        st.caption(
            f"原始 {audit['official_train_rows'] + audit['official_test_rows']:,} 条 → 清洗后 {manifest['rows']:,} 条；{len(manifest['class_names'])} 个类别。最终测试集保持冻结，不在这里展示逐条内容。"
        )
        with st.expander("来源与清洗依据"):
            st.write(manifest["source"]["attribution"])
            st.caption(manifest["source"]["license"] + " · " + manifest["source"]["revision"])
            st.json(
                {
                    "清洗原因": pd.Series([r["reason"] for r in audit["removed_training_rows"]])
                    .value_counts()
                    .to_dict(),
                    "data_fingerprint": manifest["data_fingerprint"],
                    "split_id": manifest["split_id"],
                }
            )
        split = st.radio(
            "浏览哪部分数据",
            ["train", "validation"],
            format_func=lambda x: {
                "train": "训练集：算法学习用",
                "validation": "验证集：检查学习效果用",
            }[x],
            horizontal=True,
        )
        frame = samples(root, split)
        category = st.selectbox("按真实意图筛选", ["全部", *manifest["class_names"]])
        if category != "全部":
            frame = frame[frame["真实意图"] == category]
        st.caption(f"符合条件 {len(frame)} 条。显示原始英文类别名称，避免翻译改变标签含义。")
        page = st.number_input(
            "样本页码",
            min_value=1,
            max_value=max(1, (len(frame) + 19) // 20),
            value=1,
            key="data_page_" + split + category,
        )
        st.dataframe(
            frame.iloc[(page - 1) * 20 : page * 20][["row_id", "text", "真实意图"]],
            hide_index=True,
            width="stretch",
        )
    except (ValueError, OSError, KeyError):
        st.info("数据尚未准备或校验未通过。请先按项目说明导入 BANKING77。")


def show_errors(root, relative):
    import streamlit as st

    with st.expander("查看验证集中分错的咨询"):
        evidence = workflow_evidence(root, relative)
        options = [
            name
            for name, bundle in evidence["versions"].items()
            if bundle.get("report.json", {}).get("validation", {}).get("validation_metrics")
            and bundle.get("report.json", {}).get("task_profile") == "banking77"
        ]
        if not options:
            st.info("此运行没有可查看的 BANKING77 验证预测。")
            return
        version = st.selectbox("错误分析版本", options, key="error_version_" + relative)
        try:
            frame, accuracy = validation_errors(root, relative, version)
            st.caption(
                f"原次保存的验证预测：准确率 {accuracy:.2%}，共分错 {len(frame)} 条。查看不会重新训练、预测或调用模型。"
            )
            category = st.selectbox(
                "错误真实类别",
                ["全部", *sorted(frame["真实意图"].unique())],
                key="error_category_" + relative + version,
            )
            if category != "全部":
                frame = frame[frame["真实意图"] == category]
            page = st.number_input(
                "错误页码",
                min_value=1,
                max_value=max(1, (len(frame) + 19) // 20),
                value=1,
                key="error_page_" + relative + version + category,
            )
            st.dataframe(
                frame.iloc[(page - 1) * 20 : page * 20][["row_id", "text", "真实意图", "预测意图"]],
                hide_index=True,
                width="stretch",
            )
        except (ValueError, OSError, KeyError):
            st.info(
                "原次预测缺失或与数据、代码、报告不匹配，无法展示。系统不会重新预测来替代历史证据。"
            )
