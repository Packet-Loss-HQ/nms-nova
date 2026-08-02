# Changelog

## v0.2.0 - 2026-08-02
- SQLite-backed target management UI
- Add/edit/delete targets via `/targets`
- YAML→SQLite migration on first run
- Per-target SSH key support
- Mobile layout fixes for edit form

## v0.1.5 - 2026-08-02
- Add Telegram alert delivery via bot token / chat ID env vars
- Add `scripts/purge_target.py` for removing targets and their historical data
- Expand RUNBOOK.md with add-target, remove-target, and Telegram setup steps

## v0.1.4 - 2026-08-02
- Allow unauthenticated chart data fetch for dashboard JS
- Chart canvases initialize correctly on first load and after HTMX refresh
- Single-sample metrics render visible data points
- Fix FastAPI app version display in dashboard UI

## v0.1.3 - 2026-08-02
- Chart.js dashboard now survives HTMX refreshes and renders single-sample data points
- Unified `service_up` probe supports both systemd services and Docker containers
- Placeholder hosts removed; real target configs reconciled to 8-host deployment
- Light/dark theme UI cleanup; fixed interface units and alert strip formatting
- Sanitize public repo: real `targets.yaml` removed from git history, `targets.yaml.example` added

## v0.1.2 - 2026-08-01
- Add CI workflow for lint/test
- Add DEPENDENCIES.md with license catalog
- Remove internal hostnames/IPs from public-facing configs

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
