from pathlib import Path

import pytest

from algofactory.cli import parser, run
from algofactory.experiments import ExperimentConfig
from algofactory.generation.configuration import validate_configuration
from algofactory.llm.providers import ProviderRequest
from algofactory.llm.workflow_mock import MockWorkflowProvider
from algofactory.tasks import BANKING77
from algofactory.web.service import RunSettings
from algofactory.workflow_models import GeneratedCode, WorkflowFailure


def test_configs_flow_to_mock_code_and_static_validation():
    baseline = ExperimentConfig()
    alternative = ExperimentConfig(ngram_max=1, max_features=10000, logistic_c=1.0, nb_alpha=0.5)
    assert baseline.digest != alternative.digest
    assert alternative.frozen()["nb_alpha_schedule"] == [0.5, 0.25, 0.05]
    for config in [baseline, alternative]:
        for algorithm in config.algorithms:
            required = config.configuration(algorithm)
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
                            "required_configuration": required,
                            "experiment_hash": config.digest,
                        },
                    ),
                    GeneratedCode,
                )
                .code
            )
            assert validate_configuration(code, required)["status"] == "passed"
            if config == alternative:
                with pytest.raises(WorkflowFailure):
                    validate_configuration(code, baseline.configuration(algorithm))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"algorithms": []},
        {"algorithms": ["text_nb", "text_nb"]},
        {"logistic_c": 50.0},
        {"max_features": 1000000},
        {"ngram_max": 3},
        {"nb_alpha": -1.0},
    ],
)
def test_invalid_parameters_rejected(kwargs):
    with pytest.raises(ValueError):
        ExperimentConfig(**kwargs)


def test_cli_conflict_rejected_before_provider(tmp_path, monkeypatch):
    import algofactory.llm.providers as providers

    monkeypatch.setattr(
        providers.APIConfig,
        "from_env",
        classmethod(lambda *a, **k: pytest.fail("must not configure provider")),
    )
    path = tmp_path / "experiment.json"
    path.write_text(ExperimentConfig().model_dump_json())
    with pytest.raises(ValueError, match="standard_task"):
        run(
            parser().parse_args(
                [
                    "demo",
                    "--task",
                    "banking77",
                    "--mode",
                    "api",
                    "--experiment",
                    str(path),
                    "--request",
                    "Use C=999",
                ]
            )
        )
    with pytest.raises(ValueError):
        RunSettings(experiment=ExperimentConfig(algorithms=["text_nb"]), compare=True)
    assert (
        RunSettings(
            experiment=ExperimentConfig(algorithms=["text_nb"]),
            compare=False,
            request=BANKING77.request,
        ).max_repairs
        == 1
    )


def test_web_config_is_frozen_and_invalid_selection_does_not_submit(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    import algofactory.web.service as service

    monkeypatch.setenv("ALGOFACTORY_PROJECT_ROOT", str(tmp_path))
    observed = []
    monkeypatch.setattr(
        service.Jobs, "submit", lambda self, settings, token: observed.append(settings) or token
    )
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "src/algofactory/web/app.py", default_timeout=30).run()
    next(t for t in app.toggle if t.label == "自主选择算法与参数").set_value(True).run()
    next(s for s in app.selectbox if s.label == "逻辑回归 C").set_value(1.0).run()
    next(b for b in app.button if b.label == "开始生成并验证").click().run()
    assert observed[0].experiment.logistic_c == 1.0
    next(s for s in app.multiselect if s.label == "参与实验的算法").set_value([]).run()
    next(b for b in app.button if b.label == "开始生成并验证").click().run()
    assert len(observed) == 1
    assert not app.exception


def test_churn_planner_does_not_receive_text_experiment_parameters(tmp_path, monkeypatch):
    import algofactory.orchestrator as workflow
    from algofactory.datasets import generate_dataset
    from algofactory.orchestrator import run_workflow
    from algofactory.tasks import CHURN

    requests = []

    class RecordingMock(MockWorkflowProvider):
        def _raw(self, request, schema):
            requests.append(request)
            return super()._raw(request, schema)

    def stop_before_docker(*args, **kwargs):
        raise WorkflowFailure("test_stop_before_execution")

    monkeypatch.setattr(workflow, "DockerExecutor", stop_before_docker)
    data = tmp_path / "data"
    generate_dataset(data, rows=200)
    root = Path(__file__).resolve().parents[1]
    run_workflow(
        directory=tmp_path / "run",
        dataset_dir=data,
        db_path=tmp_path / "knowledge.sqlite",
        approval_path=tmp_path / "unused",
        requirements_path=root / "requirements.txt",
        knowledge_document=root / "data/customer_churn.txt",
        request=CHURN.request,
        provider=RecordingMock(),
        validation_only=True,
    )
    planning = next(r for r in requests if r.operation == "plan_algorithm")
    assert planning.source["required_configuration"] is None
    assert planning.source["algorithm"] == CHURN.algorithm
