#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST="${PLIST_DIR}/com.jarvis.ironman.plist"

mkdir -p "${PLIST_DIR}" "${ROOT}/data/logs"

sed \
  -e "s#\/Users\/mac\/Desktop\/jarvis-ironman-main#${ROOT}#g" \
  "${ROOT}/launchd/com.jarvis.ironman.plist" > "${PLIST}"

launchctl bootout "gui/$(id -u)" "${PLIST}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST}"
launchctl enable "gui/$(id -u)/com.jarvis.ironman"
echo "JARVIS 7/24 service installed: ${PLIST}"
