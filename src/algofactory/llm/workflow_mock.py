"""Explicit deterministic demo strategy, using the same Provider contract as API calls."""

import json
from importlib.resources import files

from algofactory.llm.providers import Provider, ProviderError, ProviderRequest
from algofactory.tasks import BANKING77_REUSE_REQUEST, PROFILES


class MockWorkflowProvider(Provider):
    mode = "mock"

    def __init__(
        self, fault: str | None = None, *, max_calls: int = 8, plugins=None, template_overrides=None
    ):
        super().__init__(max_calls=max_calls, max_retries=1)
        if fault not in {
            None,
            "missing_predict_proba",
            "unsafe_code",
            "invalid_json",
            "repairable_interface",
            "persistent_interface",
            "unrepairable",
            "text_adapter",
        }:
            raise ValueError("Unknown explicit fault fixture")
        from algofactory.plugins import default_registry

        self.plugins = plugins if plugins is not None else default_registry()
        self.template_overrides = dict(template_overrides or {})
        for task_name, template_name in self.template_overrides.items():
            self.plugins.template(template_name, PROFILES[task_name].task_type)
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
            fixtures.update(
                json.loads(
                    files("algofactory.llm").joinpath("fixtures/regression.json").read_text()
                )
            )
            fixtures.update(
                json.loads(
                    files("algofactory.llm")
                    .joinpath("fixtures/banking-intent-tasks.json")
                    .read_text()
                )
            )
            if data["sha256"] not in fixtures:
                raise ProviderError("mock_fixture_missing")
            response = fixtures[data["sha256"]]["response"]
        elif request.operation == "parse_task":
            profile = next((p for p in PROFILES.values() if p.request == data["request"]), None)
            if data["request"] == BANKING77_REUSE_REQUEST:
                profile = PROFILES["banking77"]
            if profile is None:
                from algofactory.requirements import interpret_requirement

                if not interpret_requirement(data["request"]).issues:
                    profile = PROFILES["banking77"]
            if profile is None:
                raise ProviderError("mock_request_unsupported")
            response = profile.intent()
            if profile.name == "banking77":
                from algofactory.requirements import interpret_requirement

                parsed = interpret_requirement(data["request"])
                if parsed.experiment and (
                    parsed.experiment.goal == "one_vs_rest"
                    or (parsed.experiment.goal == "subset" and len(parsed.experiment.intents) == 2)
                ):
                    response["task_type"] = "binary_classification"
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
            template = self.template_overrides.get(profile.name, template)
            code = self.plugins.template(template, profile.task_type)
            repair = data.get("repair")
            if (
                repair
                and repair["diagnosis"]["action"] == "OPTIMIZE"
                and data.get("algorithm_key") == "text_nb"
            ):
                alpha = {1: "0.05", 2: "0.01"}[repair["attempt"]]
                code = code.replace("alpha=0.1", "alpha=" + alpha)
            if data.get("experiment_hash"):
                required = data["required_configuration"]
                tfidf = required["TfidfVectorizer"]
                code = code.replace(
                    "ngram_range=(1, 2)", "ngram_range=" + repr(tuple(tfidf["ngram_range"]))
                )
                code = code.replace(
                    "max_features=30000", "max_features=" + str(tfidf["max_features"])
                )
                code = code.replace(
                    "C=4.0", "C=" + str(required["classifier_parameters"].get("C", 4.0))
                )
                if data.get("algorithm_key") == "text_nb":
                    import re

                    code = re.sub(
                        r"alpha=[0-9.]+",
                        "alpha=" + str(required["classifier_parameters"]["alpha"]),
                        code,
                    )
            parameters = (data.get("required_configuration") or {}).get("classifier_parameters", {})
            if parameters.get("class_weight") == "balanced":
                code = code.replace(
                    "LogisticRegression(", 'LogisticRegression(class_weight="balanced", '
                )
            if parameters.get("fit_prior") is False:
                code = code.replace("MultinomialNB(", "MultinomialNB(fit_prior=False, ")
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
            if self.fault == "text_adapter" and not repair:
                start = code.index("    preprocess = ColumnTransformer(")
                end = code.index("    model =", start)
                code = (
                    code[:start]
                    + "    preprocess = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, max_features=30000)\n"
                    + code[end:]
                )
            response = {
                "interface": "build_pipeline",
                "code": code,
                "plan_id": data["plan"]["plan_id"],
                "experience_use": [
                    {
                        "experience_id": item["experience_id"],
                        "decision": "adopted",
                        "reason": "显式 Mock：输出固定的、符合文本适配经验的模板；不代表模型推理或收益。",
                    }
                    for item in data.get("retrieved_experiences", [])
                ],
            }
        else:
            raise ProviderError("unsupported_mock_operation")
        return json.dumps(response, ensure_ascii=False)
