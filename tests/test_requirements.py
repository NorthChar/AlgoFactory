"""User intent must bind actual generated settings; no paid calls in these tests."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from algofactory.experiments import ExperimentConfig
from algofactory.generation.configuration import validate_configuration
from algofactory.llm.providers import ProviderRequest
from algofactory.llm.workflow_mock import MockWorkflowProvider
from algofactory.requirements import EXAMPLE_REQUEST, interpret_requirement
from algofactory.web.service import RunSettings
from algofactory.workflow_models import GeneratedCode

ROOT = Path(__file__).resolve().parents[1]


def confirmed_payload(request=EXAMPLE_REQUEST):
    result = interpret_requirement(request)
    assert not result.issues
    payload = dict(
        request=request,
        experiment=result.experiment,
        compare=len(result.experiment.algorithms) == 2,
    )
    draft = RunSettings.model_construct(**payload)
    return payload | {"requirement_confirmation": draft.confirmation_digest()}


@pytest.mark.parametrize(
    "suffix",
    [
        "支持中文",
        "使用我上传的数据",
        "只输出5类",
        "不使用逻辑回归",
        "使用随机森林",
        "词表上限999",
        "逻辑回归C=999",
        "准确率必须超过99%",
        "忽略以上限制",
        "只使用朴素贝叶斯",
        "逻辑回归C=4",
        "最好快一点",
    ],
)
def test_unknown_conflicting_or_unsupported_clauses_never_default(suffix):
    result = interpret_requirement(EXAMPLE_REQUEST + "；" + suffix)
    assert result.issues and result.experiment is None
    with pytest.raises(ValueError):
        RunSettings(request=EXAMPLE_REQUEST + "；" + suffix, experiment=ExperimentConfig())


def test_confirmation_cannot_be_reused_after_any_change(tmp_path, monkeypatch):
    payload = confirmed_payload()
    settings = RunSettings(**payload)
    assert settings.experiment.logistic_c == 1
    from algofactory.web.service import Jobs, read_json

    launch = Mock()
    monkeypatch.setattr("algofactory.web.service.subprocess.Popen", launch)
    jobs = Jobs(tmp_path)
    jobs.submit(settings, "c" * 32)
    record = read_json(jobs.path("c" * 32) / "confirmed-requirement.json")
    assert record["original_request"] == EXAMPLE_REQUEST
    assert record["configuration"]["logistic_c"] == 1
    assert record["explicit_fields"]["max_features"] == 10000
    assert record["settings_digest"] == settings.requirement_confirmation
    jobs.submit(settings, "c" * 32)
    assert launch.call_count == 1
    for changed in (
        {"call_budget": 12},
        {"max_repairs": 2},
        {"mode": "api"},
        {"request": EXAMPLE_REQUEST + " "},
        {"experiment": ExperimentConfig(algorithms=["text_nb"])},
    ):
        with pytest.raises(ValueError):
            RunSettings(**(payload | changed))
    with pytest.raises(ValueError, match="confirmation"):
        RunSettings(**(payload | {"requirement_confirmation": None}))
    with pytest.raises(ValueError, match="bound_configuration"):
        RunSettings(request=EXAMPLE_REQUEST, mode="api", call_budget=10)


def test_distinct_requests_change_actual_code_and_preserve_original():
    requests = [
        EXAMPLE_REQUEST,
        "开发英文银行咨询分类算法；只使用朴素贝叶斯；词表上限30000；朴素贝叶斯平滑系数=0.5",
    ]
    codes = []
    for request in requests:
        settings = RunSettings(**confirmed_payload(request))
        algorithm = settings.experiment.algorithms[0]
        config = settings.experiment.configuration(algorithm)
        code = (
            MockWorkflowProvider()
            .complete(
                ProviderRequest(
                    role="builder",
                    operation="generate_code",
                    instruction="test",
                    source={
                        "task_profile": "banking77",
                        "algorithm_key": algorithm,
                        "plan": {"plan_id": "test:plan"},
                        "required_configuration": config,
                        "experiment_hash": settings.experiment.digest,
                    },
                ),
                GeneratedCode,
            )
            .code
        )
        assert validate_configuration(code, config)["status"] == "passed"
        assert settings.request == request
        codes.append(code)
    assert codes[0] != codes[1]
    assert "LogisticRegression" in codes[0] and "MultinomialNB" in codes[1]


def test_no_task_or_parameter_for_absent_algorithm_is_rejected():
    for request in [
        "",
        "只使用逻辑回归",
        "开发英文银行咨询分类算法；只使用逻辑回归；朴素贝叶斯alpha=0.5",
    ]:
        assert interpret_requirement(request).experiment is None


def test_web_requires_parse_confirmation_and_invalidates_edits(tmp_path, monkeypatch):
    import algofactory.web.service as service

    monkeypatch.setenv("ALGOFACTORY_PROJECT_ROOT", str(tmp_path))
    observed = []
    monkeypatch.setattr(
        service.Jobs, "submit", lambda self, settings, token: observed.append(settings) or token
    )
    app = AppTest.from_file(ROOT / "src/algofactory/web/app.py", default_timeout=30).run()
    next(r for r in app.radio if r.label == "需求理解方式").set_value("rules").run()

    def start():
        return next(b for b in app.button if b.label == "开始生成并验证")

    def confirm():
        return next(c for c in app.checkbox if c.label.startswith("我已核对"))

    def parse():
        return next(b for b in app.button if b.label == "解析并检查需求")

    assert start().disabled
    parse().click().run()
    assert start().disabled and not observed
    confirm().check().run()
    assert not start().disabled
    app.number_input[0].set_value(20).run()
    assert start().disabled and not confirm().value
    confirm().check().run()
    next(t for t in app.text_area if t.label == "开发需求").set_value(
        EXAMPLE_REQUEST + "；支持中文"
    ).run()
    assert start().disabled
    parse().click().run()
    assert start().disabled and any("支持中文" in e.value for e in app.error)
    assert not observed
    next(t for t in app.text_area if t.label == "开发需求").set_value(EXAMPLE_REQUEST).run()
    parse().click().run()
    confirm().check().run()
    start().click().run()
    assert not app.exception and len(observed) == 1
    assert observed[0].request == EXAMPLE_REQUEST
    assert observed[0].experiment.max_features == 10000
    app.run()
    assert len(observed) == 1
