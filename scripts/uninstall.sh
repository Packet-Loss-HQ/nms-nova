#!/usr/bin/env bash
set -euo pipefail

echo "This will remove NMS-Nova and stop its services."
read -p "Continue? [y/N] " -r
if [[ ! ${REPLY:-} =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 1
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl disable --now nms-nova-fastapi nms-nova-poller nms-nova-retention.timer || true
  rm -f /etc/systemd/system/nms-nova-*
  systemctl daemon-reload
fi

echo "Removing /opt/nms-nova ..."
rm -rf /opt/nms-nova

echo "Uninstall complete."
