#!/usr/bin/env bash
# The GUI twin of open.sh: the Octopilot space in herdr-app, each claude an hc
# terminal labelled octopilot.agent=<name>. From a worktree it needs
# OCTOPILOT_STATE_DIR (see herdr/README.md, "GUI (herdr-app)").
set -euo pipefail
APP="herdr-app"
HC="hc"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
LIVE_DIR="$(cd "$HOME/.dotfiles/ai/octopilot" 2>/dev/null && pwd -P || echo "$HOME/.dotfiles/ai/octopilot")"
LABEL="Octopilot"
ORCH_AGENT="octopilot"                 # scan.py's ORCH_AGENT
PROMPTER_AGENT="octopilot-prompter"
CODE_AGENT="octopilot-code"            # scan.py's CODE_AGENT
MAIN_TAB="OCTOPILOT"
CODE_TAB="Octopilot (code changes)"
CODE_CWD="$(cd "$DIR/../.." && pwd -P)"   # the checkout this octopilot lives in

if [ "$DIR" != "$LIVE_DIR" ] && [ -z "${OCTOPILOT_STATE_DIR:-}" ]; then
  echo "open-gui.sh: $DIR is not the live octopilot ($LIVE_DIR), and would" \
    "share its state.json. Set OCTOPILOT_STATE_DIR to a scratch state dir." >&2
  exit 1
fi

# The scope knobs the caller set, read before config.sh supplies its defaults:
# only these are forwarded, so the defaults keep applying to the sessions.
declare -a scope=()
for v in HOME_REPOS ISSUE_ORGS CLONE_ROOTS; do
  if [ -n "${!v:-}" ]; then scope+=("$v=${!v}"); fi
done

set -a
# shellcheck source=../config.sh
source "$DIR/config.sh"
set +a

# Every session and pane started here gets the hc backend, this octopilot's
# directory (the skills' scan.sh, see OCTOPILOT_DIR in plugin/skills), and the
# state dir and scope knobs a test sets.
envs=(OCTOPILOT_BACKEND=hc "OCTOPILOT_DIR=$DIR")
if [ -n "${OCTOPILOT_STATE_DIR:-}" ]; then envs+=("OCTOPILOT_STATE_DIR=$OCTOPILOT_STATE_DIR"); fi
envs+=("${scope[@]+"${scope[@]}"}")

# A JSON argv array from its arguments, as herdr-app takes it.
argv_json() {
  jq -nc '$ARGS.positional' --args -- "$@"
}

# The --settings that put a worktree's octopilot plugin in place of the
# installed one (empty on the live checkout), for every claude started here.
SETTINGS="$(OCTOPILOT_DIR="$DIR" "$DIR/scan.sh" plugin-settings)"

# argv for a claude session, optionally started with a prompt.
session_argv() {
  local args=(env "${envs[@]}" claude)
  if [ -n "$SETTINGS" ]; then args+=(--settings "$SETTINGS"); fi
  if [ -n "${1:-}" ]; then args+=("$1"); fi
  argv_json "${args[@]}"
}

# The address of the live hc terminal labelled as an octopilot agent, if any.
agent_term() {
  "$HC" ls --json --label "octopilot.agent=$1" | jq -r '.terminals[0].address // empty'
}

# "space tab pane" of a terminal as herdr-app shows it, if it shows it.
locate() {
  "$APP" ls | jq -r --arg t "$1" '.spaces[] as $s | $s.tabs[] as $tab |
    $tab.terminals[] | select(.terminal == $t) | [$s.id, $tab.id, .pane] | @tsv'
}

# The id of a tab of a space by its name, if it has one.
tab_named() {
  "$APP" ls | jq -r --arg s "$1" --arg n "$2" \
    '.spaces[] | select(.id == $s) | .tabs[] | select(.name == $n) | .id' | head -n1
}

name_agent() {
  "$HC" label "$1" "octopilot.agent=$2" >/dev/null
}

# The octopilot dir an orchestrator runs from. Labels are global, so one from
# before octopilot.dir existed belongs to the live checkout.
owner_dir() {
  "$HC" get "$1" --json | jq -r --arg d "$LIVE_DIR" '.labels["octopilot.dir"] // $d'
}

# Split the messenger pane down and start the prompter in the new pane.
add_prompter() {
  local split
  split=$("$APP" do pane.split --direction down --pane "$1" \
    --argv "$(session_argv "/octopilot:prompter")")
  "$APP" do pane.rename --pane "$(jq -r '.pane' <<<"$split")" --name prompter >/dev/null
  name_agent "$(jq -r '.terminal' <<<"$split")" "$PROMPTER_AGENT"
}

# The code-changes tab, unless the space has one; a claude starts in it.
add_code_tab() {
  local created
  if [ -n "$(tab_named "$1" "$CODE_TAB")" ]; then return 0; fi
  created=$("$APP" do tab.new --space "$1" --name "$CODE_TAB" --folder "$CODE_CWD" \
    --argv "$(session_argv)" --focus false)
  name_agent "$(jq -r '.terminal' <<<"$created")" "$CODE_AGENT"
}

orch=$(agent_term "$ORCH_AGENT")
if [ -n "$orch" ]; then
  if [ "$(owner_dir "$orch")" != "$DIR" ]; then
    echo "open-gui.sh: the $ORCH_AGENT agent ($orch) runs from another octopilot" \
      "(not $DIR). Close it, or run this from its own checkout." >&2
    exit 1
  fi
  located=$(locate "$orch")
  if [ -z "$located" ]; then
    echo "open-gui.sh: the $ORCH_AGENT agent ($orch) is not in a Herdr space" >&2
    exit 1
  fi
  IFS=$'\t' read -r space tab pane <<<"$located"
  "$APP" do tab.rename --id "$tab" --name "$MAIN_TAB" >/dev/null
  "$APP" do agent.focus --terminal "$orch" >/dev/null
  if [ -z "$(agent_term "$PROMPTER_AGENT")" ]; then add_prompter "$pane"; fi
  add_code_tab "$space"
  exit 0
fi

# The orchestrator in its own space, in its folder, started ticking straight away.
created=$("$APP" do space.new --name "$LABEL" --folder "$OCTOPILOT_ORCH_CWD" \
  --tab "$MAIN_TAB" --argv "$(session_argv "/octopilot:messenger")")
space=$(jq -r '.space' <<<"$created")
orch=$(jq -r '.terminal' <<<"$created")
"$HC" label "$orch" "octopilot.agent=$ORCH_AGENT" "octopilot.dir=$DIR" >/dev/null
root=$(locate "$orch" | cut -f3)
if [ -z "$root" ]; then
  echo "open-gui.sh: the new $ORCH_AGENT terminal ($orch) is not in a Herdr space" >&2
  exit 1
fi
"$APP" do pane.rename --pane "$root" --name messenger >/dev/null

# The dashboard first, so it takes the full height on the right; the prompter
# then splits only the messenger's column.
dash=$("$APP" do pane.split --direction right --pane "$root" \
  --argv "$(argv_json env "${envs[@]}" bash "$DIR/dashboard.sh")")
"$APP" do pane.rename --pane "$(jq -r '.pane' <<<"$dash")" --name dashboard >/dev/null
add_prompter "$root"
add_code_tab "$space"
"$APP" do agent.focus --terminal "$orch" >/dev/null
