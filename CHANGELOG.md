# Changelog

## [Unreleased]
- Add verbose target detail view with probe evidence, inline metric config, per-metric history, and alert rule context
- Add probe reliability badge to dashboard cards with success-rate color coding
- Add target enable/disable toggle in target detail page
- Add Settings page: account management, password change/clear, retention controls, alert delivery config
- Add optional Basic web auth with middleware and public route exemptions for `/metrics` and `/static/*`
- Add README.md, PRODUCT.md, LICENSE.txt
- Fix stale `__pycache__` masking store changes during deployment
- Remove stale `/settings-v2` routes and normalize nav to `/settings`
- Fix chart range handling: 7d range uses daily buckets instead of hourly
- Fix HTMX fragment handling for `/targets/new` and `/alerts/new`
- Add kbps auto-scaling for `interface_total_kbps` on dashboard cards

## v0.4.0 - 2026-08-02
- Add `/api/v1` JSON endpoints: targets, metrics, alert rules, delivery settings, delivery log, pending escalations
- Configurable webhook retry attempts + timeout via `delivery_settings`
- Per-rule cooldown support in alert delivery routing
- Escalation chain support: `escalation_target`, `escalation_after_minutes`
- One-time DB migrations for new columns/tables
- Scoped API token auth: `/api/v1/admin/tokens` create/list, middleware assigns `request.state.api_scopes`
- Auth middleware: `/api/v1` no longer requires Basic auth, supports Bearer and scoped tokens
- Update docs/version strings to 0.4.0

## v0.3.3 - 2026-08-02
- M10.1 closeout: masked secrets, webhook HMAC signing, `schema_version: 1`
- Retry + audit log for delivery sends, `delivery_log` table
- Alert dedup, per-rule delivery routing, test delivery rate limit
- CSRF protection on save/test endpoints
- `/settings-v2` route with masked fields and inline test feedback

## v0.3.2 - 2026-08-02
- Mobile responsive fixes for `/targets`, `/status`, dashboard cards
- Shared `_layout()` nav with hamburger menu
- Dashboard unified to shared layout

## v0.3.1 - 2026-08-02
- Responsive top nav with hamburger menu
- Active-state highlighting on nav links

## v0.3.0 - 2026-08-02
- Alert Rules Editor UI at `/alerts` with CRUD for rules
- Persist alert rules in SQLite `alert_rules` table
- Alert Delivery Management at `/settings` for Telegram and webhook config
- Test alert delivery from settings UI
- Restore dashboard card links to target detail pages
- Restore `/targets` list View buttons
- Chart.js 4.4.0 CDN to shared layout for detail pages
- Add `/static/detail.js` for chart initialization and range switching
- Add FastAPI static file mount for `/static`

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
- Chart.js dashboard survives HTMX refreshes and renders single-sample data points
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
