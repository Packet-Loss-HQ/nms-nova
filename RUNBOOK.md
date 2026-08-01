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
