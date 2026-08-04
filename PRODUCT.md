# NMS-Nova — Product Positioning

## What it is
NMS-Nova is a lightweight, self-hosted network monitoring system built for homelab owners and small-scale operators who want visibility without telemetry, vendor lock-in, or enterprise complexity.

## Who it is for
- Homelabbers running Proxmox, Docker, or mixed Linux environments.
- Operator-owners who want full control of data, polling behavior, and alerting.
- Technically minded users who prefer local SQLite, systemd, and simple config over SaaS agents.

## What it does
- Probes targets via SSH/LXC/Docker and stores samples in local SQLite.
- Presents a concise dashboard with latest values and chart history.
- Provides a verbose drill-down view per target with probe evidence, inline metric controls, per-metric history, and alert rule context.
- Delivers alerts via Telegram and generic webhooks.

## What it does not do
- Optional SNMP support via `pysnmp` (BSD-2-Clause) in licensed builds; MIT core remains without it.
- No cloud dependency.
- No external telemetry or usage reporting.
- Optional commercial modules: SNMP probes, RBAC, extended retention, multi-channel delivery, anomaly baseline, and white-label branding removal.

## Commercial readiness

NMS-Nova is structured for commercial packaging if desired:
- Dual license: MIT for portfolio/non-commercial; proprietary/all rights reserved for commercial deployments.
- Support path: direct support via `sales@packet-loss.net` or marketplace listing.
- Extensible delivery: webhook/alert channels can be extended for managed-service or white-label use cases.

## Commercial intent
Nova is offered under a dual model:
- MIT for public portfolio, learning, and non-commercial use.
- Proprietary/all rights reserved for commercial deployments and resale.

This keeps the project’s public credibility clean while preserving commercial exclusivity if a paid bundle/license is pursued.
