# Dependencies

## Application runtime
| Component | Version | License | Purpose |
|-----------|---------|---------|---------|
| Python | 3.11+ | PSF License | Runtime |
| FastAPI | 0.111.0 | MIT | Web framework |
| Uvicorn | 0.30.0 | MIT | ASGI server |
| Pydantic | 2.7.0 | MIT | Data validation |
| python-multipart | 0.0.9 | MIT | Form parsing |
| PyYAML | latest | MIT | Target config parsing |

## Infrastructure
| Component | Version | License | Purpose |
|-----------|---------|---------|---------|
| SQLite | 3.35+ | Public Domain | Metrics store |
| Reverse proxy | latest | Apache 2.0 | TLS termination |
| OS base | 12 | Various (permissive) | Base OS |
| Tunnel client | latest | BSD-3-Clause | Tunnel ingress |

## Frontend
| Component | Version | License | Purpose |
|-----------|---------|---------|---------|
| HTMX | 2.0.0 | MIT | Interactivity |
| Chart.js | latest | MIT | Trend charts |

## License policy
Only permissive licenses are permitted: MIT, Apache 2.0, PSF, Public Domain, BSD-3-Clause.
GPL/AGPL and copyleft licenses are forbidden in the application stack.
