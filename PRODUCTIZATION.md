# NMS-Nova Productization

## Status
Public portfolio released under MIT. Commercial/SMB packaging is available under a proprietary license.

## License model
- Public/homelab use: MIT
- Commercial/SMB: proprietary/all-rights-reserved
- Buyers receive no copyleft, royalty, or attribution obligations

## Branch strategy
- `main` — public-facing MIT portfolio
- `product/commercial` — proprietary packaging, branding, license checks
- Do not mix commercial-only assets into `main`

## Positioning
- For SMBs/MSPs that need monitoring without GPL/AGPL legal risk
- For homelab users who want a copyleft-free portfolio piece
- Emphasizes: no agents on targets, read-only probes, simple backup/restore, dual licensing

## Pre-release checklist
1. `targets.yaml` is git-ignored; `targets.yaml.example` is public template
2. Demo seed script exists but is not enabled by default
3. `LICENSE-MIT.txt` and `COMMERCIAL-LICENSE.txt` present
4. `DEPENDENCIES.md` matches runtime deps
5. No internal hostnames, IPs, or credentials in tracked files
6. GitHub release notes and changelog updated
7. CI passes before push
8. Full sanitization pass before any GitHub push
