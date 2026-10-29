"""Run with: python -m streamlit run src/algofactory/web/app.py --server.address 127.0.0.1"""

import json
import os
import uuid
from pathlib import Path

import streamlit as st

from algofactory.tasks import PROFILES
from algofactory.web.service import (
    Jobs,
    RunSettings,
    artifacts,
    confined,
    graph_snapshot,
    graph_view,
    read_json,
    report_catalog,
)

ROOT = Path(
    os.environ.get("ALGOFACTORY_PROJECT_ROOT", Path(__file__).resolve().parents[3])
).resolve()
STATUS = {
    "queued": "等待启动",
    "running": "正在运行",
    "accepted": "最终测试通过",
    "validated": "验证集通过",
    "failed": "未通过",
    "stopped": "已停止",
    "interrupted": "运行中断",
}

st.set_page_config(page_title="AlgoFactory · 算法工作台", page_icon="◈", layout="wide")
st.title("AlgoFactory")
st.caption("从能力描述到可验证算法 · BANKING77 客服意图分类")
jobs = Jobs(ROOT)
with st.sidebar:
    st.subheader("本地算法工作台")
    st.write("77 类英文客服意图 · TF-IDF + 轻量分类器")
    st.caption("生成 → 隔离训练 → 独立验证 → 知识沉淀")
    st.info("Mock 使用固定模型响应；训练、预测和评分仍真实执行。")
    st.caption("当前为本机演示。客户流失保留 CLI 兼容验证；回归任务用于扩展验证。")

launch, reports, knowledge = st.tabs(["新建任务", "运行与报告", "知识与来源"])


def show_report(relative):
    paths = artifacts(ROOT, relative)
    report = read_json(paths["report.json"])
    validation = report.get("validation", {})
    status = STATUS.get(report["status"], report["status"])
    st.subheader(status)
    st.caption(
        f"{report.get('task_profile', '未识别')} · {report.get('provider_mode', '未知')} · {report['workflow_id']}"
    )
    if report.get("error_category"):
        st.error("停止原因：" + report["error_category"])
    if not report.get("persisted"):
        st.warning("知识库回写未完成；报告已保留，此运行不能视为完整成功。")
    if not report.get("test_attempted"):
        st.info("本次未运行最终测试。验证集成绩不代表最终测试通过。")
    columns = st.columns(4)
    for column, key, label in zip(
        columns,
        ("functional", "metrics", "stability", "interface"),
        ("功能", "指标", "稳定性", "接口"),
        strict=True,
    ):
        value = validation.get(key, {}).get("status", "not_run")
        column.metric(
            label, {"passed": "通过", "failed": "未通过", "not_run": "未执行"}.get(value, value)
        )
    measured = validation.get("validation_metrics", {})
    if measured:
        st.dataframe(
            [
                {
                    "指标": name,
                    "验证集": score,
                    "最终测试": validation.get("test_metrics", {}).get(name),
                    "冻结门槛": report.get("thresholds", {}).get(name),
                    "方向": "越低越好" if name in {"mae", "rmse"} else "越高越好",
                }
                for name, score in measured.items()
            ],
            hide_index=True,
            width="stretch",
        )
    if report.get("design_explanation"):
        with st.expander("算法设计依据"):
            explanation = report["design_explanation"]
            st.write(explanation["text"])
            st.caption(explanation["selection_basis"])
            st.json(
                {k: v for k, v in explanation.items() if k not in {"text", "selection_basis"}},
                expanded=False,
            )
    if report.get("attempts"):
        st.write("候选与修复版本")
        st.dataframe(report["attempts"], hide_index=True, width="stretch")
    usage = report.get("experience_usage")
    if usage:
        with st.expander("经验采用证据"):
            st.caption("模型声明、代码规则检查与实际评分分别记录；声明采用不表示效果提升。")
            st.json(usage, expanded=False)
    if "trace.json" in paths:
        with st.expander("运行轨迹", expanded=False):
            st.dataframe(read_json(paths["trace.json"]), hide_index=True, width="stretch")
    if "provider-usage.json" in paths:
        with st.expander("API 请求与用量"):
            st.json(read_json(paths["provider-usage.json"]))
    if "candidate.py" in paths:
        with st.expander("生成代码（只读）"):
            st.code(paths["candidate.py"].read_text(), language="python")
    for name in ("report.md", "report.json", "candidate.py"):
        if name in paths:
            st.download_button(
                "下载 "
                + {
                    "report.md": "中文报告",
                    "report.json": "结构化证据",
                    "candidate.py": "生成代码",
                }[name],
                paths[name].read_bytes(),
                file_name=name,
                key=relative + name,
            )


