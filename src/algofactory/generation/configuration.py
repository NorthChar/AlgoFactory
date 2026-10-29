"""Inspect the restricted factory as data; never import or execute generated Python."""

import ast
from dataclasses import dataclass

from algofactory.workflow_models import WorkflowFailure


def required_configuration(algorithm, seed=42, repair=None):
    if algorithm == "ridge":
        return {
            "classifier": "Ridge",
            "classifier_parameters": {"alpha": 1.0},
            "numeric_features": ["x1", "x2", "x3"],
            "text_selector": "text",
        }
    classifier = "LogisticRegression" if algorithm == "text_logistic" else "MultinomialNB"
    parameters = {"C": 4.0, "max_iter": 500, "random_state": seed}
    if classifier == "MultinomialNB":
        alpha = 0.1
        if repair and repair.diagnosis["action"] == "OPTIMIZE":
            alpha = {1: 0.05, 2: 0.01}[repair.attempt]
        parameters = {"alpha": alpha}
    return {
        "TfidfVectorizer": {"ngram_range": [1, 2], "sublinear_tf": True, "max_features": 30000},
        "classifier": classifier,
        "classifier_parameters": parameters,
        "text_selector": "text",
    }


@dataclass
class Constructor:
    name: str
    args: list
    kwargs: dict


def validate_configuration(code, required):
    """Resolve literals/assignments and inspect the returned Pipeline, including its connections."""
    issues = []
    bindings = {
        "config": {
            "seed": required["classifier_parameters"].get("random_state", 42),
            "text_features": [required["text_selector"]],
            "numeric_features": required.get("numeric_features", []),
        }
    }

    def value(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            return [value(child) for child in node.elts]
        if isinstance(node, ast.Name):
            return bindings[node.id]
        if isinstance(node, ast.Subscript):
            return value(node.value)[value(node.slice)]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return Constructor(
                node.func.id,
                [value(a) for a in node.args],
                {k.arg: value(k.value) for k in node.keywords},
            )
        raise ValueError("unsupported_configuration_expression")

    def argument(obj, name):
        if obj.args and name in obj.kwargs:
            raise ValueError("duplicate_argument")
        return obj.args[0] if len(obj.args) == 1 else obj.kwargs[name]

    try:
        function = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
        returned = None
        for statement in function.body:
            if isinstance(statement, ast.Assign):
                resolved = value(statement.value)
                for target in statement.targets:
                    bindings[target.id] = resolved
            elif isinstance(statement, ast.Return):
                returned = value(statement.value)
                break
        assert isinstance(returned, Constructor) and returned.name == "Pipeline"
        assert len(returned.args) <= 1 and set(returned.kwargs) <= {"steps"}
        steps = argument(returned, "steps")
        assert len(steps) == 2 and all(len(step) == 2 for step in steps)
        preprocessor, classifier = [step[1] for step in steps]
        assert isinstance(preprocessor, Constructor) and preprocessor.name == "ColumnTransformer"
        assert len(preprocessor.args) <= 1 and set(preprocessor.kwargs) <= {"transformers"}
        transformers = argument(preprocessor, "transformers")
        assert len(transformers) == 1 and len(transformers[0]) == 3
        _, vectorizer, selector = transformers[0]
        if required["classifier"] == "Ridge":
            assert isinstance(vectorizer, Constructor) and vectorizer.name == "Pipeline"
            assert len(vectorizer.args) <= 1 and set(vectorizer.kwargs) <= {"steps"}
            numeric_steps = argument(vectorizer, "steps")
            assert len(numeric_steps) == 2 and all(len(step) == 2 for step in numeric_steps)
            impute, scale = [step[1] for step in numeric_steps]
            assert impute == Constructor("SimpleImputer", [], {"strategy": "median"})
            assert scale == Constructor("StandardScaler", [], {})
            assert selector == required["numeric_features"]
        else:
            assert isinstance(vectorizer, Constructor) and vectorizer.name == "TfidfVectorizer"
            if vectorizer.args or vectorizer.kwargs != required["TfidfVectorizer"]:
                issues.append({"rule": "tfidf_parameters", "expected": required["TfidfVectorizer"]})
            if selector != required["text_selector"]:
                issues.append(
                    {"rule": "scalar_text_selector", "expected": required["text_selector"]}
                )
        if (
            not isinstance(classifier, Constructor)
            or classifier.name != required["classifier"]
            or classifier.args
            or classifier.kwargs != required["classifier_parameters"]
        ):
            issues.append(
                {
                    "rule": "classifier_parameters",
                    "expected": required["classifier_parameters"],
                    "classifier": required["classifier"],
                }
            )
    except (
        AssertionError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
        ValueError,
        StopIteration,
    ):
        issues.append(
            {
                "rule": "regression_pipeline_structure"
                if required["classifier"] == "Ridge"
                else "text_pipeline_structure",
                "expected": "Pipeline(ColumnTransformer(training-only preprocessing, frozen columns), classifier)",
            }
        )
    if issues:
        raise WorkflowFailure("algorithm_configuration_mismatch", diagnostics=issues)
    return {"status": "passed", "required_configuration": required}
