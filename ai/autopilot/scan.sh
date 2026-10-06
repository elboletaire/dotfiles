#!/usr/bin/env bash
# Thin wrapper: source config, export it, hand off to scan.py.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=config.sh
source "$DIR/config.sh"
export HOME_REPOS ISSUE_ORGS REVIEW_CMD REVIEW_LEVEL REVIEW_LEVEL_FOLLOWUP REVIEW_LEVEL_COMMENT MAX_ACTIVE MAX_REVIEW_ROUNDS
export STALE_HOURS ISSUE_MAX_AGE_DAYS STATE_DIR STATE_FILE PROMPT_DIR WIND_DOWN_AT
export AGENT_STALL_MIN RE_REVIEW_QUIET_HOURS CLONE_ROOTS CLONE_PREFER AUTOPILOT_GROUP
export MODEL_WORK MODEL_INVESTIGATE MODEL_REVIEW_FIX MODEL_REVIEW_COMMENT
export MODEL_COLD_REVIEW AUTOPILOT_ORCH DASHBOARD_REFRESH_SECS AUTOPILOT_BACKEND

# The orchestrator's doorbell, for its Monitor: one line per agent report or
# dashboard request. It only says "look"; `inbox` holds the messages. -F
# follows the log across the trims that replace the file.
if [[ "${1:-}" == "doorbell" ]]; then
  events="$(dirname "$STATE_FILE")/events.jsonl"
  touch "$events"
  tail -n 0 -F "$events" 2>/dev/null |
    grep --line-buffered -E '"kind": "(report|request)"'
  exit
fi

exec python3 "$DIR/scan.py" "$@"