with launch:
    st.subheader("生成并验证算法")
    task = st.selectbox(
        "任务",
        ["banking77", "regression"],
        format_func=lambda x: {
            "banking77": "客服意图分类 · BANKING77",
            "regression": "扩展验证 · 合成回归",
        }[x],
    )
    mode = st.radio(
        "模型模式",
        ["mock", "api"],
        format_func=lambda x: "Mock · 无 API 费用" if x == "mock" else "Azure API · 使用本机配置",
        horizontal=True,
    )
    if mode == "api":
        st.info(
            "密钥仅从本机 .env 或环境变量读取，不在页面输入或显示。每次任务最多 12 次请求，具体费用以 Azure 账单为准。"
        )
    request = st.text_area(
        "开发需求",
        value=PROFILES[task].request,
        key="request_" + task + mode,
        disabled=mode == "mock",
        help="Mock 仅支持固定示例需求；真实 API 可理解同一输入协议下的需求。",
    )
    with st.form("new_task"):
        compare = st.checkbox(
            "比较两个候选并允许修复", value=task == "banking77", disabled=task != "banking77"
        )
        validation_only = st.checkbox(
            "仅验证集评估",
            value=True,
            help="关闭后，只有选定版本可进行一次最终测试；失败后不重选。",
        )
        experiences = st.checkbox(
            "使用适用的已验证经验",
            value=False,
            disabled=task != "banking77",
            help="使用 Phase 4 归档经验库；必须开启候选比较。适用范围严格匹配，未承诺性能收益。",
        )
        max_repairs = st.slider("每候选最多修复次数", 0, 2, 1)
        budget = st.number_input(
            "本次模型请求上限",
            min_value=1,
            max_value=12 if mode == "api" else 32,
            value=4 if mode == "api" else 24,
            step=1,
            key="budget_" + mode,
        )
        submitted = st.form_submit_button(
            "开始验证" if mode == "mock" else "开始 API 验证（产生费用）", type="primary"
        )
    if submitted:
        try:
            settings = RunSettings(
                task=task,
                mode=mode,
                compare=compare,
                validation_only=validation_only,
                experiences=experiences,
                max_repairs=max_repairs,
                call_budget=budget,
                request=request,
            )
            token = st.session_state.setdefault("submission_token", uuid.uuid4().hex)
            st.session_state["current_job"] = jobs.submit(settings, token)
            st.session_state["submission_token"] = uuid.uuid4().hex
            st.success("任务已提交。刷新页面不会重新提交；进度与报告在下方更新。")
        except (ValueError, OSError):
            st.error("无法提交：请检查配置。回归只支持单候选；经验复用需要候选比较。")

    @st.fragment(run_every="2s")
    def progress():
        identifier = st.session_state.get("current_job")
        if not identifier:
            return
        try:
            state = jobs.state(identifier)
            st.write("当前任务：" + STATUS.get(state["status"], state["status"]))
            st.caption(identifier)
            if state.get("error_category"):
                st.error(state["error_category"])
            trace_path = jobs.path(identifier) / "run/trace.json"
            if trace_path.is_file():
                trace = read_json(trace_path)
                if trace:
                    st.caption("最近进度：" + trace[-1]["reason"])
            if state["status"] in {"running", "queued"}:
                if st.button("停止当前任务"):
                    jobs.cancel(identifier)
                    st.warning("已请求停止，正在等待当前操作结束并保存状态。")
            else:
                st.caption(
                    "可在“运行与报告”查看结果。失败或中断的产物会保留；重新提交将创建独立运行，不续跑已预约的最终测试。"
                )
        except (ValueError, OSError):
            st.warning("暂时无法读取进度，请在运行列表中重新加载。")

    progress()

with reports:
    st.subheader("运行记录")
    if st.button("刷新运行列表"):
        st.rerun()
    identifiers = jobs.list()
    if identifiers:
        selected_job = st.selectbox("本地任务", identifiers)
        try:
            state = jobs.state(selected_job)
            st.write(STATUS.get(state["status"], state["status"]))
            if state.get("error_category"):
                st.error(state["error_category"])
            if st.button("恢复查看此任务"):
                st.session_state["current_job"] = selected_job
                st.success("已恢复进度查看；没有重新调用模型或测试。")
        except (ValueError, OSError):
            st.warning("此任务记录不可读取，已保留原始文件。")
    catalog = report_catalog(ROOT)
    if catalog:
        relative = st.selectbox(
            "查看报告", list(reversed(catalog)), help="历史档案与本次运行明确分开，不会重写归档。"
        )
        try:
            show_report(relative)
        except (ValueError, OSError, KeyError):
            st.error("报告不完整或无法读取，不能据此确认验收。")
    else:
        st.info("尚无报告。完成首个任务后可在此查看与下载。")

with knowledge:
    st.subheader("知识图谱与来源")
    choices = ["examples/phase4/library.sqlite"]
    choices += [
        str((jobs.path(i) / "knowledge.sqlite").relative_to(ROOT))
        for i in jobs.list()
        if (jobs.path(i) / "knowledge.sqlite").is_file()
    ]
    choices = [p for p in choices if confined(ROOT, p).is_file()]
    if choices:
        choice = st.selectbox("知识库", choices)
        try:
            snapshot = graph_snapshot(confined(ROOT, choice))
            types = sorted({e["type"] for e in snapshot["entities"]})
            if types:
                entity_type = st.selectbox(
                    "实体类型",
                    types,
                    index=types.index("Experience") if "Experience" in types else 0,
                )
                selected_entities = {
                    e["id"]: e for e in snapshot["entities"] if e["type"] == entity_type
                }
                focus = st.selectbox(
                    "实体",
                    list(selected_entities),
                    format_func=lambda k: selected_entities[k]["name"] + " · " + k[-18:],
                )
                dot, entity = graph_view(snapshot, focus)
                st.graphviz_chart(dot, width="stretch")
                st.caption(
                    "显示所选实体的一跳关系，最多 40 条。切换实体可追踪到实现、验证、失败与来源。"
                )
                st.json(entity, expanded=False)
                source = next(s for s in snapshot["sources"] if s["id"] == entity["source_id"])
                with st.expander("原始来源与引用"):
                    st.code(entity["source_span"]["quote"][:6000], language=None)
                    st.caption("来源 ID：" + source["id"])
                    st.caption("SHA-256：" + source["sha256"])
                    st.caption("长引用最多展示 6,000 字；完整来源保留在知识库。")
                st.download_button(
                    "下载图谱关系与实体 JSON",
                    json.dumps(snapshot, ensure_ascii=False, indent=2),
                    file_name="knowledge.json",
                )
            else:
                st.info("知识库暂时没有实体。")
        except Exception:
            st.error("知识库暂时不可读取；未修改原始档案。")
    else:
        st.info("完成任务后会出现可追溯知识。")
