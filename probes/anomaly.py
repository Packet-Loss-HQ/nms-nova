"""Anomaly detection helpers for NMS-Nova.

Baseline model:
- Rolling mean/stddev per metric(target_id + definition_id)
- Z-score check on new samples
- Persist baselines in metric_baselines
- Record anomalies in metric_anomalies

Configurable defaults:
- minimum samples: 20
- z-score warning threshold: 2.5
- z-score critical threshold: 3.0
"""
from __future__ import annotations

import math
from typing import Optional

from state.store import MetricsStore


class AnomalyEngine:
    def __init__(self, store: MetricsStore, min_samples: int = 20, warn_z: float = 2.5, crit_z: float = 3.0):
        self.store = store
        self.min_samples = min_samples
        self.warn_z = warn_z
        self.crit_z = crit_z

    def evaluate(self, target_id: int, definition_id: int, value: float) -> Optional[dict]:
        baseline = self.store.get_baseline(target_id, definition_id)
        if baseline is None or int(baseline.get("sample_count", 0)) < self.min_samples:
            # Not enough data yet; update running stats if any
            self._update_baseline_from_value(target_id, definition_id, value)
            return None
        mean = float(baseline.get("mean", 0.0))
        stddev = float(baseline.get("stddev", 0.0))
        stddev = max(stddev, 1e-6)
        zscore = (value - mean) / stddev
        severity = "critical" if zscore >= self.crit_z else "warning" if zscore >= self.warn_z else None
        if severity:
            self.store.insert_anomaly(target_id, definition_id, value, zscore, severity)
        self._update_baseline_from_value(target_id, definition_id, value)
        return {"zscore": zscore, "severity": severity, "value": value, "mean": mean, "stddev": stddev} if severity else None

    def _update_baseline_from_value(self, target_id: int, definition_id: int, value: float) -> None:
        baseline = self.store.get_baseline(target_id, definition_id)
        if baseline is None:
            self.store.upsert_baseline(target_id, definition_id, value, 0.0, 1)
            return
        count = int(baseline.get("sample_count", 0)) + 1
        mean = float(baseline.get("mean", 0.0))
        stddev = float(baseline.get("stddev", 0.0))
        delta = value - mean
        new_mean = mean + delta / count
        if count > 1:
            m2 = float(stddev) ** 2 * (count - 1)
            m2 += delta * (value - new_mean)
            new_var = m2 / count
            new_std = math.sqrt(new_var)
        else:
            new_std = 0.0
        self.store.upsert_baseline(target_id, definition_id, new_mean, new_std, count)
