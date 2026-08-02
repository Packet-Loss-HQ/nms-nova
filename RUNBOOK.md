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
### Manual poller restart
```
systemctl restart nms-nova-poller
```

### FastAPI restart
```
systemctl restart nms-nova-fastapi
```

### Add a target
1. Add the target block to `targets.yaml`
2. Verify SSH probe access from the NMS host: `ssh -i <ssh_key> <user>@<address> hostname`
3. Restart poller: `systemctl restart nms-nova-poller`
4. Confirm `service_up` goes green on the dashboard within one poll interval

### Remove a target
1. Stop the poller: `systemctl stop nms-nova-poller`
2. Run the purge script: `/opt/nms-nova/.venv/bin/python3 scripts/purge_target.py <target_name>`
3. Remove the target block from `targets.yaml`
4. Restart the poller: `systemctl restart nms-nova-poller`

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
- Missing metrics: verify poller service active and `targets.yaml` targets reachable
- Disk full: run retention manually or prune old backups in `/opt/nms-nova/backups`
