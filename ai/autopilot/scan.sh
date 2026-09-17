#!/usr/bin/env bash
# Thin wrapper: source config, export it, hand off to scan.py.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=config.sh
source "$DIR/config.sh"
export HOME_REPOS ISSUE_ORGS REVIEW_CMD REVIEW_LEVEL MAX_ACTIVE
export STALE_HOURS ISSUE_MAX_AGE_DAYS STATE_DIR STATE_FILE PROMPT_DIR
exec python3 "$DIR/scan.py" "$@"
