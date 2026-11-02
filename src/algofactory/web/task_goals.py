"""Business goal selection and read-only scope preview."""

import streamlit as st

from algofactory.intent_catalog import INTENTS, intent_title
from algofactory.web.data_view import dataset_snapshot, samples

GOALS = {
    "full": "完整意图分类 · 区分全部 77 类",
    "subset": "指定类别分类 · 只区分选中的类别",
    "one_vs_rest": "单个意图识别 · 判断属于或不属于",
}


def choose_goal():
    goal = st.radio("你要开发哪一种算法？", list(GOALS), format_func=GOALS.get)
    names = []
    objective = "macro_f1"
    if goal == "subset":
        names = sorted(
            st.multiselect(
                "需要区分哪些咨询？选择 2–76 类",
                list(INTENTS),
                default=["card_arrival", "lost_or_stolen_card", "pending_transfer"],
                format_func=intent_title,
            )
        )
        st.warning(
            "仅适用于这些类别范围内的咨询。其他类别不会用于训练或评估，也不会被自动识别为“其他”。"
        )
    elif goal == "one_vs_rest":
        names = [
            st.selectbox(
                "要识别哪一种咨询？",
                list(INTENTS),
                index=list(INTENTS).index("lost_or_stolen_card"),
                format_func=intent_title,
            )
        ]
        objective = st.radio(
            "你更重视什么？",
            ["macro_f1", "recall"],
            format_func=lambda v: (
                "兼顾识别效果与误报" if v == "macro_f1" else "优先减少漏判，同时查看误报"
            ),
        )
        st.info(
            "正类：所选意图；负类：其余 76 类已有咨询。它不能判断任意新业务，也不能识别交易本身是否存在风险。"
        )
    st.caption(
        "中文名称为项目提供的辅助说明，实际训练使用原始英文标签。可以在下方说明更多要求；文字和选择冲突时需要澄清。"
    )
    return {"goal": goal, "intents": names, "objective": objective}


def show_scope(root, config):
    st.write("**本次任务：**" + GOALS[config.goal])
    try:
        _, manifest, audit = dataset_snapshot(root)
        counts = audit["class_counts"]
        chosen = [str(manifest["class_names"].index(n)) for n in config.intents]
        if config.goal == "subset":
            sizes = {s: sum(counts[s][i] for i in chosen) for s in counts}
        else:
            sizes = audit["split_counts"]
        st.caption(
            "数据用途：训练 {} 条 · 验证 {} 条 · 最终测试 {} 条（只有显式开启才运行）。保留原数据划分，按本次目标筛选或转换标签。".format(
                sizes["train"], sizes["validation"], sizes["test"]
            )
        )
        if config.goal == "one_vs_rest":
            st.table(
                [
                    {
                        "数据用途": s,
                        "所选意图": counts[s][chosen[0]],
                        "其他已知意图": sizes[s] - counts[s][chosen[0]],
                    }
                    for s in counts
                ]
            )
        if config.intents:
            with st.expander("看看所选意图的训练示例"):
                frame = samples(root)
                st.dataframe(
                    frame[frame["真实意图"].isin(config.intents)]
                    .groupby("真实意图")
                    .head(2)[["text", "真实意图"]],
                    hide_index=True,
                )
    except (OSError, ValueError, KeyError):
        st.warning("数据尚未准备好或未通过完整性检查，暂不能预览数量。")
    if config.objective == "recall":
        st.info(
            "减少漏判方案：逻辑回归按类别数量加权；朴素贝叶斯使用均等类别先验。可能增加误报，最终效果以验证结果为准。"
        )
    st.caption(
        "选优规则："
        + (
            "通过冻结的 Macro-F1 和召回门槛后，优先按所选意图的召回率排序；同时报告误报。"
            if config.objective == "recall"
            else "按验证集 Macro-F1，再按 Accuracy 比较通过检查的候选。"
        )
    )
