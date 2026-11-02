"""Run with: python -m streamlit run src/algofactory/web/app.py --server.address 127.0.0.1"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st

from algofactory.requirements import EXAMPLE_REQUEST, LABELS, interpret_requirement
from algofactory.tasks import PROFILES
from algofactory.web.data_view import show_data, show_errors
from algofactory.web.evidence import stage_rows, workflow_evidence
from algofactory.web.models import show_trial
from algofactory.web.requirement_intake import NATURAL_EXAMPLE, show_semantic_intake
from algofactory.web.service import (
    WEB_API_CALL_LIMIT,
    Jobs,
    RunSettings,
    artifacts,
    confined,
    generation_budget,
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
    messages = {
        "call_budget_exhausted": "本次大模型请求已达到设置上限，任务已停止，已有成果已保留。请查看用量和已保留成果，再决定是否调整预算并创建新任务；系统不会自动加额或续跑。",
        "docker_missing": "电脑上尚未找到 Docker。请让环境配置人员安装并启动 Docker Desktop 后，再创建新任务。",
        "docker_unavailable": "训练环境暂时无法连接。请先启动 Docker Desktop，等待就绪后再创建新任务。",
        "sandbox_image_missing": "本机缺少执行镜像。请让环境配置人员按 README 的镜像准备步骤处理后重试。",
        "sandbox_image_not_prepared": "执行环境尚未准备完成。请让环境配置人员按 README 准备本机镜像。",
        "sandbox_image_stale": "执行环境与当前代码版本不一致。请让环境配置人员按 README 重新准备镜像。",
        "dataset_not_prepared": "训练材料尚未导入。请让环境配置人员按 README 导入数据后再开始。",
        "worker_interrupted": "任务运行中断，已有文件已保留。请查看任务记录；需要继续时手动创建新任务，刷新不会续跑。",
        "another_job_running": "已有另一个任务正在运行。请等待它完成，再创建新任务。",
    }
    return messages.get(
        category,
        "本次开发未能完成，已有记录已保留。请在“开发过程”查看原因，或把下方技术信息交给配置人员；不要连续点击重试。",
    )


def show_failure(category):
    st.error(stop_reason(category))
    with st.expander("技术信息（供排查使用）"):
        st.code(category, language=None)


def open_trial(relative):
    st.session_state["task_section_" + relative] = "试用本次算法"


st.set_page_config(page_title="AlgoFactory · 银行咨询分类算法开发", page_icon="◈", layout="wide")
st.title("AlgoFactory")
st.caption("银行咨询分类算法开发 · 生成代码 → 训练与验证 → 修复与交付")
jobs = Jobs(ROOT)
with st.sidebar:
    st.subheader("银行咨询分类算法开发")
    st.write("开发一个识别英文银行咨询意图的分类器，交付代码、模型与验证报告。")
    st.caption("一次开发任务，一条完整流程")
    st.info("支持英文银行咨询的全部类别、指定类别及单个意图识别。其他业务任务仅作兼容性检查。")
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
        "examples/banking-classification/comparison": "历史案例 · 真实 API 失败修复与最终测试",
        "examples/experience-reuse/run": "历史案例 · 真实 API 经验复用（仅验证集）",
        "examples/mock-repair": "历史案例 · Mock 注入故障后的修复",
        "examples/rejected-code": "历史案例 · 危险代码被拒绝",
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
    if report.get("selection"):
        from algofactory.intent_catalog import intent_title
        from algofactory.web.task_goals import GOALS

        scope = report["selection"]
        st.info(GOALS[scope["goal"]] + "：" + "；".join(intent_title(n) for n in scope["intents"]))
        if scope["goal"] == "subset":
            st.warning("仅在选定类别范围内训练和评估；不识别范围外咨询。")
        else:
            st.caption("负类仅包含其余 76 类已知咨询；不代表未知意图检测。")
    validation = report.get("validation", {})
    if (
        report.get("selection", {}).get("goal") == "one_vs_rest"
        and "validation-class-details.json" in paths
    ):
        matrix = read_json(paths["validation-class-details.json"])["confusion_matrix"]
        left, right = st.columns(2)
        left.metric("验证集漏判：本应识别却漏掉", matrix[1][0])
        right.metric("验证集误报：其他咨询被误判为目标", matrix[0][1])
        st.caption(
            f"验证样本：目标意图 {sum(matrix[1])} 条，其他已知意图 {sum(matrix[0])} 条；这些数量不能外推为真实客户比例。"
        )
    status = STATUS.get(report["status"], report["status"])
    st.subheader(status)
    st.caption(
        f"{report.get('task_profile', '未识别')} · {report.get('provider_mode', '未知')} · {report['workflow_id']}"
    )
    if report.get("error_category"):
        show_failure(report["error_category"])
    if not report.get("persisted"):
        st.warning("知识库回写未完成；报告已保留，此运行不能视为完整成功。")
    if not report.get("test_attempted"):
        st.info("本次未运行最终测试。验证集成绩不代表最终测试通过。")
    if report["status"] in {"accepted", "validated"} and report.get("persisted"):
        st.success("本次代码已生成，并通过报告所列的运行与效果检查。")
        st.write(
            "你可以下载代码与报告，也可以先输入一条咨询试用成果。通过检查不保证每句话都分类正确。"
        )
        if report.get("task_profile") == "banking77":
            st.button(
                "输入咨询，试用本次成果",
                key="open_trial_" + relative,
                on_click=open_trial,
                args=(relative,),
                type="primary",
            )
    elif report["status"] not in {"accepted", "validated"}:
        st.warning("本次尚未交付通过验证的算法。先查看原因与开发过程，不能把已有代码当成合格成果。")
    with st.expander("查看检查项目与评分（技术详情）"):
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
    st.subheader("代码与交付物")
    st.caption(
        "下载代码和报告；在“开发过程”查看生成与修复依据，在“试用本次算法”检查交付模型。失败任务的文件也会保留，请结合状态判断。"
    )
    if "candidate.py" in paths:
        with st.expander("查看本次生成的 Python 代码", expanded=False):
            st.code(paths["candidate.py"].read_text(), language="python")
        st.caption("代码定义分类流水线，需在项目配套环境中训练和运行；它不是独立的客服网站。")
    for name in ("candidate.py", "report.md", "report.json", "data-manifest.json"):
        if name in paths:
            st.download_button(
                "下载 "
                + {
                    "report.md": "中文报告",
                    "report.json": "结构化证据",
                    "candidate.py": "生成代码",
                    "data-manifest.json": "本次标签与数据配置",
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
        with st.expander("候选与修复版本（技术详情）"):
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
    st.subheader("开发银行咨询分类算法，获得经过验证的代码")
    st.write(
        "这个工作台开发英文银行咨询分类算法：可区分全部意图、指定的几个类别，或识别某一种意图。"
        "系统检索算法知识、生成代码，实际训练和评估，必要时修复，最后保存代码、报告和开发记录。"
    )
    st.caption(
        "这是项目完整落地的业务案例，用于展示算法开发闭环；当前不支持任意业务需求或自有数据上传。"
    )
    st.info(
        "操作顺序：① 描述支持范围内的开发需求 → ② 核对并确认配置 → ③ 生成、验证和试用成果。无需编写代码。"
    )
    st.button("开始开发银行分类算法", type="primary", on_click=navigate, args=("创建算法开发任务",))
    history = "examples/banking-classification/comparison"
    if history in report_catalog(ROOT):
        st.button("查看已完成的银行分类开发任务", on_click=navigate, args=("我的开发任务", history))
        st.caption("查看历史真实 API 生成代码、错误修复与最终测试证据；只读浏览，不产生费用。")
    with st.container(border=True):
        st.markdown("### 你提出开发需求，系统交付分类算法")
        left, right = st.columns(2)
        with left:
            st.markdown("**第一步：告诉系统要开发什么**")
            st.write("“识别英文咨询中银行卡丢失或被盗的问题，优先减少漏判，并告诉我误报情况。”")
            st.caption(
                "这是开发需求。可选择全部类别、已有类别的子集，或单个意图识别；输入语言仍为英文。"
            )
        with right:
            st.markdown("**完成后：用一条咨询试用成果**")
            st.write("例如输入：I lost my bank card.")
            st.caption(
                "用途示意：希望识别为银行卡丢失或被盗；这不是实际预测结果，也不是新的开发需求。"
            )
    st.markdown("### 交付什么？")
    code_col, report_col, process_col = st.columns(3)
    code_col.markdown(
        "**① 算法代码**\n\n可查看和下载的 Python 分类流水线，在配套环境中训练、运行和继续集成。"
    )
    report_col.markdown(
        "**② 验证报告**\n\n说明代码能否运行、分类效果怎样、是否达到预定标准。通过版本的模型可在任务内试用。"
    )
    process_col.markdown(
        "**③ 开发过程记录**\n\n追查知识来源、方案、错误与修复、各版本结果，以及知识回写。"
    )
    st.markdown("### 为什么还需要数据？")
    st.write(
        "代码生成后必须实际运行，才能判断是否可用。我们已准备带正确类别的咨询："
        "一部分用于训练分类器，一部分用于检查预测是否正确。你无需先了解数据集或自行准备数据。"
    )
    st.caption(
        "GPT 负责生成或修复代码；生成的分类器从咨询数据中学习，再处理新咨询。两者不是同一个模型。"
    )
    with st.expander("了解数据来源和当前支持范围"):
        st.write(
            "数据来源为 BANKING77，原始共 13,083 条英文咨询、77 类已知意图。"
            "它提供咨询和正确类别，不是客服回答库；本任务不自动回复、办理银行业务或识别未知意图。"
        )
        st.write(
            "可以用自己的话描述需求，由大模型理解和复核；也可使用免费离线示例。方案需要确认，Mock 或 API 再据此生成代码。"
        )
        st.caption("合成回归和客户流失用于公共框架兼容性检查，不代表已完成同等范围的业务产品。")
    with st.expander("系统怎样完成一次算法开发？"):
        st.write(
            "理解需求 → 检索相关知识 → 规划方案 → 生成代码 → 训练与评估 → 必要时修复 → 保存并回写结果。"
            "完成后先查看代码与报告，再试用本次生成的分类器。"
        )

with launch:
    st.subheader("描述需求 → 核对配置 → 确认后生成")
    with st.expander("开发者设置：开发案例"):
        task = st.selectbox(
            "开发案例",
            ["banking77", "regression"],
            format_func=lambda x: (
                "银行咨询分类 · 当前完整业务任务" if x == "banking77" else "合成回归 · 仅兼容性检查"
            ),
        )
    st.markdown("### 1. 描述你要开发的算法")
    st.info(
        "选择要解决的分类问题，再描述需求。系统将据此筛选数据、定义输出、生成并验证代码。仍使用已有英文咨询，不支持中文、自有数据或新增业务标签。"
    )
    from algofactory.experiments import ExperimentConfig
    from algofactory.requirement_understanding import configuration_request
    from algofactory.web.task_goals import GOALS, choose_goal, show_scope

    selection = (
        choose_goal()
        if task == "banking77"
        else {"goal": "full", "intents": [], "objective": "macro_f1"}
    )
    selection_valid = selection["goal"] != "subset" or 2 <= len(selection["intents"]) <= 76
    if not selection_valid:
        st.warning("请先选择 2–76 个类别。")
    intake = st.radio(
        "需求理解方式",
        ["natural", "rules"],
        format_func=lambda x: (
            "用自己的话描述（大模型理解，产生费用）"
            if x == "natural"
            else "离线示例与固定表达（不产生 API 费用）"
        ),
        disabled=task != "banking77",
    )
    natural = task == "banking77" and intake == "natural"
    example = NATURAL_EXAMPLE if natural else EXAMPLE_REQUEST
    if selection_valid and selection["goal"] != "full":
        example = configuration_request(ExperimentConfig(**selection))
        if natural:
            from algofactory.intent_catalog import INTENTS

            names = "、".join(INTENTS[n] for n in selection["intents"])
            example = (
                (
                    (
                        "我想将英文银行咨询分为这些已有类别："
                        + names
                        + "。只处理这些类别范围内的咨询，输出类别和概率。"
                    )
                    if selection["goal"] == "subset"
                    else ("我想判断英文银行咨询是否涉及" + names + "，输出属于或不属于及概率。")
                )
                + (
                    "优先减少漏判，并报告误报情况。"
                    if selection["objective"] == "recall"
                    else "请兼顾识别效果与误报。"
                )
                + "我不懂算法，请帮我比较合适的方案。"
            )
    request = st.text_area(
        "开发需求",
        value=example if task == "banking77" else PROFILES[task].request,
        key="requirement_text_" + task + intake + str(selection),
        disabled=task != "banking77",
        height=140,
        help="说明你要解决的问题、输入输出和限制。不需要指定算法，系统会提出方案供你确认。",
    )
    understanding = None
    experiment = None
    result = None
    checked = False
    if natural:
        result, understanding = show_semantic_intake(ROOT, request)
        checked = result is not None
        experiment = result.experiment if result else None
    else:
        with st.expander("目前能理解的需求表达（用分号或换行分隔）"):
            st.write(
                "离线入口使用本地规则逐句检查，不是通用自然语言理解。可以按下列表达组合；任何未识别的句子都会阻止提交，不会被忽略。"
            )
            st.code(
                "开发英文银行咨询分类算法；输出预测类别及概率\n只区分这些意图：card_arrival、lost_or_stolen_card / 识别单个意图：lost_or_stolen_card\n单个意图可加：优先减少漏判 / 兼顾各类效果\n只使用逻辑回归 / 只使用朴素贝叶斯 / 比较逻辑回归和朴素贝叶斯\n仅使用单词特征 / 使用单词和相邻双词特征\n词表上限10000 / 词表上限30000\n逻辑回归C=1 / 逻辑回归C=4\n朴素贝叶斯平滑系数=0.1 / 朴素贝叶斯平滑系数=0.5",
                language=None,
            )
            st.caption(
                "每行中的 / 表示可选项，不要原样全部粘贴。未指定的选项会在确认页标为默认值。更自由的表述目前需要改写，不会猜测。"
            )
        if st.session_state.get("last_requirement_input") != (task, request):
            st.session_state.pop("checked_requirement", None)
            st.session_state["last_requirement_input"] = (task, request)
        if st.button("解析并检查需求", type="primary"):
            st.session_state["checked_requirement"] = (task, request)
        checked = st.session_state.get("checked_requirement") == (task, request)
        experiment = None
        result = None
        if checked and task == "banking77":
            result = interpret_requirement(request)
            experiment = result.experiment
    if experiment and experiment.selection() != selection:
        st.error(
            "需求理解得到的目标、类别或评估偏好与上方选择不一致。请修改选择或需求并重新理解；不能按默认任务执行。"
        )
        experiment = None
    ready = selection_valid and checked and (task == "regression" or experiment is not None)
    st.markdown("### 2. 核对系统将执行的配置")
    if not checked:
        st.info("请先完成上方的需求理解或离线检查；不会自动开始生成代码。")
    elif result and result.issues:
        for issue in result.issues:
            st.error(issue)
        st.warning("本次需求尚不能执行。请修改或补充后重新检查；未创建代码生成任务。")
    elif experiment:
        rows = []
        for name, label in LABELS.items():
            if name == "logistic_c" and "text_logistic" not in experiment.algorithms:
                continue
            if name == "nb_alpha" and "text_nb" not in experiment.algorithms:
                continue
            value = getattr(experiment, name)
            if name == "goal":
                value = GOALS[value]
            elif name == "intents":
                from algofactory.intent_catalog import intent_title

                value = "；".join(intent_title(n) for n in value) or "全部 77 类"
            elif name == "objective":
                value = "优先减少漏判" if value == "recall" else "兼顾各类效果"
            elif name == "algorithms":
                value = "、".join(
                    "逻辑回归" if a == "text_logistic" else "朴素贝叶斯" for a in value
                )
            elif name == "ngram_max":
                value = "仅单词" if value == 1 else "单词和相邻双词"
            rows.append(
                {
                    "配置": label,
                    "执行值": str(value),
                    "来源": ("模型从需求提取，请核对" if natural else "用户明确指定")
                    if name in result.explicit
                    else ("系统建议，请确认" if natural else "系统默认，请确认"),
                }
            )
        st.table(rows)
        show_scope(ROOT, experiment)
        if "text_nb" in experiment.algorithms:
            st.caption(
                "修复规则：若指标不达标且允许修复，朴素贝叶斯平滑系数可按初始值、1/2、1/10 的预定顺序优化；最终测试不参与调参。"
            )
    elif ready:
        st.info("合成回归仅作固定兼容性检查，不提供自由需求解析。")

    mode = st.radio(
        "代码生成方式",
        ["mock", "api"],
        format_func=lambda x: (
            "使用模板生成代码（此步不产生 API 费用）"
            if x == "mock"
            else "使用大模型生成代码（产生费用）"
        ),
    )
    if mode == "mock":
        st.caption(
            "代码生成选择 Mock：按已确认配置生成模板代码，训练和评分真实执行；自然语言理解步骤的 API 费用仍单独计算。"
        )
    else:
        st.warning(
            "确认并开始后才调用代码生成 API。此处预算只用于代码生成流程，不包含上方自然语言理解请求；不会自动扩大预算。"
        )
    with st.expander("开发者设置：评估、修复与预算"):
        compare = bool(experiment and len(experiment.algorithms) == 2)
        st.caption("候选比较由已解析的需求决定。单候选也可在预算内自动修复。")
        validation_only = st.checkbox(
            "仅验证集评估",
            value=True,
            help="关闭后，只有选定版本可进行一次最终测试；失败后不重选。",
        )
        experiences = st.checkbox(
            "使用适用的已验证经验",
            value=False,
            disabled=task != "banking77" or selection["goal"] != "full",
        )
        max_repairs = st.slider("每候选最多修复次数", 0, 2, 1, disabled=task != "banking77")
        base_calls, repair_calls = generation_budget(compare, max_repairs, task)
        recommended = base_calls + repair_calls
        manual_budget = st.checkbox("手动设置请求上限", value=False, key="manual_budget_" + mode)
        budget_key = "budget_" + mode
        if not manual_budget or budget_key not in st.session_state:
            st.session_state[budget_key] = recommended if mode == "api" else 24
        budget = st.number_input(
            "本次模型请求上限",
            min_value=1,
            max_value=WEB_API_CALL_LIMIT if mode == "api" else 32,
            step=1,
            key=budget_key,
            disabled=not manual_budget,
        )
        st.caption(
            f"建议额度 {recommended} 次 = 首次生成 {base_calls} 次 + 修复预留 {repair_calls} 次。"
            "按所有候选用完所选修复次数估算；命中已有知识可少 1 次，接口重试另占额度。"
            "成功后无需用完预留次数，修复次数不是成功保证。训练、评分和试用不调用大模型。"
        )
        if mode == "api" and budget < recommended:
            st.warning(
                f"当前上限 {budget} 次低于建议的 {recommended} 次，可能在完成所选修复前停止。"
                "你可以保留较低上限；系统不会在运行中自动加额。"
            )
        if mode == "api":
            st.caption("生成流程最多允许 24 次请求；需求理解另计，最多 6 次。建议额度不含接口重试余量。")
    st.markdown("### 3. 确认并开始生成")
    st.write(
        f"本次：{'真实 API（付费）' if mode == 'api' else 'Mock 模板生成（无 API 费用）'}；{'仅验证集评估' if validation_only else '选定版本追加一次最终测试'}；每候选最多修复 {max_repairs if task == 'banking77' else 0} 次；请求上限 {budget} 次；{'使用已验证经验' if experiences else '不复用历史经验'}。"
    )
    payload = dict(
        understanding=understanding if natural else None,
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
    # The digest binds confirmation to all current inputs, including spending limits.
    draft = RunSettings.model_construct(**payload)
    digest = draft.confirmation_digest()
    if st.session_state.get("last_confirmation_digest") != digest:
        st.session_state["confirmed_current_requirement"] = False
        st.session_state["last_confirmation_digest"] = digest
    confirmed = st.checkbox(
        "我已核对需求、默认值和运行设置，确认按以上配置执行",
        key="confirmed_current_requirement",
        disabled=not ready,
    )
    submitted = st.button(
        "开始生成并验证" if mode == "mock" else "开始 API 生成并验证（产生费用）",
        type="primary",
        disabled=not (ready and confirmed),
    )
    if submitted:
        try:
            if not ready or not confirmed:
                raise ValueError("requirement_needs_confirmation")
            settings = RunSettings(**payload, requirement_confirmation=digest)
            minimum = (6 if experiences else 7) if compare else 4
            if mode == "api" and budget < minimum:
                st.error(
                    f"尚未提交：当前配置至少需要 {minimum} 次请求，你设置了 {budget} 次。请调整后重新确认；未调用 API。"
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
            st.error("无法提交：需求、配置或确认已失效，请重新检查并确认。未自动替换为默认任务。")
    with st.expander("了解训练材料和系统怎样完成任务"):
        st.write(
            "需求和算法知识指导代码生成；带标签的数据用于训练分类器和检查效果，不用于微调 GPT。"
        )
        if task == "banking77":
            show_data(ROOT)
        st.write(
            "理解需求 → 检索知识 → 规划方案 → 生成代码 → 训练与检查 → 必要时修复 → 保存并回写结果。"
        )
        historical = "examples/banking-classification/comparison"
        if historical in report_catalog(ROOT):
            st.button(
                "先看真实 API 完整历史案例（不产生费用）",
                on_click=navigate,
                args=("我的开发任务", historical),
            )


def show_requirement(relative):
    """Show the original request alongside the selected task, including before a report exists."""
    request = None
    if relative.startswith("runtime/web-jobs/"):
        settings_path = jobs.path(relative.split("/")[2]) / "settings.json"
        if settings_path.is_file():
            settings = read_json(settings_path)
            request = settings.get("request") or PROFILES[settings["task"]].request
            if settings.get("understanding"):
                for answer in settings["understanding"].get("answers", []):
                    st.write("**用户补充：** " + answer)
                with st.expander("确认后的执行要求与方案"):
                    st.write(settings["understanding"]["proposal"]["summary"])
                    st.json(settings["experiment"])
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
                show_failure(state["error_category"])
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
                bundle = versions[latest]
                if state["status"] in {"running", "queued"}:
                    if bundle.get("candidate.py"):
                        progress = "代码已生成，正在继续检查与评估；请等待报告。"
                    elif bundle.get("plan.json"):
                        progress = "方案已准备，正在继续生成代码。"
                    elif bundle.get("task.json"):
                        progress = "需求已整理，正在继续准备算法方案。"
                    else:
                        progress = "任务已收到，正在准备开发流程。"
                    st.info(progress)
                with st.expander("查看已产生的步骤记录（技术详情）"):
                    st.dataframe(
                        stage_rows(bundle, terminal=state["status"] not in {"running", "queued"}),
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
    st.write("第 3 步：查看成果。任务完成后先看是否通过，再试用或下载代码；运行中请等待进度更新。")
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
    choices = ["examples/experience-reuse/library.sqlite"]
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
