#!/bin/bash
# SessionStart-hook voor Claude Code on the web: zorgt dat `requests` (de enige
# dependency) er is, zodat de tests en het script meteen draaien.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"
python -m pip install --quiet --disable-pip-version-check --root-user-action=ignore -r requirements.txt
