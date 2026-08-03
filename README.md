# NMS-Nova

Self-hosted, owner-operated network monitoring for homelabs and small-scale infrastructure.

- **Dashboard**: at-a-glance target health with latest values, charts, and probe reliability.
- **Drill-down**: per-target probe evidence, inline metric config, per-metric history, and alert rule context.
- **Alerting**: Telegram and webhook delivery with retry and cooldown.
- **Settings**: account management, password protection, retention controls, and alert delivery config.
- **Data control**: local SQLite storage, configurable retention, optional basic web auth.

## Install

```bash
git clone https://github.com/Packet-Loss-HQ/nms-nova.git /opt/nms-nova
cd /opt/nms-nova
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp targets.yaml.example targets.yaml
mkdir -p secrets state backups
```

## Systemd

```bash
cp scripts/nms-nova-fastapi.service /etc/systemd/system/
cp scripts/nms-nova-poller.service /etc/systemd/system/
cp scripts/nms-nova-retention.service /etc/systemd/system/
cp scripts/nms-nova-retention.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now nms-nova-fastapi nms-nova-poller nms-nova-retention.timer
```

## Quick start

1. Open `http://<host>:8000/setup`.
2. Add a target from Setup or `/targets/new`.
3. Confirm probes appear on the Dashboard.
4. Configure alert delivery in Settings if needed.

## Configuration

- Targets are managed through the web UI or SQLite-backed APIs.
- Metrics use tier-aware polling intervals.
- Retention and web password are configurable in Settings.
- Alert rules support per-rule cooldown and escalation chains.

## Security

- Default web access is unauthenticated; enable a password in Settings if exposed beyond localhost.
- Telegram/webhook secrets stay on-host and are not committed.
- Do not expose the SQLite database or secrets directory to untrusted users.

## Troubleshooting

- Service down: `systemctl status nms-nova-fastapi` and `journalctl -u nms-nova-fastapi -n 200`
- No data: confirm target address/key, then check `/status` for latest sample timestamp
- Stale file changes not appearing: remove `__pycache__` and restart the FastAPI service

## Upgrade

```bash
cd /opt/nms-nova
git pull origin main --rebase
.venv/bin/pip install -r requirements.txt
systemctl restart nms-nova-fastapi
```

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
