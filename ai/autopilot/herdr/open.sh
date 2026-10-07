#!/usr/bin/env bash
# Build the Autopilot workspace -- on the left the orchestrator's
# communications pane (small, on top) and the user's prompter pane below it,
# the dashboard on the right -- or focus it if it already exists, adding the
# prompter if it is missing. Run by the plugin's `open` action.
#
# Nothing is ever typed into the prompter: agent reports and dashboard
# commands go to the orchestrator's inbox, and the prompter queues the user's
# commands there too (skills/autopilot-prompter).
set -euo pipefail
H="${HERDR_BIN_PATH:-herdr}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="Autopilot"
ORCH_AGENT="autopilot"             # scan.py's ORCH_AGENT
PROMPTER_AGENT="autopilot-prompter"
COMMS_RATIO=0.35                   # the communications pane's share: room for the takoyaki band

# Split the orchestrator's pane down and start the prompter in the new pane.
add_prompter() {
  local split pane
  split=$("$H" pane split "$1" --direction down --ratio "$COMMS_RATIO" --focus)
  pane=$(jq -r '.result.pane.pane_id // .result.pane_id' <<<"$split")
  "$H" pane rename "$pane" "prompter" >/dev/null
  "$H" agent start "$PROMPTER_AGENT" --kind claude --pane "$pane" \
    --timeout 60000 >/dev/null || return 0
  # A brand-new pane: nobody is typing in it yet.
  "$H" agent prompt "$PROMPTER_AGENT" "/autopilot-prompter" >/dev/null || true
}

ws=$("$H" workspace list | jq -r --arg l "$LABEL" \
  '.result.workspaces[] | select(.label == $l) | .workspace_id' | head -n1)
if [ -n "$ws" ]; then
  "$H" workspace focus "$ws" >/dev/null
  if ! "$H" agent get "$PROMPTER_AGENT" >/dev/null 2>&1; then
    orch_pane=$("$H" agent get "$ORCH_AGENT" 2>/dev/null |
      jq -r --arg w "$ws" '.result.agent | select(.workspace_id == $w) | .pane_id' ||
      true)
    [ -n "$orch_pane" ] && add_prompter "$orch_pane"
  fi
  exit 0
fi

set -a
# shellcheck source=../config.sh
source "$DIR/config.sh"
set +a
# "herdr:<agent>" or "aoe:<session>"; a bare value predates herdr and is aoe.
orch="${AUTOPILOT_ORCH:-$(jq -r '.orch // empty' "$STATE_FILE" 2>/dev/null || true)}"

# An orchestrator already running as a herdr agent elsewhere: go to it rather
# than starting a second one.
if [[ -z "$orch" || "$orch" == herdr:* ]]; then
  name="${orch#herdr:}"
  name="${name:-$ORCH_AGENT}"
  if "$H" agent get "$name" >/dev/null 2>&1; then
    exec "$H" agent focus "$name"
  fi
fi

created=$("$H" workspace create --label "$LABEL" \
  --cwd "${AUTOPILOT_ORCH_CWD:-$HOME}" --focus)
root=$(jq -r '.result.root_pane.pane_id' <<<"$created")
"$H" pane rename "$root" "communications" >/dev/null

if [[ -n "$orch" && "$orch" != herdr:* ]]; then
  # Still in aoe (started before the switch): this pane is a window onto it.
  "$H" pane run "$root" "aoe session attach $(printf '%q' "${orch#aoe:}")" >/dev/null
else
  # A fresh claude, named so workers and the dashboard can address it. It
  # waits for you: type /pr-autopilot to start ticking.
  "$H" agent start "${name:-$ORCH_AGENT}" --kind claude --pane "$root" \
    --timeout 60000 >/dev/null || true
fi

# The dashboard first, so it takes the full height on the right; the prompter
# then splits only the left column.
"$H" plugin pane open --plugin elboletaire.autopilot --entrypoint dashboard \
  --placement split --target-pane "$root" \
  --direction right --no-focus >/dev/null
add_prompter "$root"
