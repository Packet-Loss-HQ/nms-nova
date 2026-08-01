# NMS-Nova Productization Readiness

## Status: READY for public portfolio release; commercial-ready pending final audit.

## Deliverables Complete
- M1: read-only NMS with LE-secured public dashboard, multi-host coverage
- M2: tier-aware polling, systemd persistence, targets.yaml expansion
- M3: Chart.js trend UI, 24h/7d/30d ranges, retention/down-sampling script, daily timer
- M4: runbook, backup/restore tool, demo dataset, license audit

## Dual Licensing Model
- Public portfolio / homelab use: MIT
- Commercial/SMB license: proprietary/all rights reserved
- Buyer receives no copyleft/royalty/attribution obligations

## Branch Strategy
- `main` — public-facing, MIT-licensed portfolio release
- `product/commercial` — proprietary build with branding/license key checks / support packaging
- Never mix; keep commercial-only assets out of `main`

## Pre-Release Checklist
1. Remove demo data seed from default startup path
2. Replace demo default credentials with documented first-run setup
3. `LICENSE-MIT.txt` present at repo root
4. `COMMERCIAL-LICENSE.txt` present for proprietary branch
5. `DEPENDENCIES.md` matches installed packages exactly
6. Strip internal hostnames/ips from public docs; use placeholders like `your-nms-host.example`
7. Add GitHub issue templates / security policy
8. Tag release `v0.1.0` on `main`

## Competitor Positioning
- Targets SMBs/MSPs who cannot deploy GPL NMS tools without legal risk
- Homelab users who want copyleft-free portfolio pieces
- No attribution or royalty obligations downstream
