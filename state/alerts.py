#!/usr/bin/env python3
"""NMS-Nova alert rule engine."""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class AlertRule:
    metric_name: str
    threshold: float
    comparison: str = "gt"
    consecutive: int = 2
    description: str = ""

    def matches(self, value: float) -> bool:
        if self.comparison == "gt":
            return value > self.threshold
        elif self.comparison == "lt":
            return value < self.threshold
        elif self.comparison == "eq":
            return value == self.threshold
        return False


@dataclass
class Alert:
    target_name: str
    metric_name: str
    value: float
    threshold: float
    comparison: str
    description: str
    status: str = "active"


class AlertEngine:
    def __init__(self, rules: List[AlertRule]):
        self.rules = rules
        self._history: dict[str, List[float]] = {}

    def evaluate(self, target_name: str, metric_name: str, value: float) -> List[Alert]:
        key = f"{target_name}.{metric_name}"
        self._history.setdefault(key, [])
        history = self._history[key]
        history.append(value)
        rule = next((r for r in self.rules if r.metric_name == metric_name), None)
        if not rule:
            return []
        if len(history) > rule.consecutive:
            del history[: len(history) - rule.consecutive]
        alerts: List[Alert] = []
        if len(history) >= rule.consecutive and all(rule.matches(v) for v in history[-rule.consecutive :]):
            alerts.append(
                Alert(
                    target_name=target_name,
                    metric_name=metric_name,
                    value=value,
                    threshold=rule.threshold,
                    comparison=rule.comparison,
                    description=rule.description or f"{metric_name} {rule.comparison} {rule.threshold}",
                )
            )
        return alerts
