#!/usr/bin/env bash
# The GUI twin of open.sh: the Octopilot space in herdr-app, with three tabs:
#   OCTOPILOT: the octopilot-dashboard and octopilot-chat mods
#   engine: the orchestrator, the prompter and the headless dashboard, as hc terminals
#   Octopilot (code changes): a claude for changing octopilot itself
# Each claude is labelled octopilot.agent=<name> and octopilot.session=<uuid>
# (its transcript, read by scan.py speech and chat). --terminals builds the
# TUI-style layout instead. After building it switches to the `octopilot`
# layout (the kitchen corner) when herdr-app/install.sh made one and the
# shown layout is `main` (a layout you picked stays); --no-layout
# skips that. --close-launcher closes this terminal's own pane at the end (the
# tab goes with its last pane), for the key or the palette (programs.json).
# From a worktree it needs OCTOPILOT_STATE_DIR (see herdr/README.md).
set -euo pipefail
APP="herdr-app"
HC="hc"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
LIVE_DIR="$(cd "$HOME/.dotfiles/ai/octopilot" 2>/dev/null && pwd -P || echo "$HOME/.dotfiles/ai/octopilot")"
LABEL="Octopilot"
ORCH_AGENT="octopilot"                 # scan.py's ORCH_AGENT
PROMPTER_AGENT="octopilot-prompter"    # scan.py's PROMPTER_AGENT
HEADLESS_AGENT="octopilot-headless"    # the engine tab's dashboard.sh --headless
CODE_AGENT="octopilot-code"            # scan.py's CODE_AGENT
MAIN_TAB="OCTOPILOT"
ENGINE_TAB="engine"
CODE_TAB="Octopilot (code changes)"
CODE_CWD="$(cd "$DIR/../.." && pwd -P)"   # the checkout this octopilot lives in

TERMINALS=0
CLOSE_LAUNCHER=0
LAYOUT=1
for arg in "$@"; do
  case "$arg" in
    --terminals) TERMINALS=1 ;;
    --close-launcher) CLOSE_LAUNCHER=1 ;;
    --no-layout) LAYOUT=0 ;;
    -h|--help) echo "usage: open-gui.sh [--terminals] [--no-layout] [--close-launcher]"; exit 0 ;;
    *) echo "open-gui.sh: unknown argument $arg" >&2; exit 2 ;;
  esac
done

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

# The props of the mods, which read their octopilot from them.
MOD_PROPS="$(jq -nc --arg dir "$DIR" --arg state "$STATE_DIR" '{dir: $dir, state_dir: $state}')"

# `herdr-app ...` with its output on stdout; a failure stops here with the
# output it printed, so a refused command says why.
app() {
  local out
  if ! out=$("$APP" "$@" 2>&1); then
    echo "open-gui.sh: $APP $* failed: $out" >&2
    exit 1
  fi
  printf '%s\n' "$out"
}

# A JSON argv array from its arguments, as herdr-app takes it.
argv_json() {
  jq -nc '$ARGS.positional' --args -- "$@"
}

# A fresh session id for a claude that is started with --session-id.
new_session() {
  uuidgen | tr '[:upper:]' '[:lower:]'
}

# The --settings that put a worktree's octopilot plugin in place of the
# installed one (empty on the live checkout), for every claude started here.
SETTINGS="$(OCTOPILOT_DIR="$DIR" "$DIR/scan.sh" plugin-settings)"

