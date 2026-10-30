"""Seven-step presentation of stored evidence; browsing never launches execution."""

import difflib

import streamlit as st

from algofactory.web.evidence import STEPS, stage_rows, workflow_evidence

ALGORITHMS = {"text_logistic": "逻辑回归", "text_nb": "朴素贝叶斯"}


def version_label(name):
    if name == "single":
        return "单候选"
    _, algorithm, attempt = name.split("/")
    number = int(attempt.split("-")[1])
    return (
        f"{ALGORITHMS.get(algorithm, algorithm)} · {'初版' if number == 0 else f'修复版 {number}'}"
    )


def raw(value, label="结构化证据"):
    with st.expander(label):
        st.json(value, expanded=False)


def show_workflow(root, relative):
    evidence = workflow_evidence(root, relative)
    summary = evidence["summary"].get("report.json", {})
    versions = evidence["versions"]
    st.subheader("七步流程 · 查看输入、依据与产物")
    st.caption("按候选和版本查看证据；代码已生成不代表验证通过，失败记录回写也不代表任务成功。")
    if evidence["warnings"]:
        st.warning("部分产物暂时无法读取，已保留原文件：" + "、".join(evidence["warnings"]))
    names = list(versions)
    selected = next(
        (
            n
            for n in names
            if summary.get("code_hash")
            and versions[n].get("report.json", {}).get("code_hash") == summary["code_hash"]
        ),
        names[-1],
    )
    name = st.selectbox(
        "查看候选版本",
        names,
        index=names.index(selected),
        format_func=version_label,
        key="version_" + relative,
    )
    bundle = versions[name]
    report = bundle.get("report.json", {})
    if bundle.get("resume-origin.json"):
        st.info("该版本是恢复使用的历史失败证据，本次没有重新执行这个初版。")
    st.dataframe(stage_rows(bundle, terminal=bool(summary)), hide_index=True, width="stretch")
    step = st.radio(
        "查看流程步骤",
        range(7),
        format_func=lambda i: STEPS[i],
        horizontal=True,
        key="step_" + relative,
    )
    st.markdown(f"#### {STEPS[step]}")
    if step == 0:
        task = bundle.get("task.json")
        st.caption("以下为实际解析并通过任务协议核对的结果；提交前的案例说明不是模型解析结果。")
        if not task:
            st.info("尚无已校验的需求产物。任务可能未执行到此处，或历史档案未留存此文件。")
            return
        st.write("**原始能力描述**")
        st.write(task.get("description", "未记录"))
        st.write(
            "**识别的任务类型：** "
            + {
                "multiclass_classification": "文本多分类",
                "binary_classification": "二分类",
                "regression": "回归",
            }.get(task.get("task_type"), "未知")
        )
        st.write("**目标字段：** " + task.get("target", "未记录"))
        st.dataframe(
            [
                {
                    "输入字段": field.get("name"),
                    "类型": field.get("dtype"),
                    "允许缺失": "是" if field.get("nullable") else "否",
                }
                for field in task.get("feature_schema", [])
            ],
            hide_index=True,
            width="stretch",
        )
        st.write("**冻结的评价规则**")
        st.dataframe(
            [
                {
                    "指标": metric.get("name"),
                    "通过门槛": metric.get("threshold"),
                    "方向": "越低越好" if metric.get("direction") == "minimize" else "越高越好",
                }
                for metric in task.get("metrics", [])
            ],
            hide_index=True,
            width="stretch",
        )
        raw(task)
    elif step == 1:
        entries = bundle.get("retrieval.json", [])
        st.caption("按任务类型、数据形态和来源筛选知识；每条知识都保留原文引用。")
        if not entries:
            st.info("当前版本尚无检索证据。")
        for entry in entries:
            record, source = entry.get("record", {}), entry.get("source", {})
            with st.container(border=True):
                st.write("**" + record.get("name", "能力知识") + "**")
                st.caption("来源：" + source.get("title", "未记录"))
                st.write(
                    source.get("span", {}).get("quote")
                    or record.get("source_span", {}).get("quote", "未记录原文")
                )
                st.caption("知识 ID：" + record.get("id", "未记录"))
                raw(record.get("applicability", record.get("conditions", {})), "适用条件")
        cache = bundle.get("knowledge-input.json", {})
        if cache.get("reused_within_search"):
            st.info("本版本复用了已抽取的文档知识。")
    elif step == 2:
        plan = bundle.get("plan.json")
        st.caption("在预设候选和参数约束内规划；候选排名由后续验证集结果决定。")
        if plan:
            entries = bundle.get("retrieval.json", [])
            algorithm = next(
                (
                    x.get("record", {}).get("name")
                    for x in entries
                    if x.get("record", {}).get("id") == plan.get("algorithm_id")
                ),
                None,
            )
            st.write("**算法：** " + (algorithm or plan.get("algorithm_id", "未记录")))
            st.write("**预处理步骤**")
            st.write(plan.get("preprocessing", []))
            st.write("**软件依赖：** " + "、".join(plan.get("dependencies", [])))
            raw(plan, "方案与引用的知识 ID")
        elif bundle.get("plan-proposal.json"):
            st.warning("模型返回了提案，但没有通过方案校验。")
            raw(bundle["plan-proposal.json"], "未通过校验的提案")
        else:
            st.info("当前版本尚无方案产物。")
    elif step == 3:
        code = bundle.get("candidate.py")
        if code:
            st.code(code, language="python")
            st.download_button(
                "下载此版本代码",
                code,
                file_name="candidate.py",
                key="version_download_" + relative + name,
            )
            if bundle.get("configuration-check.json"):
                raw(bundle["configuration-check.json"], "代码参数检查")
            st.caption("代码仅作只读展示；训练和预测通过隔离执行完成。")
        else:
            st.info("当前版本尚无生成代码。")
    elif step == 4:
        validation = report.get("validation") or {}
        if validation:
            st.dataframe(
                [
                    {
                        "检查项": label,
                        "结果": validation.get(key, {}).get("status", "not_run"),
                        "说明": validation.get(key, {}).get("details", ""),
                    }
                    for key, label in (
                        ("functional", "功能"),
                        ("metrics", "指标"),
                        ("stability", "稳定性"),
                        ("interface", "接口"),
                    )
                ],
                hide_index=True,
                width="stretch",
            )
            if validation.get("validation_metrics"):
                st.write("**当前版本验证集成绩**")
                st.json(validation["validation_metrics"])
        else:
            st.info("当前版本尚无评估结果。")
        if summary.get("attempts"):
            st.write("**本次运行的全部候选与版本**")
            st.dataframe(
                [
                    {
                        "候选": ALGORITHMS.get(a["algorithm"], a["algorithm"]),
                        "版本": a["attempt"],
                        "状态": a["status"],
                        "Macro-F1": a.get("validation_metrics", {}).get("macro_f1"),
                        "停止原因": a.get("error_category"),
                    }
                    for a in summary["attempts"]
                ],
                hide_index=True,
                width="stretch",
            )
        ranking = evidence["summary"].get("ranking.json")
        if ranking:
            raw(ranking, "按验证集排序的候选证据")
        if summary.get("test_attempted"):
            st.write("**整次运行的最终测试结果（仅选定版本）**")
            scores = (summary.get("validation") or {}).get("test_metrics")
            if scores:
                st.json(scores)
            else:
                st.warning("已尝试最终测试，但未获得完整测试指标。")
        else:
            st.info("本次未运行最终测试，验证集成绩不能代表最终测试通过。")
    elif step == 5:
        st.caption("以下列出整次运行的修复链，包含各候选的修复版本。")
        repairs = [(n, b) for n, b in versions.items() if b.get("repair-input.json")]
        st.caption("修复仅在需要时触发；保留失败反馈、新版本和复测结果，不用最终测试成绩指导修复。")
        if not repairs:
            st.info(
                "本次尚无修复反馈记录。一次通过无需修复；提前停止也可能没有进入修复。"
                "可在历史案例中查看真实 API 修复过程。"
            )
        for version, data in repairs:
            with st.container(border=True):
                st.write("**" + version_label(version) + "**")
                feedback = data["repair-input.json"]
                diagnosis = feedback.get("diagnosis", {})
                st.write("**错误或优化原因：** " + diagnosis.get("category", "未记录"))
                st.write(diagnosis.get("reason", ""))
                raw(feedback, "提交给模型的修复反馈")
                if data.get("candidate.py"):
                    diff = "".join(
                        difflib.unified_diff(
                            feedback.get("previous_code", "").splitlines(keepends=True),
                            data["candidate.py"].splitlines(keepends=True),
                            fromfile="修复前",
                            tofile="修复后",
                        )
                    )
                    st.code(diff or "代码没有变化", language="diff")
                else:
                    st.info("修复反馈已保存，但尚未产出新代码。")
                result = data.get("report.json", {})
                st.write(
                    "**复测状态：** "
                    + {
                        "validated": "验证集通过",
                        "accepted": "最终测试通过",
                        "failed": "未通过",
                        "stopped": "已停止",
                    }.get(result.get("status"), "尚无结果")
                )
                if result.get("error_category"):
                    st.caption(result["error_category"])
                metrics = (result.get("validation") or {}).get("validation_metrics")
                if metrics:
                    st.json(metrics)
    else:
        if report.get("persisted"):
            st.success("当前版本的运行结果已回写；失败结果仍保留失败状态。")
            ids = report.get("knowledge_ids")
            if ids:
                st.dataframe([{"记录": k, "知识 ID": v} for k, v in ids.items()], hide_index=True)
            else:
                st.info("该版本仅保存了工作流记录，未记录完整实现与验证实体。")
        else:
            st.info("尚无当前版本成功回写的确认。")
        if summary.get("persisted"):
            st.caption("整次运行的报告也已确认回写。")
        st.caption("结果回写与修复经验提炼是不同步骤；回写成功不表示自动产生了可复用经验。")
        st.write(
            "到“知识与来源”选择对应本地任务的知识库，可查看实现、验证记录和原始来源之间的关系。"
        )
        raw(
            {
                "workflow_id": report.get("workflow_id"),
                "persisted": report.get("persisted"),
                "experience_usage": report.get("experience_usage"),
            },
            "回写与经验使用记录",
        )
