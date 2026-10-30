"""Finite BANKING77 experiment contract, frozen before any provider request."""

import hashlib
from typing import Literal

from pydantic import Field, model_validator

from algofactory.knowledge.store import canonical
from algofactory.schemas.contracts import Contract
from algofactory.tasks import BANKING77


class ExperimentConfig(Contract):
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
        return self

    def frozen(self):
        return self.model_dump(mode="json") | {
            "nb_alpha_schedule": [self.nb_alpha, self.nb_alpha / 2, self.nb_alpha / 10]
        }

    @property
    def digest(self):
        return hashlib.sha256(canonical(self.frozen()).encode()).hexdigest()

    def validate_request(self, request):
        # Explicit parameters are the only customization channel in this first UI.
        # Do not silently ignore a conflicting free-form requirement or charge to discover it.
        if request not in {"", BANKING77.request}:
            raise ValueError("configured_experiments_require_standard_task_description")

    def configuration(self, algorithm, seed=42, repair=None):
        if algorithm not in self.algorithms:
            raise ValueError("algorithm_outside_experiment")
        alpha = self.nb_alpha
        if repair and repair.diagnosis["action"] == "OPTIMIZE":
            alpha = self.frozen()["nb_alpha_schedule"][repair.attempt]
        return {
            "TfidfVectorizer": {
                "ngram_range": [1, self.ngram_max],
                "sublinear_tf": True,
                "max_features": self.max_features,
            },
            "classifier": "LogisticRegression" if algorithm == "text_logistic" else "MultinomialNB",
            "classifier_parameters": {"C": self.logistic_c, "max_iter": 500, "random_state": seed}
            if algorithm == "text_logistic"
            else {"alpha": alpha},
            "text_selector": "text",
        }
