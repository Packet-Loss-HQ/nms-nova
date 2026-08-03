# NMS-Nova

Self-hosted, owner-operated network monitoring for homelabs and small-scale infrastructure.

- **Dashboard**: at-a-glance target health with latest values, charts, and probe reliability.
- **Drill-down**: per-target probe evidence, inline metric config, per-metric history, and alert rule context.
- **Alerting**: Telegram and webhook delivery with retry and cooldown.
- **Settings**: account management, password protection, retention controls, and alert delivery config.
- **Data control**: local SQLite storage, configurable retention, optional basic web auth.

## Install

1. Copy the repo to the host that will run the web UI and poller.
2. Install dependencies: `pip install -r requirements.txt`
3. Initialize storage: the app creates SQLite on first run.
4. Start services:
   - `python3 -m scripts.poll_loop` for the poller
   - `uvicorn main:app --host 0.0.0.0 --port 8000` for the web UI

## Systemd

Example unit files are in `scripts/systemd/`. Enable both `nms-nova-poller.service` and `nms-nova-fastapi.service`.

## Configuration

- Targets are managed through the web UI or SQLite-backed APIs.
- Metrics use tier-aware polling intervals.
- Retention and web password are configurable in Settings.
- Alert rules support per-rule cooldown and escalation chains.

## Security

- Default web access is unauthenticated; enable a password in Settings if exposed beyond localhost.
- Telegram/webhook secrets stay on-host and are not committed.
- Do not expose the SQLite database or secrets directory to untrusted users.

## What it does not do

- No SNMP in v1.
- No cloud dependency.
- No external telemetry or usage reporting.
- No enterprise RBAC, multi-tenant isolation, or compliance modules.

## License

Dual-licensed:
- Public portfolio and open integrations: MIT
- Commercial/closed use: proprietary/all rights reserved

See `LICENSE.txt` and `PRODUCT.md`.
