"""Explicit repository-trusted plugins. No user paths, dynamic imports or candidate execution."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files

from algofactory.generation.safety import check_code
from algofactory.workflow_models import WorkflowFailure


@dataclass(frozen=True)
class TemplatePlugin:
    name: str
    task_type: str
    code: str


@dataclass(frozen=True)
class MetricPlugin:
    name: str
    task_type: str
    direction: str
    evaluate: Callable


class PluginRegistry:
    def __init__(self):
        self.templates = {}
        self.metrics = {}

    def register_template(self, plugin: TemplatePlugin):
        if plugin.name in self.templates:
            raise ValueError("duplicate_template_plugin")
        if plugin.task_type not in {
            "binary_classification",
            "multiclass_classification",
            "regression",
        }:
            raise ValueError("unsupported_plugin_task")
        check_code(plugin.code)
        self.templates[plugin.name] = plugin

    def register_metric(self, plugin: MetricPlugin):
        from algofactory.schemas.contracts import MetricRule

        if plugin.name in self.metrics:
            raise ValueError("duplicate_metric_plugin")
        MetricRule(name=plugin.name, direction=plugin.direction)
        if plugin.task_type != "regression" or plugin.name not in {"mae", "rmse"}:
            raise ValueError("unsupported_metric_plugin")
        if not callable(plugin.evaluate):
            raise ValueError("invalid_metric_plugin")
        self.metrics[plugin.name] = plugin

    def template(self, name, task_type):
        plugin = self.templates[name]
        if plugin.task_type != task_type:
            raise WorkflowFailure("template_task_mismatch")
        return plugin.code

    def score(self, name, task_type, labels, predictions):
        plugin = self.metrics[name]
        if plugin.task_type != task_type:
            raise WorkflowFailure("metric_task_mismatch")
        value = float(plugin.evaluate(labels, predictions))
        if not math.isfinite(value) or value < 0:
            raise WorkflowFailure("invalid_metric_plugin_result")
        return value

    def describe(self):
        return {
            "templates": [
                {"name": p.name, "task_type": p.task_type} for p in self.templates.values()
            ],
            "metrics": [
                {"name": p.name, "task_type": p.task_type, "direction": p.direction}
                for p in self.metrics.values()
            ],
            "trust": "Repository-reviewed Python plugins only; generated code remains Docker-only.",
        }


def default_registry():
    from sklearn.metrics import mean_absolute_error, root_mean_squared_error

    registry = PluginRegistry()
    for name, kind in (
        ("logistic.txt", "binary_classification"),
        ("text_logistic.txt", "multiclass_classification"),
        ("text_nb.txt", "multiclass_classification"),
        ("ridge.txt", "regression"),
    ):
        registry.register_template(
            TemplatePlugin(
                name,
                kind,
                files("algofactory.generation").joinpath("templates/" + name).read_text(),
            )
        )
    registry.register_metric(MetricPlugin("mae", "regression", "minimize", mean_absolute_error))
    # A second independent metric registered without changing the orchestrator.
    registry.register_metric(
        MetricPlugin("rmse", "regression", "minimize", root_mean_squared_error)
    )
    return registry
