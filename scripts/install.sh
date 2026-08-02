#!/usr/bin/env bash
set -euo pipefail
DEST=${1:-/opt/nms-nova}
REPO_URL="https://github.com/Packet-Loss-HQ/nms-nova.git"
echo "Installing NMS-Nova to ${DEST}"
mkdir -p "${DEST}"
if [ ! -d "${DEST}/.git" ]; then
  git clone "${REPO_URL}" "${DEST}"
else
  git -C "${DEST}" pull --rebase
fi
cd "${DEST}"
python3 -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.txt
cp targets.yaml.example targets.yaml || true
mkdir -p secrets state backups
chmod 700 secrets
cat > secrets/README.txt << 'README'
Place secrets here: telegram.env, nms-probe, etc.
These files are git-ignored and should not be committed.
README
if command -v systemctl >/dev/null 2>&1; then
  cp scripts/nms-nova-fastapi.service /etc/systemd/system/
  cp scripts/nms-nova-poller.service /etc/systemd/system/
  cp scripts/nms-nova-retention.service /etc/systemd/system/
  cp scripts/nms-nova-retention.timer /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable --now nms-nova-fastapi nms-nova-poller nms-nova-retention.timer
fi
echo "Install complete. Edit ${DEST}/targets.yaml and secrets before use."
