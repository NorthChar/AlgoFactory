"""Run with: python -m streamlit run src/algofactory/web/app.py --server.address 127.0.0.1"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st

from algofactory.experiments import ExperimentConfig
from algofactory.tasks import PROFILES
from algofactory.web.data_view import show_data, show_errors
from algofactory.web.evidence import STEPS, stage_rows, workflow_evidence
from algofactory.web.models import show_trial
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
from algofactory.web.workflow_view import show_workflow, version_label

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


def stop_reason(category):
    if category == "call_budget_exhausted":
        return (
            "已达到本次模型请求次数上限，任务已停止。已完成的候选和报告已保留。"
            "请查看 API 请求与用量，再调整上限并手动提交新任务；系统不会自动扩额或续跑。"
            "（call_budget_exhausted）"
        )
    return category


st.set_page_config(page_title="AlgoFactory · 算法工作台", page_icon="◈", layout="wide")
st.title("AlgoFactory")
st.caption("提出算法需求 → 生成并验证 → 查看交付成果 → 试用本次算法")
jobs = Jobs(ROOT)
with st.sidebar:
    st.subheader("算法开发助手")
    st.write("帮助开发人员编写算法，并检查它能否运行、效果是否达标。")
    st.caption("一次开发任务，一条完整流程")
    st.info("当前是本机运行的案例原型，主案例为银行客服意图分类。")
    with st.expander("演示模式说明"):
        st.caption("Mock 使用固定模型响应；训练、预测和评分真实执行。真实 API 模式会产生费用。")


def navigate(destination, report=None):
    st.session_state["workspace_tab"] = destination
    if report:
        st.session_state["report_choice"] = report
        st.session_state.pop("pending_report", None)


# Submission occurs after tabs are instantiated. Apply its navigation on the next rerun.
if destination := st.session_state.pop("pending_navigation", None):
    st.session_state["workspace_tab"] = destination
if st.session_state.get("workspace_tab") not in {
    None,
    "从这里开始",
    "创建算法开发任务",
    "我的开发任务",
}:
    st.session_state["workspace_tab"] = "从这里开始"

intro, launch, reports = st.tabs(
    ["从这里开始", "创建算法开发任务", "我的开发任务"],
    key="workspace_tab",
    on_change="rerun",
)


def report_label(relative):
    titles = {
        "examples/api-phase3/comparison": "历史案例 · 真实 API 失败修复与最终测试",
        "examples/phase4/api-2-on": "历史案例 · 真实 API 经验复用（仅验证集）",
        "examples/phase3/repair": "历史案例 · Mock 注入故障后的修复",
        "examples/phase3/unsafe-code": "历史案例 · 危险代码被拒绝",
    }
    if relative in titles:
        return titles[relative]
    identifier = relative.split("/")[2]
    try:
        job = jobs.path(identifier)
        saved_path = job / "settings.json"
        if not saved_path.is_file():
            saved_path = job / "state.json"
        saved = datetime.fromtimestamp(saved_path.stat().st_mtime)
        # Keep option labels stable while the task is running; live status is in its detail.
        return f"本地任务 · {saved:%m-%d %H:%M} · {identifier[:8]}"
    except (OSError, ValueError, KeyError):
        return "本地任务 · " + identifier[:8]


def show_result(relative):
    paths = artifacts(ROOT, relative)
    report = read_json(paths["report.json"])
    if relative.startswith("examples/"):
        st.info("正在查看历史归档案例。这里只读取已有证据，不会调用 API，也不是你刚提交的任务。")
    else:
        st.caption("证据来源：" + report_label(relative))
    if report.get("experiment"):
        st.write("本次冻结的实验配置")
        st.json(report["experiment"], expanded=False)
        st.caption(
            "配置编号："
            + report["experiment_hash"]
            + (
                " · 单候选实验，不表示比较获胜"
                if report.get("candidate_mode") == "single"
                else " · 同一配置内比较"
            )
        )
    validation = report.get("validation", {})
    status = STATUS.get(report["status"], report["status"])
    st.subheader(status)
    st.caption(
        f"{report.get('task_profile', '未识别')} · {report.get('provider_mode', '未知')} · {report['workflow_id']}"
    )
    if report.get("error_category"):
        st.error("停止原因：" + stop_reason(report["error_category"]))
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
    st.subheader("本次生成的文件")
    st.caption(
        "下载代码和报告；在“开发过程”查看生成与修复依据，在“试用本次算法”检查交付模型。失败任务的文件也会保留，请结合状态判断。"
    )
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
    show_errors(ROOT, relative)
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


def show_report(relative):
    st.caption("下面的评估、代码、开发过程和试用模型均属于当前所选任务。")
    result_tab, process_tab, trial_tab = st.tabs(
        ["结果与交付", "开发过程", "试用本次算法"],
        key="task_section_" + relative,
        on_change="rerun",
    )
    with result_tab:
        show_result(relative)
    with process_tab:
        show_workflow(ROOT, relative)
    with trial_tab:
        show_trial(ROOT, relative)


with intro:
    st.subheader("你想开发什么算法？")
    st.write(
        "描述你需要的算法，系统帮你生成代码、运行验证，并交付可试用的结果。"
        "当前可通过 BANKING77 银行客服分类案例体验完整开发流程。"
    )
    st.button("体验银行客服分类示例", type="primary", on_click=navigate, args=("创建算法开发任务",))
    history = "examples/api-phase3/comparison"
    if history in report_catalog(ROOT):
        st.button("看一个已经完成的例子", on_click=navigate, args=("我的开发任务", history))
        st.caption(
            "打开已完成的真实 API 案例，查看生成的代码、报告与修复过程；只读查看，不产生费用。"
        )
    with st.container(border=True):
        st.markdown("### 举个例子：给银行客服做一个咨询分类算法")
        st.write(
            "银行收到很多英文咨询，需要判断客户在问银行卡、转账、退款等哪类问题，方便后续分流。"
        )
        left, right = st.columns(2)
        with left:
            st.markdown("**你提出的开发需求**")
            st.write("“帮我生成一个算法，根据英文客服咨询判断它属于哪类业务，并验证分类效果。”")
        with right:
            st.markdown("**做出来的算法要能做什么**")
            st.write("接收一段英文咨询，输出对应的意图类别及概率。")
            st.caption(
                "用途示意：‘I lost my card’ → 银行卡遗失/被盗。此处是说明示例，不是本次预测结果。"
            )
        st.caption("本案例的数据已经准备好：BANKING77，13,083 条英文咨询、77 类意图。")
    st.markdown("### 用完以后，你能拿到什么？")
    code_col, report_col, process_col = st.columns(3)
    code_col.markdown(
        "**① 算法代码**\n\n生成的 Python 文件，可交给开发人员在配套环境中使用和继续集成。"
    )
    report_col.markdown("**② 验证报告**\n\n说明代码能否运行、分类效果怎样、是否达到预定标准。")
    process_col.markdown(
        "**③ 开发过程记录**\n\n可以追查用了哪些知识、哪里出错、如何修复，以及各版本的结果。"
    )
    st.info(
        "银行客服分类是本次算法开发的示例：先创建任务，完成后在该任务中查看代码和报告、输入英文咨询试用成果。自有数据上传和任意新业务尚未接入。"
    )
    with st.expander("“七步流程”和这个用途有什么关系？"):
        st.write(
            "七步流程展示系统怎样完成一次开发任务：理解需求 → 查找相关知识 → 规划方案 → "
            "生成代码 → 测试效果 → 必要时修复 → 保存结果。你可以先看代码和报告，再展开过程检查依据。"
        )

with launch:
    st.subheader("创建算法开发任务")
    st.caption("① 确认需求与数据 → ② 选择开发设置 → ③ 提交后查看任务")
    st.write("描述你希望生成的算法能力，系统会生成代码并运行测试，保存整个过程的证据。")
    st.info(
        "当前支持预设案例及固定输入输出协议。这里填写算法开发需求；"
        "暂不支持上传自有数据或任意业务任务。提交后，生成过程、评估和试用会集中在同一个任务里。"
    )
    task = st.selectbox(
        "开发案例",
        ["banking77", "regression"],
        format_func=lambda x: {
            "banking77": "客服意图分类 · BANKING77",
            "regression": "扩展验证 · 合成回归",
        }[x],
    )
    st.write("**本次案例的输入与输出（预设范围，尚未调用模型）**")
    data_column, input_column, output_column = st.columns(3)
    if task == "banking77":
        data_column.markdown(
            "**数据**\n\nBANKING77 · 77 类英文客服意图\n\n官方训练集 10,003 条，测试集 3,080 条；训练集再划分验证集。"
        )
        input_column.markdown("**算法接收**\n\n含 `text` 列的英文咨询文本；标签字段为 `intent`。")
        output_column.markdown(
            "**算法输出**\n\n已知意图类别和各类别概率。\n\n工作台交付代码、评估报告与知识记录。"
        )
    else:
        data_column.markdown("**数据**\n\n预设合成回归数据，用于验证跨任务扩展。")
        input_column.markdown("**算法接收**\n\n数值特征 `x1`、`x2`、`x3`；目标字段为 `value`。")
        output_column.markdown(
            "**算法输出**\n\n连续数值；以 MAE、RMSE 评估。\n\n工作台交付代码、评估报告与知识记录。"
        )
    if task == "banking77":
        st.markdown("#### 本次使用的数据")
        st.write(
            "7,993 条训练咨询教算法识别意图；1,999 条验证咨询用于检查效果、比较和修复；"
            "3,080 条冻结测试咨询仅用于最终评估。这些数据训练的是生成的分类算法，不是 GPT。"
        )
        with st.expander("查看本次数据的真实样本与来源"):
            show_data(ROOT)
    with st.expander("第一次使用：这七步会发生什么？"):
        st.dataframe(
            [
                {"步骤": title, "你将看到": detail}
                for title, detail in zip(
                    STEPS,
                    (
                        "解析后的输入字段、目标与评价规则",
                        "检索到的能力知识及原始文档引用",
                        "预设候选范围内的方案、依赖和知识依据",
                        "可查看和下载的 Python 代码",
                        "功能、指标、稳定性、接口检查与候选比较",
                        "若触发修复，查看错误反馈、代码差异与复测结果",
                        "实现与验证记录回写，可在知识图谱追踪来源",
                    ),
                    strict=True,
                )
            ],
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "Mock 用固定模型响应演示流程；API 在既定任务协议内解析需求和生成代码。可通过“自主选择算法与参数”在已支持的候选范围内配置实验。"
        )
    historical = "examples/api-phase3/comparison"
    if historical in report_catalog(ROOT):
        st.button(
            "先看真实 API 完整历史案例（不产生费用）",
            on_click=navigate,
            args=("我的开发任务", historical),
        )
    st.markdown("#### 开发设置")
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
    custom = False
    experiment = None
    if task == "banking77":
        custom = st.toggle("自主选择算法与参数", value=False)
        if custom:
            st.write(
                "先选方案，再生成代码。以下选择会固定到本次实验，验证后不会自动改选另一套参数。"
            )
            algorithms = st.multiselect(
                "参与实验的算法",
                ["text_logistic", "text_nb"],
                default=["text_logistic", "text_nb"],
                format_func=lambda x: {
                    "text_logistic": "逻辑回归（Logistic Regression）",
                    "text_nb": "朴素贝叶斯（MultinomialNB）",
                }[x],
            )
            c1, c2 = st.columns(2)
            with c1:
                ngram = st.selectbox(
                    "文本特征",
                    [2, 1],
                    format_func=lambda x: "单词 + 相邻双词" if x == 2 else "仅单词",
                )
                max_features = st.selectbox("词表上限", [30000, 10000])
            with c2:
                logistic_c = st.selectbox(
                    "逻辑回归 C", [4.0, 1.0], help="数值越小，正则化越强。仅对逻辑回归生效。"
                )
                nb_alpha = st.selectbox(
                    "朴素贝叶斯平滑系数",
                    [0.1, 0.5],
                    help="控制少见词的平滑程度。若触发指标优化，最多按初始值、1/2、1/10 的预定顺序尝试。",
                )
            if algorithms:
                experiment = ExperimentConfig(
                    algorithms=algorithms,
                    ngram_max=ngram,
                    max_features=max_features,
                    logistic_c=logistic_c,
                    nb_alpha=nb_alpha,
                )
                st.caption(
                    "配置编号："
                    + experiment.digest[:16]
                    + "。不同实验的结果分别呈现，不合并成跨配置排行榜。"
                )
            else:
                st.warning("至少选择一个算法才能提交。")
            st.caption(
                "配置实验使用固定的 BANKING77 业务描述；算法与参数通过以上控件设置。首版不解释任意文字中的额外参数约束。"
            )
    request = st.text_area(
        "开发需求",
        value=PROFILES[task].request,
        key="request_" + task + mode + ("_configured" if custom else ""),
        disabled=mode == "mock" or custom,
        help="Mock 仅支持固定示例需求；真实 API 可理解同一输入协议下的需求。",
    )
    st.caption("示例描述的是需要生成的算法能力；仅修改文字不会改变预设的数据字段、类别或验证门槛。")
    with st.form("new_task"):
        compare = st.checkbox(
            "比较两个候选并允许修复",
            value=(len(algorithms) == 2 if custom else task == "banking77"),
            disabled=task != "banking77" or custom,
            key=("compare_custom_" + str(len(algorithms)))
            if custom
            else "compare_baseline_" + task,
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
            value=10 if mode == "api" else 24,
            step=1,
            key="budget_" + mode,
        )
        if mode == "api":
            st.caption(
                "无重试、无修复时：单候选需要 4 次请求；双候选通常需要 7 次，"
                "成功复用知识时为 6 次。每次代码修复另需 3 次，接口重试也计入上限。"
                "10 次可为普通双候选预留一次修复；12 次上限不保证覆盖全部修复。"
                "上限不是固定消耗，训练和最终测试不调用模型。"
            )
        submitted = st.form_submit_button(
            "开始生成并验证" if mode == "mock" else "开始 API 生成并验证（产生费用）",
            type="primary",
        )
    if submitted:
        try:
            if custom and experiment is None:
                raise ValueError("select_at_least_one_algorithm")
            settings = RunSettings(
                experiment=experiment,
                task=task,
                mode=mode,
                compare=compare,
                validation_only=validation_only,
                experiences=experiences,
                max_repairs=max_repairs,
                call_budget=budget,
                request=request,
            )
            minimum = (6 if experiences else 7) if compare else 4
            if mode == "api" and budget < minimum:
                st.error(
                    f"尚未提交：当前配置即使无重试、无修复也至少需要 {minimum} 次请求，"
                    f"你设置了 {budget} 次。请调整请求上限，或关闭候选比较后重新提交。"
                    "本次未启动任务、未调用 API。"
                )
            else:
                token = st.session_state.setdefault("submission_token", uuid.uuid4().hex)
                st.session_state["current_job"] = jobs.submit(settings, token)
                st.session_state["pending_report"] = f"runtime/web-jobs/{token}/run"
                st.session_state["submission_token"] = uuid.uuid4().hex
                st.session_state["pending_navigation"] = "我的开发任务"
                st.session_state["submission_notice"] = token
                st.rerun()
        except (ValueError, OSError):
            st.error(
                "无法提交：请检查候选与参数。配置实验使用固定业务描述；回归只支持单候选；经验复用需要比较流程。"
            )


def show_requirement(relative):
    """Show the original request alongside the selected task, including before a report exists."""
    request = None
    if relative.startswith("runtime/web-jobs/"):
        settings_path = jobs.path(relative.split("/")[2]) / "settings.json"
        if settings_path.is_file():
            settings = read_json(settings_path)
            request = settings.get("request") or PROFILES[settings["task"]].request
    else:
        evidence = workflow_evidence(ROOT, relative)
        request = next(
            (
                b["task.json"].get("description")
                for b in evidence["versions"].values()
                if b.get("task.json")
            ),
            None,
        )
    if request:
        st.markdown("**本次开发需求**")
        st.write(request)


def task_detail(relative, was_active=False):
    try:
        if relative.startswith("runtime/web-jobs/"):
            identifier = relative.split("/")[2]
            state = jobs.state(identifier)
            if was_active and state["status"] not in {"running", "queued"}:
                st.rerun()  # Stop polling once the task ends; keep trial results visible.
            st.subheader("当前任务：" + STATUS.get(state["status"], state["status"]))
            st.caption("任务编号：" + identifier)
            if state.get("error_category"):
                st.error(stop_reason(state["error_category"]))
            if state["status"] in {"running", "queued"}:
                st.info("系统正在完成这次开发。进度会自动更新；刷新页面不会重新提交。")
                if st.button("停止当前任务", key="stop_" + identifier):
                    jobs.cancel(identifier)
                    st.warning("已请求停止，正在等待当前操作结束并保存状态。")
            elif relative not in report_catalog(ROOT):
                st.warning("任务已结束但尚无完整报告。已保存产物保留在下方，不能据此确认验收。")
        show_requirement(relative)
        if relative in report_catalog(ROOT):
            show_report(relative)
        else:
            evidence = workflow_evidence(ROOT, relative)
            versions = evidence["versions"]
            if versions:
                latest = next(reversed(versions))
                st.caption("当前版本：" + version_label(latest))
                st.dataframe(
                    stage_rows(
                        versions[latest], terminal=state["status"] not in {"running", "queued"}
                    ),
                    hide_index=True,
                    width="stretch",
                )
            st.caption(
                "完成后，结果、交付文件和试用入口会在本任务中出现。无需到另一个页面寻找模型。"
            )
    except (ValueError, OSError, KeyError):
        st.error("此任务的部分记录不完整或无法读取，不能据此确认验收。原始文件已保留。")


with reports:
    st.subheader("我的开发任务")
    st.write("选择一次开发，查看它的需求、进度、交付结果，再试用这次生成的算法。")
    if st.button("刷新任务列表"):
        st.rerun()
    local = [f"runtime/web-jobs/{identifier}/run" for identifier in jobs.list()]
    local.sort(
        key=lambda p: (jobs.path(p.split("/")[2]) / "state.json").stat().st_mtime, reverse=True
    )
    catalog = local + [p for p in report_catalog(ROOT) if p not in local]
    pending = st.session_state.pop("pending_report", None)
    if pending in catalog:
        st.session_state["report_choice"] = pending
    if catalog:
        if st.session_state.get("report_choice") not in catalog:
            st.session_state["report_choice"] = catalog[0]
        labels = {path: report_label(path) for path in catalog}
        relative = st.selectbox(
            "选择开发任务",
            catalog,
            format_func=labels.__getitem__,
            key="report_choice",
            help="进度、报告和试用均绑定此任务。历史案例只读浏览，不会重新运行。",
        )
        if st.session_state.pop("submission_notice", None):
            st.success("开发任务已提交，已打开本次任务。刷新不会重复提交。")
        active = relative in local and jobs.state(relative.split("/")[2])["status"] in {
            "running",
            "queued",
        }
        st.fragment(task_detail, run_every="2s" if active else None)(relative, active)
    else:
        st.info("还没有开发任务。先创建一个任务，完成后这里会显示代码、报告和算法试用入口。")
        st.button("创建第一个开发任务", on_click=navigate, args=("创建算法开发任务",))

with st.sidebar.expander("辅助工具 · 知识与来源"):
    st.subheader("知识图谱与来源")
    choices = ["examples/phase4/library.sqlite"]
    choices += [
        str((jobs.path(i) / "knowledge.sqlite").relative_to(ROOT))
        for i in jobs.list()
        if (jobs.path(i) / "knowledge.sqlite").is_file()
    ]
    choices = [p for p in choices if confined(ROOT, p).is_file()]
    if choices:
        selected_report = st.session_state.get("report_choice", "")
        current_db = selected_report.removesuffix("/run") + "/knowledge.sqlite"
        choice = st.selectbox(
            "知识库",
            choices,
            index=choices.index(current_db) if current_db in choices else 0,
            format_func=lambda p: (
                "历史经验库 · Phase 4"
                if p.startswith("examples/")
                else "本地任务 · " + p.split("/")[2]
            ),
        )
        st.caption("历史经验库与本次任务的回写记录分开保存，请核对所选任务。")
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
