#!/usr/bin/env bash
# Build the Octopilot workspace, or focus it if it already exists and add
# whatever it is missing. Run by the plugin's `open` action.
#
# Tab "OCTOPILOT": on the left the orchestrator's messenger pane (small,
# on top) and the user's prompter pane below it, the dashboard on the right.
# Tab "Octopilot (code changes)": a claude in the dotfiles, for changing
# octopilot itself.
#
# Nothing is ever typed into the prompter: agent reports and dashboard
# commands go to the orchestrator's inbox, and the prompter queues the user's
# commands there too (plugin/skills/prompter).
set -euo pipefail
H="${HERDR_BIN_PATH:-herdr}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="Octopilot"
ORCH_AGENT="octopilot"             # scan.py's ORCH_AGENT
PROMPTER_AGENT="octopilot-prompter"
MESSENGER_RATIO=0.35                   # the messenger pane's share: room for the takoyaki band
MAIN_TAB="OCTOPILOT"
CODE_TAB="Octopilot (code changes)"
CODE_AGENT="octopilot-code"
CODE_CWD="$(cd "$DIR/../.." && pwd)"   # the dotfiles checkout

# Split the orchestrator's pane down and start the prompter in the new pane.
add_prompter() {
  local split pane
  split=$("$H" pane split "$1" --direction down --ratio "$MESSENGER_RATIO" --focus)
  pane=$(jq -r '.result.pane.pane_id // .result.pane_id' <<<"$split")
  "$H" pane rename "$pane" "prompter" >/dev/null
  "$H" agent start "$PROMPTER_AGENT" --kind claude --pane "$pane" \
    --timeout 60000 >/dev/null || return 0
  # A brand-new pane: nobody is typing in it yet.
  "$H" agent prompt "$PROMPTER_AGENT" "/octopilot:prompter" >/dev/null || true
}

# The code-changes tab, unless the workspace has one; a claude starts in it.
add_code_tab() {
  local tabs created pane
  tabs=$("$H" tab list --workspace "$1")
  jq -e --arg l "$CODE_TAB" '.result.tabs[] | select(.label == $l)' \
    <<<"$tabs" >/dev/null && return 0
  created=$("$H" tab create --workspace "$1" --label "$CODE_TAB" \
    --cwd "$CODE_CWD" --no-focus)
  pane=$(jq -r '.result.root_pane.pane_id' <<<"$created")
  "$H" agent start "$CODE_AGENT" --kind claude --pane "$pane" \
    --timeout 60000 >/dev/null || true
}

# The tab holding the orchestrator's pane is the main one.
name_main_tab() {
  local tab
  tab=$("$H" pane list | jq -r --arg p "$1" \
    '.result.panes[] | select(.pane_id == $p) | .tab_id')
  [ -n "$tab" ] && "$H" tab rename "$tab" "$MAIN_TAB" >/dev/null
}

ws=$("$H" workspace list | jq -r --arg l "$LABEL" \
  '.result.workspaces[] | select(.label == $l) | .workspace_id' | head -n1)
if [ -n "$ws" ]; then
  "$H" workspace focus "$ws" >/dev/null
  orch_pane=$("$H" agent get "$ORCH_AGENT" 2>/dev/null |
    jq -r --arg w "$ws" '.result.agent | select(.workspace_id == $w) | .pane_id' ||
    true)
  if [ -n "$orch_pane" ]; then
    name_main_tab "$orch_pane"
    "$H" agent get "$PROMPTER_AGENT" >/dev/null 2>&1 || add_prompter "$orch_pane"
  fi
  add_code_tab "$ws"
  exit 0
fi

set -a
# shellcheck source=../config.sh
source "$DIR/config.sh"
set +a
# "herdr:<agent>".
orch="${OCTOPILOT_ORCH:-$(jq -r '.orch // empty' "$STATE_FILE" 2>/dev/null || true)}"
name="${orch#herdr:}"
name="${name:-$ORCH_AGENT}"

# An orchestrator already running as a herdr agent elsewhere: go to it rather
# than starting a second one.
if "$H" agent get "$name" >/dev/null 2>&1; then
  exec "$H" agent focus "$name"
fi

created=$("$H" workspace create --label "$LABEL" \
  --cwd "${OCTOPILOT_ORCH_CWD:-$HOME}" --focus)
root=$(jq -r '.result.root_pane.pane_id' <<<"$created")
"$H" pane rename "$root" "messenger" >/dev/null
name_main_tab "$root"

# A fresh claude, named so workers and the dashboard can address it. It waits
# for you: type /octopilot:messenger to start ticking.
"$H" agent start "$name" --kind claude --pane "$root" \
  --timeout 60000 >/dev/null || true

# The dashboard first, so it takes the full height on the right; the prompter
# then splits only the left column.
"$H" plugin pane open --plugin elboletaire.octopilot --entrypoint dashboard \
  --placement split --target-pane "$root" \
  --direction right --no-focus >/dev/null
add_prompter "$root"
add_code_tab "$(jq -r '.result.workspace.workspace_id // .result.workspace_id' <<<"$created")"
