# NMS-Nova Productization Readiness

## Status: Public portfolio released; commercial-ready pending final audit.

## Deliverables Complete
- v0.1.0: initial public portfolio release (MIT)
- v0.1.1: alert engine, bearer auth, webhooks, enriched `/health`
- v0.1.2: CI workflow, `DEPENDENCIES.md`, public-doc cleanup
- v0.1.3: chart JS fixes, unified `service_up` probe, sanitized git history
- v0.1.4: public chart data endpoint for dashboard JS, version UI fix
- v0.1.5: Telegram alert delivery, target purge script, RUNBOOK expansion

## Dual Licensing Model
- Public portfolio / homelab use: MIT
- Commercial/SMB license: proprietary/all rights reserved
- Buyer receives no copyleft/royalty/attribution obligations

## Branch Strategy
- `main` — public-facing, MIT-licensed portfolio release
- `product/commercial` — proprietary build with branding/license key checks / support packaging
- Never mix; keep commercial-only assets out of `main`

## Pre-Release Checklist
1. `targets.yaml` is git-ignored; `targets.yaml.example` is public template
2. Demo seed script exists but is not part of default startup
3. `LICENSE-MIT.txt` present at repo root
4. `COMMERCIAL-LICENSE.txt` present for proprietary branch
5. `DEPENDENCIES.md` matches installed packages exactly
6. Internal hostnames/IPs/tokens stripped from tracked files
7. GitHub release notes and changelog updated for each tag
8. CI workflow passes before push
9. Full sanitization pass before any GitHub push

## Competitor Positioning
- Targets SMBs/MSPs who cannot deploy GPL NMS tools without legal risk
- Homelab users who want copyleft-free portfolio pieces
- No attribution or royalty obligations downstream
