"""Explicit deterministic demo strategy, using the same Provider contract as API calls."""

import json
from importlib.resources import files

from algofactory.llm.providers import Provider, ProviderError, ProviderRequest
from algofactory.tasks import PROFILES


class MockWorkflowProvider(Provider):
    mode = "mock"

    def __init__(self, fault: str | None = None, *, max_calls: int = 8):
        super().__init__(max_calls=max_calls, max_retries=1)
        if fault not in {
            None,
            "missing_predict_proba",
            "unsafe_code",
            "invalid_json",
            "repairable_interface",
            "persistent_interface",
            "unrepairable",
        }:
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
            fixtures.update(
                json.loads(
                    files("algofactory.llm").joinpath("fixtures/banking77-phase3.json").read_text()
                )
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
        elif request.operation in {"generate_code", "repair_code"}:
            profile = PROFILES[data.get("task_profile", "churn")]
            from algofactory.planning import ALGORITHMS

            template = (
                ALGORITHMS[data["algorithm_key"]][1]
                if data.get("algorithm_key")
                else profile.template
            )
            code = files("algofactory.generation").joinpath("templates/" + template).read_text()
            repair = data.get("repair")
            if (
                repair
                and repair["diagnosis"]["action"] == "OPTIMIZE"
                and data.get("algorithm_key") == "text_nb"
            ):
                alpha = {1: "0.05", 2: "0.01"}[repair["attempt"]]
                code = code.replace("alpha=0.1", "alpha=" + alpha)
            broken = self.fault in {
                "missing_predict_proba",
                "persistent_interface",
                "unrepairable",
            } or (
                self.fault == "repairable_interface"
                and not repair
                and data.get("algorithm_key") == "text_logistic"
            )
            if broken:
                code = code.replace(
                    "from sklearn.linear_model import LogisticRegression",
                    "from sklearn.svm import LinearSVC",
                ).replace("LogisticRegression(", "LinearSVC(")
                code = code.replace(
                    "from sklearn.naive_bayes import MultinomialNB",
                    "from sklearn.svm import LinearSVC",
                ).replace(
                    "MultinomialNB(alpha=0.1)",
                    'LinearSVC(max_iter=500, random_state=config["seed"])',
                )
                if self.fault == "persistent_interface" and repair:
                    code = code.replace("max_iter=500", "max_iter=" + str(500 + repair["attempt"]))
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
