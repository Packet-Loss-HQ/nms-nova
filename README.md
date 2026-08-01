# NMS-Nova

Lightweight, agentless, read-only network monitoring for homelabs and small networks.

- FastAPI + SQLite + WAL
- SSH/lxc-attach probes
- Reverse proxy / TLS termination
- Prometheus `/metrics` endpoint
- Chart.js dashboard with 24h / 7d / 30d trends
- Alert engine with webhook notifications
- Bearer-token or Basic auth
- systemd services + daily retention timer

## Install
```bash
git clone <this-repo> /opt/nms-nova
python3 -m venv /opt/nms-nova/.venv
/opt/nms-nova/.venv/bin/pip install -r requirements.txt
```

## Configure
Edit `targets.yaml` with hosts and metric intervals, then:
```bash
/opt/nms-nova/.venv/bin/python3 scripts/poll_loop.py
```

Optional environment variables:
- `NMS_API_TOKEN` — Bearer token for API access
- `NMS_WEBHOOK_URL` — POST alert payloads on alert evaluation
- `NMS_AUTH_USER` / `NMS_AUTH_PASS` — Basic auth credentials
- `NMS_DB` — database path
- `NMS_TARGETS` — targets YAML path
- `NMS_POLL_INTERVAL` — poll loop sleep seconds

## Services
Use the included systemd units:
- `nms-nova-poller.service`
- `nms-nova-fastapi.service`
- `nms-nova-retention.timer`

## License
Public portfolio release: MIT. See `LICENSE-MIT.txt`.

Commercial/SMB license available. See `COMMERCIAL-LICENSE.txt`.
