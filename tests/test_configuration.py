"""Freeze the documented candidate parameters without executing generated source."""

from importlib.resources import files

import pytest

from algofactory.generation.configuration import required_configuration, validate_configuration
from algofactory.workflow_models import WorkflowFailure


def template(algorithm):
    return files("algofactory.generation").joinpath(f"templates/{algorithm}.txt").read_text()


@pytest.mark.parametrize("algorithm", ["text_logistic", "text_nb"])
def test_documented_candidate_configuration_passes(algorithm):
    assert (
        validate_configuration(template(algorithm), required_configuration(algorithm))["status"]
        == "passed"
    )


@pytest.mark.parametrize(
    "replacement",
    [
        "TfidfVectorizer()",
        "TfidfVectorizer(ngram_range=(1, 1), sublinear_tf=True, max_features=30000)",
    ],
)
def test_omitted_or_wrong_tfidf_parameters_rejected(replacement):
    code = template("text_nb").replace(
        "TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, max_features=30000)", replacement
    )
    with pytest.raises(WorkflowFailure) as error:
        validate_configuration(code, required_configuration("text_nb"))
    assert error.value.category == "algorithm_configuration_mismatch"
    assert error.value.diagnostics[0]["rule"] == "tfidf_parameters"


def test_unused_correct_constructor_does_not_hide_returned_default():
    code = template("text_nb").replace(
        "    preprocess =",
        "    unused = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, max_features=30000)\n    preprocess =",
        1,
    )
    code = code.replace(
        '("text", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, max_features=30000)',
        '("text", TfidfVectorizer()',
    )
    with pytest.raises(WorkflowFailure):
        validate_configuration(code, required_configuration("text_nb"))


@pytest.mark.parametrize(
    "before,after",
    [
        ("C=4.0", "C=1.0"),
        ('config["text_features"][0]', 'config["text_features"]'),
        ('random_state=config["seed"]', "random_state=99"),
    ],
)
def test_classifier_and_selector_contract_enforced(before, after):
    with pytest.raises(WorkflowFailure):
        validate_configuration(
            template("text_logistic").replace(before, after),
            required_configuration("text_logistic"),
        )


def test_literal_bindings_supported_without_execution():
    code = (
        template("text_logistic")
        .replace("    preprocess =", "    features = 30000\n    preprocess =")
        .replace("max_features=30000", "max_features=features")
    )
    validate_configuration(code, required_configuration("text_logistic"))
