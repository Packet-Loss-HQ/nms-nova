# Changelog

## v0.1.1 - 2026-08-01
- Add interface traffic probe (`interface_total_kbps`)
- Add alert engine with default CPU/memory/service-down rules
- Add `/alerts` endpoint and alert banner in dashboard UI
- Add bearer-token API auth (`NMS_API_TOKEN`)
- Add webhook notifications (`NMS_WEBHOOK_URL`)
- Enrich `/health` with DB size, sample count, target count, version
- Add `targets.yaml` validation on startup
- Distinguish probe errors from zero values in UI
- Upgrade DB schema: `metric_samples.error` column

## v0.1.0 - 2026-08-01
- Initial public portfolio release
- FastAPI + SQLite + Chart.js dashboard
- systemd services + retention timer
- MIT / commercial dual license