# argv for a claude session: its session id (empty: none), optionally started
# with a prompt.
session_argv() {
  local args=(env "${envs[@]}" claude)
  if [ -n "$SETTINGS" ]; then args+=(--settings "$SETTINGS"); fi
  if [ -n "${1:-}" ]; then args+=(--session-id "$1"); fi
  if [ -n "${2:-}" ]; then args+=("$2"); fi
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

# Labels a terminal as an agent: its name, and for a claude its session id.
name_agent() {
  local labels=("octopilot.agent=$2")
  if [ -n "${3:-}" ]; then labels+=("octopilot.session=$3"); fi
  "$HC" label "$1" "${labels[@]}" >/dev/null
}

# The octopilot dir an orchestrator runs from. Labels are global, so one from
# before octopilot.dir existed belongs to the live checkout.
owner_dir() {
  "$HC" get "$1" --json | jq -r --arg d "$LIVE_DIR" '.labels["octopilot.dir"] // $d'
}

# Split a pane (direction: right or down) and start the prompter in the new one.
add_prompter() {
  local split session
  session=$(new_session)
  split=$(app do pane.split --direction "$2" --pane "$1" \
    --argv "$(session_argv "$session" "/octopilot:prompter")")
  app do pane.rename --pane "$(jq -r '.pane' <<<"$split")" --name prompter >/dev/null
  name_agent "$(jq -r '.terminal' <<<"$split")" "$PROMPTER_AGENT" "$session"
}

# Split the orchestrator's pane down and run the headless dashboard in it: the
# loops that feed view.json, which the mods show.
add_headless() {
  local split
  split=$(app do pane.split --direction down --pane "$1" \
    --argv "$(argv_json env "${envs[@]}" bash "$DIR/dashboard.sh" --headless)")
  app do pane.rename --pane "$(jq -r '.pane' <<<"$split")" --name headless >/dev/null
  name_agent "$(jq -r '.terminal' <<<"$split")" "$HEADLESS_AGENT"
}

# The engine tab's helpers under the orchestrator's pane, those that are missing.
add_engine_agents() {
  if [ -z "$(agent_term "$HEADLESS_AGENT")" ]; then add_headless "$1"; fi
  if [ -z "$(agent_term "$PROMPTER_AGENT")" ]; then add_prompter "$1" right; fi
}

# The OCTOPILOT tab, unless the space has one: the dashboard mod, and the chat
# mod (the prompter) beside it.
add_main_tab() {
  local created pane
  if [ -n "$(tab_named "$1" "$MAIN_TAB")" ]; then return 0; fi
  created=$(app do tab.new --space "$1" --name "$MAIN_TAB" \
    --mod octopilot-dashboard --props "$MOD_PROPS" --focus false)
  pane=$(jq -r '.pane // empty' <<<"$created")
  if [ -z "$pane" ]; then
    echo "open-gui.sh: the $MAIN_TAB tab has no pane to split the chat into" >&2
    exit 1
  fi
  app do pane.split --direction right --pane "$pane" \
    --mod octopilot-chat --props "$MOD_PROPS" >/dev/null
}

# The code-changes tab, unless the space has one; a claude starts in it.
add_code_tab() {
  local created
  if [ -n "$(tab_named "$1" "$CODE_TAB")" ]; then return 0; fi
  created=$(app do tab.new --space "$1" --name "$CODE_TAB" --folder "$CODE_CWD" \
    --argv "$(session_argv "" "")" --focus false)
  name_agent "$(jq -r '.terminal' <<<"$created")" "$CODE_AGENT"
}

# The terminal of a dashboard.sh run as the TUI layout's curses dashboard, if
# the space has one: a second dashboard loop next to the headless one. herdr-app
# runs an argv inside a shell, so the foreground's argv and the pane's name
# (`dashboard`, as the TUI layout's builder gives it) count too.
legacy_dashboard() {
  local t
  for t in $("$APP" ls | jq -r --arg s "$1" \
    '.spaces[] | select(.id == $s) | .tabs[].terminals[] |
      select(.name == "dashboard") | .terminal'); do
    echo "$t"
    return 0
  done
  for t in $("$APP" ls | jq -r --arg s "$1" \
    '.spaces[] | select(.id == $s) | .tabs[].terminals[].terminal'); do
    if "$HC" get "$t" --json | jq -e '[(.argv // []), (.foreground.argv // [])] |
      any(join(" ") | test("dashboard[.]sh") and (test("--headless") | not))' >/dev/null; then
      echo "$t"
      return 0
    fi
  done
}

# Closes this terminal's own pane, so no idle launcher tab stays behind (a tab
# whose last pane closes goes with it). Never the tab itself: the terminal may
# share it with panes that are not ours. The last step of a path that worked.
close_launcher() {
  local located pane
  if [ -z "${HC_TERMINAL_ID:-}" ]; then return 0; fi
  located=$(locate "$HC_TERMINAL_ID") || return 0
  IFS=$'\t' read -r _ _ pane <<<"$located"
  if [ -z "$pane" ]; then return 0; fi
  app do pane.close --pane "$pane" >/dev/null
}

# Runs at the end of every path that did its work: the octopilot layout (the
# kitchen corner), then the launcher's own pane.
finish() {
  if [ "$TERMINALS" = 0 ] && [ "$LAYOUT" = 1 ] && layout_exists octopilot \
    && [ "$("$APP" status | jq -r '.layout // empty')" = main ]; then
    app do layout.switch --name octopilot >/dev/null
  fi
  if [ "$CLOSE_LAUNCHER" = 1 ]; then close_launcher; fi
}

# True when herdr-app has a layout of this name (layouts/<name>.json).
layout_exists() {
  [ -f "${HERDR_APP_HOME:-$HOME/.config/herdr-app}/layouts/$1.json" ]
}

# Shows the space and its OCTOPILOT tab.
focus_main() {
  app do space.select --id "$1" >/dev/null
  app do tab.select --id "$(tab_named "$1" "$MAIN_TAB")" >/dev/null
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
  if [ "$TERMINALS" = 1 ]; then
    if [ -n "$(tab_named "$space" "$MAIN_TAB")" ] && [ "$(tab_named "$space" "$MAIN_TAB")" != "$tab" ]; then
      echo "open-gui.sh: the space already has an $MAIN_TAB tab (the GUI layout);" \
        "run without --terminals" >&2
      exit 1
    fi
    app do tab.rename --id "$tab" --name "$MAIN_TAB" >/dev/null
    if [ -z "$(agent_term "$PROMPTER_AGENT")" ]; then add_prompter "$pane" down; fi
    add_code_tab "$space"
    app do agent.focus --terminal "$orch" >/dev/null
  else
    old=$(legacy_dashboard "$space")
    if [ -n "$old" ]; then
      echo "open-gui.sh: terminal $old is the curses dashboard of the TUI layout;" \
        "close its pane first (two dashboards would run), or use --terminals" >&2
      exit 1
    fi
    app do tab.rename --id "$tab" --name "$ENGINE_TAB" >/dev/null
    add_engine_agents "$pane"
    add_main_tab "$space"
    add_code_tab "$space"
    focus_main "$space"
  fi
  finish
  exit 0
fi

# The orchestrator in its own space, in its folder, started ticking straight away.
session=$(new_session)
tab_name="$ENGINE_TAB"
if [ "$TERMINALS" = 1 ]; then tab_name="$MAIN_TAB"; fi
created=$(app do space.new --name "$LABEL" --folder "$OCTOPILOT_ORCH_CWD" \
  --tab "$tab_name" --argv "$(session_argv "$session" "/octopilot:messenger")" --focus false)
space=$(jq -r '.space' <<<"$created")
orch=$(jq -r '.terminal' <<<"$created")
"$HC" label "$orch" "octopilot.agent=$ORCH_AGENT" "octopilot.dir=$DIR" \
  "octopilot.session=$session" >/dev/null
root=$(locate "$orch" | cut -f3)
if [ -z "$root" ]; then
  echo "open-gui.sh: the new $ORCH_AGENT terminal ($orch) is not in a Herdr space" >&2
  exit 1
fi

if [ "$TERMINALS" = 1 ]; then
  app do pane.rename --pane "$root" --name messenger >/dev/null
  # The dashboard first, so it takes the full height on the right; the prompter
  # then splits only the messenger's column.
  dash=$(app do pane.split --direction right --pane "$root" \
    --argv "$(argv_json env "${envs[@]}" bash "$DIR/dashboard.sh")")
  app do pane.rename --pane "$(jq -r '.pane' <<<"$dash")" --name dashboard >/dev/null
  add_prompter "$root" down
  add_code_tab "$space"
  app do agent.focus --terminal "$orch" >/dev/null
else
  add_engine_agents "$root"
  add_main_tab "$space"
  add_code_tab "$space"
  focus_main "$space"
fi
finish
