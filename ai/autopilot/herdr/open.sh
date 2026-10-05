#!/usr/bin/env bash
# Build the Autopilot workspace -- orchestrator on the left, dashboard on the
# right -- or focus it if it already exists. Run by the plugin's `open` action.
set -euo pipefail
H="${HERDR_BIN_PATH:-herdr}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="Autopilot"

ws=$("$H" workspace list | jq -r --arg l "$LABEL" \
  '.result.workspaces[] | select(.label == $l) | .workspace_id' | head -n1)
if [ -n "$ws" ]; then
  exec "$H" workspace focus "$ws"
fi

created=$("$H" workspace create --label "$LABEL" --cwd "$HOME" --focus)
ws=$(jq -r '.result.workspace.workspace_id' <<<"$created")
root=$(jq -r '.result.root_pane.pane_id' <<<"$created")

# The orchestrator is the aoe session that last ran a tick (or AUTOPILOT_ORCH).
# Until the workers move to herdr it stays in aoe; this pane is a window onto it.
set -a
# shellcheck source=../config.sh
source "$DIR/config.sh"
set +a
orch="${AUTOPILOT_ORCH:-$(jq -r '.orch // empty' "$STATE_FILE" 2>/dev/null || true)}"
if [ -n "$orch" ]; then
  "$H" pane rename "$root" "orchestrator" >/dev/null
  "$H" pane run "$root" "aoe session attach $(printf '%q' "$orch")" >/dev/null
else
  "$H" pane run "$root" "echo 'No orchestrator recorded yet: start /pr-autopilot in aoe, then rerun this action.'" >/dev/null
fi

"$H" plugin pane open --plugin elboletaire.autopilot --entrypoint dashboard \
  --placement split --target-pane "$root" \
  --direction right --focus >/dev/null
