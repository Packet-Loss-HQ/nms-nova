# Security Policy

NMS-Nova handles credentials, alert delivery tokens, and network infrastructure data. Please report security issues responsibly.

## Reporting a vulnerability

- Do not open a public issue for security vulnerabilities.
- Email security reports to `security@packet-loss.net`.
- Include a description, affected versions, and reproduction steps if possible.

## Supported versions

- `main` branch: supported
- Older tags: best-effort only

## Secrets hygiene

- Never commit secrets, tokens, passwords, or live internal infrastructure data.
- Use `secrets/` locally; it is gitignored.
- Report any accidental secret exposure immediately so it can be revoked and rotated.
