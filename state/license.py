"""NMS-Nova license and feature-flag enforcement."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set


@dataclass(frozen=True)
class License:
    mode: str = "mit"  # "mit" or "commercial"
    key: Optional[str] = None
    features: Set[str] = field(default_factory=set)


MIT_FEATURES: Set[str] = {
    "core_dashboard",
    "core_charts_24h_7d_30d",
    "core_targets",
    "core_metrics",
    "core_alerts_basic",
    "core_settings",
    "core_auth",
    "core_retention_30d",
    "core_docker",
    "core_api",
}

COMMERCIAL_FEATURES: Set[str] = {
    "extended_retention",
    "advanced_analytics",
    "alert_escalation",
    "multichannel_delivery",
    "rbac",
    "snmp_v2_v3",
    "white_label",
    "custom_dashboards",
    "anomaly_detection",
    "backup_restore",
    "priority_support",
    "commercial_license",
}

ALL_FEATURES: Set[str] = MIT_FEATURES | COMMERCIAL_FEATURES


def enabled_for(license: License) -> Set[str]:
    if license.mode == "commercial":
        return ALL_FEATURES
    return set(MIT_FEATURES)


def is_enabled(license: License, feature: str) -> bool:
    return feature in enabled_for(license)


def commercial_features_summary(license: License) -> List[Dict[str, Any]]:
    enabled = enabled_for(license)
    return [
        {
            "id": feature,
            "name": _FEATURE_NAMES.get(feature, feature),
            "enabled": feature in enabled,
        }
        for feature in sorted(ALL_FEATURES)
    ]


_FEATURE_NAMES = {
    "core_dashboard": "Dashboard",
    "core_charts_24h_7d_30d": "Standard charts",
    "core_targets": "Targets",
    "core_metrics": "Metrics",
    "core_alerts_basic": "Basic alerts",
    "core_settings": "Settings",
    "core_auth": "Auth",
    "core_retention_30d": "Retention (30 days)",
    "core_docker": "Docker",
    "core_api": "API",
    "extended_retention": "Extended retention",
    "advanced_analytics": "Advanced analytics",
    "alert_escalation": "Alert escalation",
    "multichannel_delivery": "Multi-channel delivery",
    "rbac": "RBAC / multi-user",
    "snmp_v2_v3": "SNMP v2c/v3",
    "white_label": "White-label",
    "custom_dashboards": "Custom dashboards",
    "anomaly_detection": "Anomaly detection",
    "backup_restore": "Backup/restore",
    "priority_support": "Priority support",
    "commercial_license": "Commercial license",
}
