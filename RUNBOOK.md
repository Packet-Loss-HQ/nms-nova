# NMS-Nova Operations Runbook

## Service Layout
- FastAPI + dashboard: `nms-nova-fastapi.service` → `http://127.0.0.1:8000`
- Poller: `nms-nova-poller.service` (writes to SQLite)
- Public HTTPS: `https://<NMS_HOSTNAME>/` via reverse proxy
- Retention: `nms-nova-retention.timer` daily at 03:00 UTC

## Access
- Dashboard auth: HTTP Basic (set `NMS_AUTH_USER` / `NMS_AUTH_PASS` in systemd env or compose)
- DB path: `/opt/nms-nova/state/nms-nova.db` or `/data/nms-nova.db` in container

## Common Tasks
### Add a target
Preferred path:
1. Open `/targets` in the dashboard
2. Click **Add target**
3. Enter name, address, kind, probe type, tier, SSH key path, and enabled metrics
4. Save

Legacy YAML path still works on first run:
1. Copy `targets.yaml.example` to `targets.yaml`
2. Add target blocks with metrics and intervals
3. On next poller start, targets are imported into SQLite automatically

Verify:
- Target appears on `/targets`
- `service_up` goes green on the dashboard within one poll interval

### Edit a target
1. Open `/targets`
2. Click **Edit** on the target
3. Update fields/metrics/SSH key path
4. Save
5. Poller picks up changes on next cycle

### Remove a target
1. Open `/targets`
2. Click **Delete** on the target
3. Confirm
4. Or run: `/opt/nms-nova/.venv/bin/python3 scripts/purge_target.py <target_name>`

Note: deleting from the UI or script removes the target and all its historical samples from SQLite.

### Telegram alerts
Set these environment variables in the service unit or compose file:
- `NMS_WEBHOOK_URL` — optional generic webhook
- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `TELEGRAM_CHAT_ID` — target chat/user ID
Alerts are posted when rules in `state/alerts.py` trigger.

### Backup
```
/opt/nms-nova/.venv/bin/python3 scripts/backup_restore.py backup
```

### Restore
```
/opt/nms-nova/.venv/bin/python3 scripts/backup_restore.py restore --file /opt/nms-nova/backups/nms-nova-YYYYMMDDTHHMMSSZ.db
```

## Troubleshooting
- 502 at public URL: check `systemctl status nms-nova-fastapi`, reverse proxy config, and tunnel/proxy upstream
- Missing metrics: verify poller service active and targets visible on `/targets`
- Service showing DOWN: verify target address/kind/SSH key path and probe command on the target
- Disk full: run retention manually or prune old backups in `/opt/nms-nova/backups`

### Telegram alerts
1. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the service env.
2. Open `/settings-v2` and confirm Telegram delivery is enabled.
3. Use **Test delivery** to verify connectivity before relying on alerts.

## Release Notes
### v0.4.0
- Add `/api/v1` JSON API, scoped tokens, auth middleware
- Escalation query + delivery retry/timeout controls
- Branding settings API/UI with live preview
- `/license/check`, `/upgrade`, commercial wrapper hooks
- Central public-path auth helper, `/healthz`, docs exposure
