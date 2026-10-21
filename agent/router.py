"""The mixture-of-experts router: one function that picks which expert handles a task.

An application-level router, not a neural MoE layer: it sends each task to the model
best suited to it and logs why. Every call site logs the decision to model_usage_log
via RunContext.log_model_call, using the reason this module returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent.config import Settings

Task = Literal["classify", "extract", "escalate", "explain"]


@dataclass(frozen=True)
class RouteDecision:
    expert: str  # "rules", "jev", or a model name from config
    reason: str


def route(task: Task, settings: Settings, tokens_used_today: int) -> RouteDecision:
    if settings.kill_switch:
        return RouteDecision("rules", "kill switch is on")
    if tokens_used_today >= settings.max_tokens_per_day:
        return RouteDecision("rules", "daily token budget exhausted")

    if task == "classify":
        if settings.jev_enabled:
            return RouteDecision("jev", "Jev answers category, urgency and injection directly")
        return RouteDecision(
            settings.extract_model, "Jev unavailable; asking the extractor the same questions"
        )
    if task == "extract":
        return RouteDecision(settings.extract_model, "default extractor for free-text fields")
    if task == "escalate":
        return RouteDecision(
            settings.escalate_model, "extractor returned low confidence or failed validation once"
        )
    if task == "explain":
        return RouteDecision(settings.escalate_model, "plain-English explanation needs good writing")
    raise ValueError(f"unknown task {task!r}")
