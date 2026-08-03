# NMS-Nova

Self-hosted, owner-operated network monitoring for homelabs and small-scale infrastructure.

- **Dashboard**: at-a-glance target health with latest values, charts, and probe reliability.
- **Drill-down**: per-target probe evidence, inline metric config, per-metric history, and alert rule context.
- **Alerting**: Telegram and webhook delivery with retry and cooldown.
- **Settings**: account management, password protection, retention controls, and alert delivery config.
- **Data control**: local SQLite storage, configurable retention, optional basic web auth.

## Install

Requires Python 3.11-3.13.

```bash
git clone https://github.com/Packet-Loss-HQ/nms-nova.git /opt/nms-nova
cd /opt/nms-nova
./scripts/install.sh
```

Or run the installer from another path:
```bash
./scripts/install.sh /opt/nms-nova
```

## Systemd

The installer enables these units if systemd is present:
- `nms-nova-fastapi.service`
- `nms-nova-poller.service`
- `nms-nova-retention.service`
- `nms-nova-retention.timer`

## Quick start

1. Open `http://<host>:8000/setup`.
2. Add a target from Setup or `/targets/new`.
3. Confirm probes appear on the Dashboard.
4. Configure alert delivery in Settings if needed.

## Reverse proxy / TLS

NMS-Nova runs on HTTP by default. For HTTPS ingress, place it behind Caddy or nginx.

Caddy example:
```
nms.example.com {
  reverse_proxy 127.0.0.1:8000
}
```

Nginx example:
```
server {
  listen 443 ssl http2;
  server_name nms.example.com;
  ssl_certificate /etc/letsencrypt/live/nms.example.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/nms.example.com/privkey.pem;

  client_max_body_size 10m;

  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

## Docker

```bash
docker compose up -d
```

Mount `./state` for persistent data and `./secrets` for on-host secrets. The container exposes port `8000`.

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
- Install failed: ensure Python 3.11-3.13, venv created successfully, and port 8000 is free

## Upgrade

```bash
cd /opt/nms-nova
git pull origin main --rebase
.venv/bin/pip install -r requirements.txt
systemctl restart nms-nova-fastapi
```

## Uninstall / reset

```bash
systemctl disable --now nms-nova-fastapi nms-nova-poller nms-nova-retention.timer
rm -f /etc/systemd/system/nms-nova-*
systemctl daemon-reload
rm -rf /opt/nms-nova
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

## Screenshots

- Dashboard: at-a-glance target cards with latest values, probe reliability, and chart ranges.
- Target detail: probe status, metric blocks, inline interval editing, per-metric history.
- Settings: account/password, retention, Telegram/webhook delivery.

## Contributing

See `CONTRIBUTING.md` for setup, testing, and PR guidance.

## Security

See `SECURITY.md` for responsible disclosure instructions.
