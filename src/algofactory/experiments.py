"""Finite BANKING77 experiment contract, frozen before any provider request."""

import hashlib
from typing import Literal

from pydantic import Field, model_validator

from algofactory.knowledge.store import canonical
from algofactory.schemas.contracts import Contract


class ExperimentConfig(Contract):
    goal: Literal["full", "subset", "one_vs_rest"] = "full"
    intents: list[str] = Field(default_factory=list, max_length=76)
    objective: Literal["macro_f1", "recall"] = "macro_f1"

    algorithms: list[Literal["text_logistic", "text_nb"]] = Field(
        default_factory=lambda: ["text_logistic", "text_nb"], min_length=1, max_length=2
    )
    ngram_max: Literal[1, 2] = 2
    max_features: Literal[10000, 30000] = 30000
    logistic_c: Literal[1.0, 4.0] = 4.0
    nb_alpha: Literal[0.1, 0.5] = 0.1
    optimization: Literal["frozen_nb_schedule"] = "frozen_nb_schedule"

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.algorithms)) != len(self.algorithms):
            raise ValueError("duplicate_algorithms")
        from algofactory.intent_catalog import INTENTS

        if len(set(self.intents)) != len(self.intents) or not set(self.intents) <= set(INTENTS):
            raise ValueError("unknown_or_duplicate_intents")
        if self.intents != sorted(self.intents):
            raise ValueError("intents_must_be_sorted")
        if (
            (self.goal == "full" and self.intents)
            or (self.goal == "subset" and not 2 <= len(self.intents) <= 76)
            or (self.goal == "one_vs_rest" and len(self.intents) != 1)
        ):
            raise ValueError("goal_intent_count_mismatch")
        if self.objective == "recall" and self.goal != "one_vs_rest":
            raise ValueError("recall_objective_requires_one_intent")
        return self

    def selection(self):
        return {"goal": self.goal, "intents": self.intents, "objective": self.objective}

    def validate_manifest(self, manifest):
        expected = manifest.get(
            "selection", {"goal": "full", "intents": [], "objective": "macro_f1"}
        )
        if expected != self.selection():
            raise ValueError("requirement_dataset_selection_mismatch")

    def frozen(self):
        return self.model_dump(
            mode="json", exclude={"goal", "intents", "objective"} if self.goal == "full" else set()
        ) | {"nb_alpha_schedule": [self.nb_alpha, self.nb_alpha / 2, self.nb_alpha / 10]}

    @property
    def digest(self):
        return hashlib.sha256(canonical(self.frozen()).encode()).hexdigest()

    def validate_request(self, request):
        from algofactory.requirements import validate_bound_request

        validate_bound_request(request, self)

    def configuration(self, algorithm, seed=42, repair=None):
        if algorithm not in self.algorithms:
            raise ValueError("algorithm_outside_experiment")
        alpha = self.nb_alpha
        if repair and repair.diagnosis["action"] == "OPTIMIZE":
            alpha = self.frozen()["nb_alpha_schedule"][repair.attempt]
        parameters = (
            {"C": self.logistic_c, "max_iter": 500, "random_state": seed}
            if algorithm == "text_logistic"
            else {"alpha": alpha}
        )
        if self.objective == "recall":
            parameters.update(
                {"class_weight": "balanced"}
                if algorithm == "text_logistic"
                else {"fit_prior": False}
            )
        return {
            "TfidfVectorizer": {
                "ngram_range": [1, self.ngram_max],
                "sublinear_tf": True,
                "max_features": self.max_features,
            },
            "classifier": "LogisticRegression" if algorithm == "text_logistic" else "MultinomialNB",
            "classifier_parameters": parameters,
            "text_selector": "text",
        }
