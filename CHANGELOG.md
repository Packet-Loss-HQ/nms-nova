# Changelog

## v0.1.3 - 2026-08-02
- Fix chart rendering after HTMX body refresh
- Ensure single-sample metrics render visible data points
- Remove placeholder hosts from monitoring config
- Add Docker container detection for `service_up` probe
- Switch probes to direct SSH path; remove lxc_host workaround
- Redesign dashboard UI: light/dark theme, clean cards, refined alerts
- Fix `interface_total_kbps` unit display
- Sanitize public repo: `targets.yaml` removed, `targets.yaml.example` added

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
