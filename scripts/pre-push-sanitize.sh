#!/usr/bin/env bash
# Lightweight pre-push guard for public repos.
set -euo pipefail

PATTERNS='10\.0\.(110|120)\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[0-1])\.|ct10[1-9]|ct1[1-9][0-9]|aether|YWRtaW46|github_pat|aether_host_key|telegram\.env|chat_id|webhook_secret|NMS_API_TOKEN|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID'

# Check staged files against patterns
if git diff --cached --name-only | grep -E '\.(py|yml|yaml|md|txt|json|service|sh|env)$' >/dev/null 2>&1; then
  matches=$(git diff --cached --name-only | grep -E '\.(py|yml|yaml|md|txt|json|service|sh|env)$' | xargs grep -nE "$PATTERNS" 2>/dev/null || true)
  if [ -n "$matches" ]; then
    echo "Potential sensitive content detected in staged files:"
    echo "$matches"
    echo "Aborting push. Remove or sanitize the above before pushing."
    exit 1
  fi
fi

exit 0
