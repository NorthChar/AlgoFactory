"""Persisted, idempotent semantic analysis rounds and a nontechnical intake UI."""

import re
import uuid
from pathlib import Path

import streamlit as st

from algofactory.datasets import write_json
from algofactory.llm.providers import APIConfig, APIProvider, ProviderError
from algofactory.requirement_understanding import Understanding, requirement_parts, understand
from algofactory.requirements import RequirementResult

NATURAL_EXAMPLE = (
    "我想把英文银行咨询自动分到已有的问题类别，输出类别和概率。我不懂算法，请帮我比较合适的方案。"
)


def requirement_provider(root):
    config = APIConfig.from_env(Path(root) / ".env").model_copy(
        update={"max_calls": 2, "max_retries": 0, "max_output_tokens": 4096}
    )
    return APIProvider(config)


def analyze_draft(root, conversation, request, answers):
    """A round is reserved on disk before any call; interrupted rounds never auto-retry."""
    requirement_parts(request, answers)
    if not re.fullmatch(r"[a-f0-9]{32}", conversation):
        raise ValueError("invalid_requirement_conversation")
    directory = Path(root) / "runtime/requirement-drafts" / conversation
    directory.mkdir(parents=True, exist_ok=True)
    original = directory / "original.txt"
    try:
        with original.open("x", encoding="utf-8") as stream:
            stream.write(request)
    except FileExistsError:
        if original.read_text(encoding="utf-8") != request:
            raise ValueError("requirement_conversation_mismatch") from None
    round_dir = directory / str(len(answers))
    payload = {"request": request, "answers": answers}
    try:
        round_dir.mkdir()
    except FileExistsError:
        import json

        recorded = json.loads((round_dir / "input.json").read_text())
        if recorded != payload:
            raise ValueError("requirement_round_mismatch") from None
        if (round_dir / "understanding.json").exists():
            return Understanding.model_validate_json((round_dir / "understanding.json").read_text())
        raise ProviderError("requirement_round_incomplete_no_replay") from None
    write_json(round_dir / "input.json", payload)
    provider = None
    try:
        provider = requirement_provider(root)
        result = understand(request, answers, provider)
        write_json(round_dir / "understanding.json", result.model_dump(mode="json"))
        return result
    except Exception as exc:
        write_json(
            round_dir / "failure.json",
            {"category": getattr(exc, "category", "requirement_analysis_failed")},
        )
        raise
    finally:
        if provider is not None:
            write_json(
                round_dir / "usage.json",
                {
                    "calls": provider.calls,
                    "limit": 2,
                    "audit": [record.model_dump(mode="json") for record in provider.audit],
                },
            )


def show_semantic_intake(root, request):
    """Return accepted semantic context, or keep generation blocked while clarifying."""
    if st.session_state.get("natural_request") != request:
        st.session_state["natural_request"] = request
        st.session_state["natural_conversation"] = uuid.uuid4().hex
        st.session_state["natural_answers"] = []
        st.session_state.pop("natural_understanding", None)
        st.session_state.pop("natural_failure", None)
    answers = st.session_state["natural_answers"]
    st.caption(
        "用自己的话说明想解决的问题和限制，无需知道算法或参数。系统会给出建议并追问不清楚的内容；当前业务范围仍是英文银行咨询分类。"
    )
    st.warning(
        "自然语言理解使用已配置的大模型接口：每轮最多 2 次请求（理解及复核），最多 3 轮，共最多 6 次；无自动重试。它与后面的代码生成预算分别计算。只点击下面的付费按钮才调用。"
    )
    review = st.session_state.get("natural_understanding")
    action = False
    if review is None:
        action = st.button(
            "理解我的需求（产生费用，最多 2 次请求）",
            disabled=bool(st.session_state.get("natural_failure")),
        )
    else:
        st.write("**系统理解的目标**")
        st.write(review.proposal.summary)
        parts = {p["id"]: p["text"] for p in requirement_parts(request, review.answers)}
        for assessment in review.proposal.assessments:
            with st.container(border=True):
                st.write("你的表述：" + parts.get(assessment.part_id, "未找到对应原文"))
                st.write(assessment.explanation)
                if assessment.question:
                    st.info(assessment.question)
        if review.verification and review.verification.issues:
            st.warning("复核发现：" + "；".join(review.verification.issues))
        if review.problems():
            st.warning(
                "需求还不能执行。请回答上面的疑问，或明确修改不支持的要求；不会先按默认任务生成。"
            )
        if len(answers) < 2:
            answer = st.text_area("补充说明或回答问题", key="natural_answer_" + str(len(answers)))
            if st.button(
                "提交补充并重新理解（产生费用，最多 2 次请求）", disabled=not answer.strip()
            ):
                answers = [*answers, answer]
                st.session_state["natural_answers"] = answers
                st.session_state.pop("natural_understanding", None)
                action = True
        else:
            st.caption(
                "已达到本次需求的 3 轮理解上限。如仍需调整，请将完整需求重新整理到上方输入框，开始新的需求检查。"
            )
    if action:
        try:
            with st.spinner("正在整理需求并检查方案是否忠实于你的要求…"):
                review = analyze_draft(
                    root, st.session_state["natural_conversation"], request, answers
                )
            st.session_state["natural_understanding"] = review
            st.rerun()
        except (ValueError, OSError, ProviderError):
            st.session_state["natural_failure"] = True
            st.error(
                "本轮需求理解未完成，已停止且不会自动重试；请检查接口配置或整理新需求。未开始生成代码。"
            )
    if st.session_state.get("natural_failure"):
        st.error("当前需求检查发生错误，生成已禁用；不会降级成默认任务。")
        return None, None
    # Do not use a stale proposal while a later clarification is pending or failed.
    if review is None or review.request != request or review.answers != answers:
        return None, None
    problems = review.problems()
    if problems:
        return RequirementResult(None, {}, problems), review
    try:
        review.execution_request()
    except ValueError:
        return RequirementResult(
            None, {}, ["建议配置无法映射到支持的执行方案，请重新检查。"]
        ), review
    explicit = {
        name: getattr(review.proposal.configuration, name)
        for assessment in review.proposal.assessments
        if assessment.disposition == "supported"
        for name in assessment.fields
    }
    return RequirementResult(review.proposal.configuration, explicit, []), review
