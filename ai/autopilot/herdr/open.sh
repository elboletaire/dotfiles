#!/usr/bin/env bash
# Build the Autopilot workspace -- orchestrator on the left, dashboard on the
# right -- or focus it if it already exists. Run by the plugin's `open` action.
set -euo pipefail
H="${HERDR_BIN_PATH:-herdr}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="Autopilot"
ORCH_AGENT="autopilot"   # scan.py's ORCH_AGENT

ws=$("$H" workspace list | jq -r --arg l "$LABEL" \
  '.result.workspaces[] | select(.label == $l) | .workspace_id' | head -n1)
if [ -n "$ws" ]; then
  exec "$H" workspace focus "$ws"
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
"$H" pane rename "$root" "orchestrator" >/dev/null

if [[ -n "$orch" && "$orch" != herdr:* ]]; then
  # Still in aoe (started before the switch): this pane is a window onto it.
  "$H" pane run "$root" "aoe session attach $(printf '%q' "${orch#aoe:}")" >/dev/null
else
  # A fresh claude, named so workers and the dashboard can address it. It
  # waits for you: type /pr-autopilot to start ticking.
  "$H" agent start "${name:-$ORCH_AGENT}" --kind claude --pane "$root" \
    --timeout 60000 >/dev/null || true
fi

"$H" plugin pane open --plugin elboletaire.autopilot --entrypoint dashboard \
  --placement split --target-pane "$root" \
  --direction right --no-focus >/dev/null
