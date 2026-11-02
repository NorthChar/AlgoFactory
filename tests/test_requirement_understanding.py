"""Semantic proposals are untrusted until covered, reviewed, bound and confirmed."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from algofactory.experiments import ExperimentConfig
from algofactory.llm.providers import Provider, ProviderError
from algofactory.requirement_understanding import (
    Assessment,
    Proposal,
    Understanding,
    Verification,
    requirement_parts,
    understand,
)
from algofactory.web.requirement_intake import NATURAL_EXAMPLE, analyze_draft
from algofactory.web.service import Jobs, RunSettings, read_json

ROOT = Path(__file__).resolve().parents[1]


class ScriptedProvider(Provider):
    mode = "mock"

    def __init__(self, responses):
        super().__init__(max_calls=2, max_retries=0)
        self.responses = iter(responses)

    def _raw(self, request, schema):
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response.model_dump_json()


def proposal(request=NATURAL_EXAMPLE, answers=(), disposition="supported"):
    return Proposal(
        task="banking77",
        summary="将英文咨询分到已有类别，建议比较两个候选。",
        configuration=ExperimentConfig(),
        assessments=[
            Assessment(
                part_id=p["id"],
                disposition=disposition,
                explanation="明确的英文银行分类目标"
                if disposition == "supported"
                else "需要补充或不支持",
                question="是否接受只比较现有方案、不保证运行时间？"
                if disposition == "clarify"
                else "",
            )
            for p in requirement_parts(request, list(answers))
        ],
    )


def accepted():
    return Understanding(
        request=NATURAL_EXAMPLE, proposal=proposal(), verification=Verification(verdict="approve")
    )


def settings_for(review):
    payload = dict(
        understanding=review,
        request=review.request,
        experiment=review.proposal.configuration,
        compare=len(review.proposal.configuration.algorithms) == 2,
    )
    draft = RunSettings.model_construct(**payload)
    return RunSettings(**payload, requirement_confirmation=draft.confirmation_digest())


def test_two_calls_and_configuration_bind_to_original_and_normalized(tmp_path, monkeypatch):
    provider = ScriptedProvider([proposal(), Verification(verdict="approve")])
    result = understand(NATURAL_EXAMPLE, [], provider)
    assert not result.problems() and provider.calls == 2
    settings = settings_for(result)
    assert settings.execution_request() != NATURAL_EXAMPLE
    settings.experiment.validate_request(settings.execution_request())
    monkeypatch.setattr("algofactory.web.service.subprocess.Popen", Mock())
    jobs = Jobs(tmp_path)
    jobs.submit(settings, "a" * 32)
    record = read_json(jobs.path("a" * 32) / "confirmed-requirement.json")
    assert record["original_request"] == NATURAL_EXAMPLE
    assert record["execution_request"] == settings.execution_request()
    assert record["understanding"]["verification"]["verdict"] == "approve"
    altered = settings.model_dump(mode="json") | {"call_budget": 12}
    with pytest.raises(ValueError, match="confirmation"):
        RunSettings.model_validate(altered)


@pytest.mark.parametrize("disposition", ["clarify", "unsupported"])
def test_unclear_or_unsupported_never_generates(disposition):
    provider = ScriptedProvider([proposal(disposition=disposition)])
    result = understand(NATURAL_EXAMPLE, [], provider)
    assert result.problems() and provider.calls == 1
    with pytest.raises(ValueError):
        settings_for(result)


def test_missing_clause_and_false_supersession_block_even_approved():
    result = accepted()
    result.proposal.assessments.pop()
    assert result.problems()
    result = accepted()
    result.proposal.assessments[0].disposition = "superseded"
    result.proposal.assessments[0].superseded_by = "0:1"
    assert result.problems()
    with pytest.raises(ValueError):
        settings_for(result)


def test_independent_reviewer_can_reject_hidden_requirements():
    p = ScriptedProvider(
        [proposal(), Verification(verdict="revise", issues=["用户要求中文，方案却只支持英文"])]
    )
    review = understand(NATURAL_EXAMPLE, [], p)
    assert review.problems()
    with pytest.raises(ValueError):
        settings_for(review)


def test_rounds_cached_failure_not_replayed_and_three_round_limit(tmp_path, monkeypatch):
    import algofactory.web.requirement_intake as intake

    instances = []

    def factory(root):
        p = ScriptedProvider([proposal(), Verification(verdict="approve")])
        instances.append(p)
        return p

    monkeypatch.setattr(intake, "requirement_provider", factory)
    one = analyze_draft(tmp_path, "b" * 32, NATURAL_EXAMPLE, [])
    two = analyze_draft(tmp_path, "b" * 32, NATURAL_EXAMPLE, [])
    assert one == two and len(instances) == 1 and instances[0].calls == 2
    with pytest.raises(ValueError):
        analyze_draft(tmp_path, "b" * 32, NATURAL_EXAMPLE, ["a", "b", "c"])
    broken = ScriptedProvider([ProviderError("timeout")])
    monkeypatch.setattr(intake, "requirement_provider", lambda root: broken)
    with pytest.raises(ProviderError):
        analyze_draft(tmp_path, "c" * 32, NATURAL_EXAMPLE, [])
    with pytest.raises(ProviderError, match="no_replay"):
        analyze_draft(tmp_path, "c" * 32, NATURAL_EXAMPLE, [])
    assert broken.calls == 1


def test_unsupported_followed_by_explicit_revision():
    request = "我想做中文银行咨询分类"
    answer = "撤回中文要求，改为英文银行咨询77类分类，输出类别及概率"
    p = proposal(request, [answer])
    p.assessments[0].disposition = "superseded"
    p.assessments[0].superseded_by = "1:0"
    review = understand(request, [answer], ScriptedProvider([p, Verification(verdict="approve")]))
    assert not review.problems()
    settings_for(review)


def test_web_natural_input_clarification_and_no_background_calls(tmp_path, monkeypatch):
    import algofactory.web.requirement_intake as intake
    import algofactory.web.service as service

    monkeypatch.setenv("ALGOFACTORY_PROJECT_ROOT", str(tmp_path))
    providers = []
    answer = "接受现有英文数据和类别，请比较两个方案，不要求速度保证"
    responses = [
        [proposal(disposition="clarify")],
        [proposal(answers=[answer]), Verification(verdict="approve")],
    ]

    def factory(root):
        p = ScriptedProvider(responses[len(providers)])
        providers.append(p)
        return p

    monkeypatch.setattr(intake, "requirement_provider", factory)
    launches = Mock()
    monkeypatch.setattr(service.subprocess, "Popen", launches)
    app = AppTest.from_file(ROOT / "src/algofactory/web/app.py", default_timeout=30).run()
    assert not providers and not launches.called
    next(b for b in app.button if b.label.startswith("理解我的需求")).click().run()
    assert len(providers) == 1 and not app.exception
    assert next(b for b in app.button if b.label == "开始生成并验证").disabled
    app.run()
    assert len(providers) == 1
    next(t for t in app.text_area if t.label == "补充说明或回答问题").set_value(answer).run()
    next(b for b in app.button if b.label.startswith("提交补充")).click().run()
    assert not app.exception and len(providers) == 2
    assert next(b for b in app.button if b.label == "开始生成并验证").disabled
    next(c for c in app.checkbox if c.label.startswith("我已核对")).check().run()
    next(b for b in app.button if b.label == "开始生成并验证").click().run()
    assert not app.exception and launches.call_count == 1
    path = next((tmp_path / "runtime/web-jobs").glob("*/settings.json"))
    stored = json.loads(path.read_text())
    assert stored["request"] == NATURAL_EXAMPLE and stored["understanding"]["answers"] == [answer]
    app.run()
    assert len(providers) == 2 and launches.call_count == 1


def test_runner_uses_approved_execution_request_and_keeps_original(tmp_path, monkeypatch):
    import algofactory.web.runner as runner

    (tmp_path / "runtime/banking77-data").mkdir(parents=True)
    monkeypatch.setattr("algofactory.web.service.subprocess.Popen", Mock())
    review = accepted()
    settings = settings_for(review)
    jobs = Jobs(tmp_path)
    jobs.submit(settings, "d" * 32)
    captured = []

    def fake_run(args):
        captured.append(args)
        return {"status": "validated", "workflow_id": "test:semantic"}

    monkeypatch.setattr(runner, "run", fake_run)
    assert runner.execute(tmp_path, "d" * 32) == 0
    assert captured[0].request == settings.execution_request()
    assert captured[0].request != NATURAL_EXAMPLE
    config = json.loads(captured[0].experiment.read_text())
    assert config == settings.experiment.model_dump(mode="json")
    origin = read_json(jobs.path("d" * 32) / "run/requirement-origin.json")
    assert origin["original_request"] == NATURAL_EXAMPLE
    assert origin["confirmed_settings_digest"] == settings.requirement_confirmation
