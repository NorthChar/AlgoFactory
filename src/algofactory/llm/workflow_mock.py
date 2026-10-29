"""Explicit deterministic demo strategy, using the same Provider contract as API calls."""

import json
from importlib.resources import files

from algofactory.llm.providers import Provider, ProviderError, ProviderRequest
from algofactory.tasks import PROFILES


class MockWorkflowProvider(Provider):
    mode = "mock"

    def __init__(self, fault: str | None = None):
        super().__init__(max_calls=8, max_retries=1)
        if fault not in {None, "missing_predict_proba", "unsafe_code", "invalid_json"}:
            raise ValueError("Unknown explicit fault fixture")
        self.fault = fault

    def _raw(self, request: ProviderRequest, schema: dict) -> str:
        data = request.source
        if self.fault == "invalid_json" and request.operation == "parse_task":
            return "{invalid fixture JSON"
        if request.operation == "extract_knowledge":
            fixtures = json.loads(
                files("algofactory.llm").joinpath("fixtures/churn.json").read_text()
            )
            fixtures.update(
                json.loads(files("algofactory.llm").joinpath("fixtures/banking77.json").read_text())
            )
            if data["sha256"] not in fixtures:
                raise ProviderError("mock_fixture_missing")
            response = fixtures[data["sha256"]]["response"]
        elif request.operation == "parse_task":
            profile = next((p for p in PROFILES.values() if p.request == data["request"]), None)
            if profile is None:
                raise ProviderError("mock_request_unsupported")
            response = profile.intent()
        elif request.operation == "plan_algorithm":
            algorithm = next(
                (
                    e
                    for e in data["evidence"]
                    if e["type"] == "Algorithm"
                    and e["name"] == data.get("algorithm", "Logistic Regression")
                ),
                None,
            )
            capability = next((e for e in data["evidence"] if e["type"] == "Capability"), None)
            if not algorithm or not capability:
                raise ProviderError("no_compatible_knowledge")
            response = {
                "plan_id": data["plan_id"],
                "task_id": data["task_id"],
                "algorithm_id": algorithm["id"],
                "preprocessing": ["training_only_tfidf", "frozen_class_mapping"]
                if data.get("task_profile") == "banking77"
                else [
                    "median_imputation",
                    "most_frequent_imputation",
                    "one_hot_encoding",
                    "standard_scaling",
                ],
                "dependencies": ["scikit-learn"],
                "evidence_ids": [algorithm["id"], capability["id"]],
            }
        elif request.operation == "generate_code":
            profile = PROFILES[data.get("task_profile", "churn")]
            code = (
                files("algofactory.generation")
                .joinpath("templates/" + profile.template)
                .read_text()
            )
            if self.fault == "missing_predict_proba":
                code = code.replace(
                    "from sklearn.linear_model import LogisticRegression",
                    "from sklearn.svm import LinearSVC",
                ).replace("LogisticRegression(", "LinearSVC(")
            if self.fault == "unsafe_code":
                code = "import os\n" + code
            response = {
                "interface": "build_pipeline",
                "code": code,
                "plan_id": data["plan"]["plan_id"],
            }
        else:
            raise ProviderError("unsupported_mock_operation")
        return json.dumps(response, ensure_ascii=False)
