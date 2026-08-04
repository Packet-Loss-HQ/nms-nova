#!/usr/bin/env bash
set -euo pipefail

DEST=${1:-/opt/nms-nova}
REPO_URL="https://github.com/Packet-Loss-HQ/nms-nova.git"

echo "Installing NMS-Nova to ${DEST}"

# Python version check
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but not installed." >&2
  exit 1
fi
PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
case "${PYVER}" in
  3.11|3.12|3.13) ;;
  *)
    echo "NMS-Nova requires Python 3.11-3.13. Detected: ${PYVER}" >&2
    exit 1
    ;;
esac

mkdir -p "${DEST}"
if [ ! -d "${DEST}/.git" ]; then
  git clone "${REPO_URL}" "${DEST}"
else
  echo "Existing install detected at ${DEST}. Upgrading..."
  git -C "${DEST}" pull --rebase
fi
cd "${DEST}"

# Create venv and install deps
python3 -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.txt
if [ "${NMS_SNMP:-0}" = "1" ]; then
  .venv/bin/pip install --no-cache-dir "pysnmp>=1.5,<2"
fi

# First-run setup
if [ ! -f targets.yaml ]; then
  cp targets.yaml.example targets.yaml
  echo "Created targets.yaml from example."
fi
mkdir -p secrets state backups
chmod 700 secrets

# Systemd install
if command -v systemctl >/dev/null 2>&1; then
  for svc in nms-nova-fastapi nms-nova-poller nms-nova-retention nms-nova-retention.timer; do
    if [ -f "scripts/${svc}.service" ] || [ -f "scripts/${svc}.timer" ]; then
      cp "scripts/${svc}.*" /etc/systemd/system/ 2>/dev/null || true
    fi
  done
  systemctl daemon-reload
  systemctl enable --now nms-nova-fastapi nms-nova-poller nms-nova-retention.timer
fi

# Validate service started
if command -v systemctl >/dev/null 2>&1; then
  if ! systemctl is-active --quiet nms-nova-fastapi; then
    echo "FastAPI service did not start. Run: journalctl -u nms-nova-fastapi -n 200" >&2
    exit 1
  fi
fi

cat <<'EOS'

Install complete.
1. Edit targets.yaml and secrets before use.
2. Open http://<host>:8000/setup to add targets or load demo data.
3. Configure Telegram/webhook delivery in Settings.
4. Upgrade later with: git pull && .venv/bin/pip install -r requirements.txt && systemctl restart nms-nova-fastapi

EOS
