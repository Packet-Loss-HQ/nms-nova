# NMS-Nova

Lightweight, agentless, read-only network monitoring for homelabs and small networks.

NMS-Nova is built around one constraint: **no agents on the targets**. It probes hosts over SSH/LXC and stores time-series metrics in SQLite. The result is a simple, self-hosted monitoring stack that stays out of the way and doesn’t create a copyleft dependency problem.

**Current version:** v0.2.0

## Features

- **Agentless SSH/LXC probes** — no software install on targets
- **SQLite + WAL** — single-file state, easy backup/restore
- **Chart.js dashboard** — 24h / 7d / 30d trends with light/dark theme
- **Target management UI** — add/edit/delete targets via `/targets`
- **SQLite source of truth** — targets/metrics defined in web UI or imported from YAML
- **Alert engine** — evaluate rules against live samples
- **Telegram alerts** — built-in bot delivery via `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`
- **Generic webhooks** — POST alert payloads to any endpoint via `NMS_WEBHOOK_URL`
- **Auth** — HTTP Basic or Bearer token
- **systemd services** — poller, FastAPI, retention timer
- **Dual license** — MIT for public portfolio, commercial/all-rights-reserved for SMB/ MSP use

## Architecture

```
/targets UI
    |
    v
nms-nova-fastapi.service ---> SQLite state <--- nms-nova-poller.service
                                      |
                                      +---> Telegram Bot API
                                      +---> Generic webhook endpoint
```

**Probes are read-only.** They use SSH command execution or `lxc-attach` to collect metrics. No configuration changes, no package installs, no persistent agent state on targets.

**Primary workflow:** add/edit targets via `/targets`. Legacy YAML import is supported on first run if `targets.yaml` is present.

> **Security:** `targets.yaml` contains host-specific values and remains git-ignored. Do not commit it to version control.

## Install

```bash
git clone https://github.com/Packet-Loss-HQ/nms-nova.git /opt/nms-nova
cd /opt/nms-nova
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Configure

1. Copy the example targets file:
   ```bash
   cp targets.yaml.example targets.yaml
   ```
2. Edit `targets.yaml` with your hosts, SSH key path, and metric intervals.
3. Deploy the probe SSH key to each target host.

### Environment variables

| Variable | Purpose |
|---|---|
| `NMS_DB` | SQLite database path |
| `NMS_TARGETS` | targets YAML path |
| `NMS_AUTH_USER` / `NMS_AUTH_PASS` | HTTP Basic auth |
| `NMS_API_TOKEN` | Bearer token for API endpoints |
| `NMS_WEBHOOK_URL` | Generic webhook for alerts |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for alerts |
| `TELEGRAM_CHAT_ID` | Telegram chat/user ID for alerts |
| `NMS_POLL_INTERVAL` | poll loop sleep seconds |

> **Security:** `targets.yaml` contains host credentials and is git-ignored. Do not commit it to version control.

## Services

Systemd units are included in `scripts/`:

| Unit | Purpose |
|---|---|
| `nms-nova-poller.service` | Polls targets and writes to SQLite |
| `nms-nova-fastapi.service` | Serves dashboard and API |
| `nms-nova-retention.timer` | Daily retention/down-sampling job |

### Quick start

```bash
cp scripts/nms-nova-poller.service /etc/systemd/system/
cp scripts/nms-nova-fastapi.service /etc/systemd/system/
cp scripts/nms-nova-retention.service /etc/systemd/system/
cp scripts/nms-nova-retention.timer /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now nms-nova-poller nms-nova-fastapi nms-nova-retention.timer
```

## Alerting

Alerts are evaluated on each `/health` and `/alerts` request against the latest samples. When rules in `state/alerts.py` trigger, NMS-Nova posts to:

- **Telegram** if `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set
- **Generic webhook** if `NMS_WEBHOOK_URL` is set

### Default rules

- `service_down` — probe failure or unreachable target
- `high_cpu` — CPU usage above threshold
- `high_memory` — memory usage above threshold

Rules are defined in `state/alerts.py` and evaluated per target per metric.

## Dashboard

Access the dashboard at `https://<NMS_HOSTNAME>/` or `http://<host>:8000/` on trusted subnets.

- 24h / 7d / 30d time range buttons
- Live refresh every 15 seconds via HTMX
- Alert banner for active rule violations
- HTTP Basic auth on public endpoints

## Operations

See `RUNBOOK.md` for:
- add/remove targets
- backup/restore
- Telegram alert setup
- troubleshooting

## Development

```bash
.venv/bin/python3 -m py_compile main.py scripts/*.py state/*.py probes/*.py
```

## License

**Public portfolio:** MIT. See `LICENSE-MIT.txt`.

**Commercial/SMB:** Proprietary all-rights-reserved. See `COMMERCIAL-LICENSE.txt`.

This project is custom-built and solely owned by the author. It contains no copyleft/royalty/attribution obligations.
