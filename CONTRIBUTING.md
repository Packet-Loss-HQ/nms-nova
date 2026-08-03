# Contributing to NMS-Nova

Thank you for your interest in improving NMS-Nova. This document covers the process and standards for contributions.

## Code of conduct

Be respectful, constructive, and on-topic. This is a small project; personal attacks or spam will not be tolerated.

## How to contribute

1. Open an issue describing the bug or feature before starting work.
2. Fork or branch from `main`.
3. Keep changes focused. One feature or fix per PR.
4. Include tests for new behavior when possible.
5. Ensure CI passes before requesting review.

## Development setup

```bash
git clone https://github.com/Packet-Loss-HQ/nms-nova.git
cd /ms-nova
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

Run the app:
```bash
NMS_DB=/tmp/nms-nova-dev.db .venv/bin/uvicorn main:app --reload
```

Run tests:
```bash
NMS_BASE_URL=http://127.0.0.1:8000 NMS_DB=/tmp/nms-nova-dev.db pytest tests/ -q
```

## Style

- PEP 8, 4-space indentation
- Type hints for new functions
- Keep changes minimal; avoid large refactors without discussion
- Do not commit secrets, IPs, or internal hostnames

## Security issues

Do not open public issues for security vulnerabilities. See `SECURITY.md` for reporting instructions.

## Licensing

By contributing, you agree that your contributions will be dual-licensed under the project’s MIT / proprietary model described in `LICENSE.txt`.
