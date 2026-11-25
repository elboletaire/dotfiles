#!/usr/bin/env bash
# The GUI twin of open.sh: the Octopilot space in herdr-app, with three tabs:
#   OCTOPILOT: the octopilot-dashboard mod on the left; on the right the
#     octopilot-chat mod over the octopilot-kitchen mod (KITCHEN_PX tall)
#   engine: the orchestrator, the prompter and the headless dashboard, as hc
#     terminals; parked after building (no pane, still running), so the tab goes away
#   Octopilot (code changes): the code agent's own claude (a terminal, never parked)
#     beside the octopilot-side panel
# Each claude is labelled octopilot.agent=<name> and octopilot.session=<uuid>
# (its transcript, read by scan.py speech and chat). --terminals builds the
# TUI-style layout instead. --show-engine keeps the engine tab visible (no park).
# --no-layout is accepted and does nothing (there is no octopilot layout any more).
# --close-launcher closes this terminal's own pane at the end (the tab goes with
# its last pane), for the key or the palette (programs.json). From a worktree it
# needs OCTOPILOT_STATE_DIR (see herdr/README.md).
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
# The names of the mod panes: each mod finds its own in panes() by these (see ownPane in the mods).
DASHBOARD_PANE="octopilot-dashboard"
PROMPTER_PANE="octopilot-prompter"
SIDE_PANE="octopilot-side"
KITCHEN_PANE="octopilot-kitchen"
KITCHEN_PX=300                         # the kitchen's height under the chat
MAIN_TAB="OCTOPILOT"
ENGINE_TAB="engine"
CODE_TAB="Octopilot (code changes)"
CODE_CWD="$(cd "$DIR/../.." && pwd -P)"   # the checkout this octopilot lives in

TERMINALS=0
CLOSE_LAUNCHER=0
SHOW_ENGINE=0
for arg in "$@"; do
  case "$arg" in
    --terminals) TERMINALS=1 ;;
    --close-launcher) CLOSE_LAUNCHER=1 ;;
    --no-layout) ;;
    --show-engine) SHOW_ENGINE=1 ;;
    -h|--help) echo "usage: open-gui.sh [--terminals] [--show-engine] [--no-layout] [--close-launcher]"; exit 0 ;;
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
# The code tab's side panel: the code agent it shows, and its title.
SIDE_PROPS="$(jq -nc --argjson mod "$MOD_PROPS" --arg agent "$CODE_AGENT" \
  '$mod + {agent: $agent, title: "Code changes"}')"
# The kitchen's props: the mod's dir and state dir, and the name of its pane.
KITCHEN_PROPS="$(jq -nc --argjson mod "$MOD_PROPS" --arg name "$KITCHEN_PANE" \
  '$mod + {pane_name: $name}')"

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

# A JSON argv run in the user's interactive shell (the gateway env of
# ~/.zshrc.local). pane.split runs its argv as given; exec ends the terminal
# with its program.
shell_argv() {
  local sh="${SHELL:-}"
  if [ -z "$sh" ]; then sh=$(getent passwd "$(id -un)" | cut -d: -f7); fi
  jq -nc --arg sh "$sh" --argjson argv "$1" '[$sh, "-ic", "exec \"$@\"", $sh] + $argv'
}

# A fresh session id for a claude that is started with --session-id.
new_session() {
  uuidgen | tr '[:upper:]' '[:lower:]'
}

# The --settings that put a worktree's octopilot plugin in place of the
# installed one (empty on the live checkout), for every claude started here.
SETTINGS="$(OCTOPILOT_DIR="$DIR" "$DIR/scan.sh" plugin-settings)"

# argv for a claude session: its session id (empty: none), optionally started
# with a prompt, in a folder (empty: the pane's own, `env -C` otherwise).
session_argv() {
  local args=(env)
  if [ -n "${3:-}" ]; then args+=(-C "$3"); fi
  args+=("${envs[@]}" claude)
  if [ -n "$SETTINGS" ]; then args+=(--settings "$SETTINGS"); fi
  if [ -n "${1:-}" ]; then args+=(--session-id "$1"); fi
  if [ -n "${2:-}" ]; then args+=("$2"); fi
  argv_json "${args[@]}"
}

# True when the terminal is labelled as run from this checkout. An unlabelled
# one is never ours: only labelled terminals are ever killed or reused.
is_mine() {
  local d
  d=$("$HC" get "$1" --json | jq -r '.labels["octopilot.dir"] // empty')
  [ -n "$d" ] && [ "$(realpath -m "$d")" = "$DIR" ]
}

# The address of this checkout's terminal labelled as an octopilot agent, if
# any. Pure lookup: it never kills (see reap_dead).
find_agent() {
  local t
  for t in $("$HC" ls --json --label "octopilot.agent=$1" | jq -r '.terminals[].address'); do
    if is_mine "$t"; then echo "$t"; return 0; fi
  done
}

# The orchestrator is this checkout's only; an unlabelled one is never adopted
# (it hits the "another octopilot" refusal instead).
find_orch() { find_agent "$ORCH_AGENT"; }

# Ends this checkout's terminals of an agent that are not running its program (a
# shell herdr kept after claude exited, a dead headless), so it starts again.
reap_dead() {
  local t info fg created want=claude
  if [ "$1" = "$HEADLESS_AGENT" ]; then want=uv; fi
  for t in $("$HC" ls --json --label "octopilot.agent=$1" | jq -r '.terminals[].address'); do
    is_mine "$t" || continue
    info=$("$HC" get "$t" --json)
    fg=$(jq -r '.foreground.name // empty' <<<"$info")
    if [ "$fg" = "$want" ]; then continue; fi
    # Still starting: its shell has not exec'd the program yet (created_ms, epoch ms).
    created=$(jq -r '.created_ms // 0' <<<"$info")
    case "$fg" in
      zsh|bash|sh|fish)
        if [ $(( $(date +%s%3N) - created )) -lt 30000 ]; then continue; fi ;;
    esac
    "$HC" kill "$t" >/dev/null || true
    "$HC" rm "$t" >/dev/null || true
  done
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

# True when herdr-app shows a space with this id.
space_exists() {
  "$APP" ls | jq -e --arg s "$1" '.spaces[] | select(.id == $s)' >/dev/null
}

# Labels a terminal as an agent of this checkout: its name, its dir, and for a
# claude its session id.
name_agent() {
  local labels=("octopilot.agent=$2" "octopilot.dir=$DIR")
  if [ -n "${3:-}" ]; then labels+=("octopilot.session=$3"); fi
  "$HC" label "$1" "${labels[@]}" >/dev/null
}

# Starts a terminal with argv (JSON, unwrapped) beside the orchestrator's pane,
# or in a tab of the space while it is parked (pane empty). Prints its address.
start_engine_term() {
  local space=$1 pane=$2 direction=$3 argv=$4 name=$5 created term p
  if [ -n "$pane" ]; then
    created=$(app do pane.split --direction "$direction" --pane "$pane" \
      --argv "$(shell_argv "$argv")")
  else
    created=$(app do tab.new --space "$space" --argv "$argv" --focus false)
  fi
  term=$(jq -r '.terminal' <<<"$created")
  p=$(locate "$term" | cut -f3)
  if [ -n "$p" ]; then app do pane.rename --pane "$p" --name "$name" >/dev/null; fi
  echo "$term"
}

# Names a mod pane after its role, so its copy finds its own pane in panes().
name_mod_pane() {
  app do pane.rename --pane "$1" --name "$2" >/dev/null
}

# Starts the prompter, labelled with its claude's session.
add_prompter() {
  local session term
  session=$(new_session)
  term=$(start_engine_term "$1" "$2" "$3" "$(session_argv "$session" "/octopilot:prompter")" prompter)
  name_agent "$term" "$PROMPTER_AGENT" "$session"
}

# Starts the headless dashboard: the loops that feed view.json, which the mods show.
add_headless() {
  local term
  term=$(start_engine_term "$1" "$2" down \
    "$(argv_json env "${envs[@]}" bash "$DIR/dashboard.sh" --headless)" headless)
  name_agent "$term" "$HEADLESS_AGENT"
}

# The engine tab's helpers beside the orchestrator (space, pane), those that are missing.
add_engine_agents() {
  if [ -z "$(find_agent "$HEADLESS_AGENT")" ]; then add_headless "$1" "$2"; fi
  if [ -z "$(find_agent "$PROMPTER_AGENT")" ]; then add_prompter "$1" "$2" right; fi
}

# The OCTOPILOT tab, unless the space has one: the dashboard mod, and the chat
# mod (the prompter) beside it. The chat's pane is recorded on the orchestrator
# (octopilot.chat): the kitchen splits from it on a later run.
add_main_tab() {
  local created pane chat
  if [ -n "$(tab_named "$1" "$MAIN_TAB")" ]; then return 0; fi
  created=$(app do tab.new --space "$1" --name "$MAIN_TAB" \
    --mod octopilot-dashboard --props "$MOD_PROPS" --focus false)
  pane=$(jq -r '.pane // empty' <<<"$created")
  if [ -z "$pane" ]; then
    echo "open-gui.sh: the $MAIN_TAB tab has no pane to split the chat into" >&2
    exit 1
  fi
  name_mod_pane "$pane" "$DASHBOARD_PANE"
  created=$(app do pane.split --direction right --pane "$pane" \
    --mod octopilot-chat --props "$MOD_PROPS")
  chat=$(jq -r '.pane' <<<"$created")
  name_mod_pane "$chat" "$PROMPTER_PANE"
  "$HC" label "$(find_orch)" "octopilot.chat=$chat" >/dev/null
}

# Sizes the kitchen (pane $2) to KITCHEN_PX: the divider above it (the chat's bottom
# edge, pane $1) goes down, so the kitchen is at its minimum whatever the split gave,
# then up by KITCHEN_PX. A refused first move is not fatal: the size is then the split's.
size_kitchen() {
  "$APP" do pane.resize --direction down --pane "$1" --px 10000 >/dev/null 2>&1 || true
  app do pane.resize --direction up --pane "$2" --px "$KITCHEN_PX" >/dev/null
}

# The kitchen under the chat in the OCTOPILOT tab, once. The pane this run recorded on
# the orchestrator (octopilot.kitchen) is kept while it exists (pane.rename fails on a
# pane that is gone), as the side panel's is. A tab from an earlier run has no chat
# record: the kitchen cannot be split from its chat, so it is left out with a note.
add_kitchen() {
  local orch kitchen chat created
  orch=$(find_orch)
  kitchen=$("$HC" get "$orch" --json | jq -r '.labels["octopilot.kitchen"] // empty')
  if [ -n "$kitchen" ] && "$APP" do pane.rename --pane "$kitchen" --name "$KITCHEN_PANE" >/dev/null 2>&1; then
    return 0
  fi
  chat=$("$HC" get "$orch" --json | jq -r '.labels["octopilot.chat"] // empty')
  if [ -z "$chat" ] || ! "$APP" do pane.rename --pane "$chat" --name "$PROMPTER_PANE" >/dev/null 2>&1; then
    echo "open-gui.sh: the $PROMPTER_PANE pane is not recorded (octopilot.chat), so the" \
      "$KITCHEN_PANE pane is not added; see herdr/README.md" >&2
    return 0
  fi
  created=$(app do pane.split --direction down --pane "$chat" --mod octopilot-kitchen --props "$KITCHEN_PROPS")
  kitchen=$(jq -r '.pane' <<<"$created")
  name_mod_pane "$kitchen" "$KITCHEN_PANE"
  size_kitchen "$chat" "$kitchen"
  "$HC" label "$orch" "octopilot.kitchen=$kitchen" >/dev/null
}

# The code agent's claude in a tab of its own, named CODE_TAB, in the dotfiles root.
# Prints its terminal.
start_code_tab() {
  local session created term
  session=$(new_session)
  created=$(app do tab.new --space "$1" --name "$CODE_TAB" \
    --argv "$(session_argv "$session" "" "$CODE_CWD")" --focus false)
  term=$(jq -r '.terminal' <<<"$created")
  name_agent "$term" "$CODE_AGENT" "$session"
  echo "$term"
}

# The terminals a tab holds, by id. herdr-app ls lists no mod panes.
tab_terminals() {
  "$APP" ls | jq -r --arg t "$1" '.spaces[].tabs[] | select(.id == $t) | .terminals[].terminal'
}

# Waits (up to 10 s) until a terminal shows in a tab, and prints its "space tab pane".
# herdr applies keep and park in the background, so the callers wait for them.
await_shown() {
  local i located
  for i in $(seq 40); do
    located=$(locate "$1")
    if [ -n "$located" ]; then echo "$located"; return 0; fi
    sleep 0.25
  done
  echo "open-gui.sh: $1 did not show in a tab" >&2
  return 1
}

# Waits (up to 10 s) until a terminal has no pane.
await_parked() {
  local i
  for i in $(seq 40); do
    if [ -z "$(locate "$1")" ]; then return 0; fi
    sleep 0.25
  done
  echo "open-gui.sh: $1 did not park" >&2
  return 1
}

# Moves the code agent's claude into a tab of its own. Shown in another tab, or parked,
# it is parked (its process keeps running) and kept again, which gives it a new tab of
# its space; the old tab (the chat, or a terminal tab that holds only the agent) goes,
# and the new one takes CODE_TAB's name. Prints the "space tab pane" it shows in.
show_code_tab() {
  local space=$1 code=$2 old=$3 located
  if [ -n "$(locate "$code")" ]; then
    app do terminal.park --terminal "$code" >/dev/null
    await_parked "$code" >/dev/null
  fi
  "$HC" label "$code" "herdr.space=$space" "octopilot.space=$space" >/dev/null
  app do terminal.keep --terminal "$code" >/dev/null
  located=$(await_shown "$code")
  if [ -n "$old" ] && [ "$old" != "$(cut -f2 <<<"$located")" ]; then
    app do tab.close --id "$old" >/dev/null
  fi
  app do tab.rename --id "$(cut -f2 <<<"$located")" --name "$CODE_TAB" >/dev/null
  echo "$located"
}

# The octopilot-side panel beside the agent's terminal, once. The pane this run recorded
# on the agent (a label) is kept while it exists: pane.rename fails on a pane that is gone.
add_side_panel() {
  local code=$1 pane=$2 side created
  side=$("$HC" get "$code" --json | jq -r '.labels["octopilot.side"] // empty')
  if [ -n "$side" ] && "$APP" do pane.rename --pane "$side" --name "$SIDE_PANE" >/dev/null 2>&1; then
    return 0
  fi
  created=$(app do pane.split --direction right --pane "$pane" --mod octopilot-side --props "$SIDE_PROPS")
  side=$(jq -r '.pane' <<<"$created")
  name_mod_pane "$side" "$SIDE_PANE"
  "$HC" label "$code" "octopilot.side=$side" >/dev/null
}

# The code-changes tab: the code agent's claude in its own terminal, with the side panel
# beside it. A rerun converts what an earlier one left: the chat mod tab, a terminal tab
# without the panel, or the agent parked (its claude keeps running). A terminal in the
# tab that is not the agent's is refused, never closed.
add_code_tab() {
  local space=$1 old code shown located t pane
  old=$(tab_named "$space" "$CODE_TAB")
  code=$(find_agent "$CODE_AGENT")
  if [ -n "$old" ]; then
    for t in $(tab_terminals "$old"); do
      if [ "$t" != "$code" ]; then
        echo "open-gui.sh: the $CODE_TAB tab holds $t, which is not the $CODE_AGENT agent;" \
          "close it first" >&2
        exit 1
      fi
    done
  fi
  if [ -z "$code" ]; then
    # What is left of the old tab holds no terminal: the panel or the chat only.
    if [ -n "$old" ]; then app do tab.close --id "$old" >/dev/null; fi
    code=$(start_code_tab "$space")
  else
    shown=$(locate "$code" | cut -f2)
    if [ -z "$shown" ] || [ "$shown" != "$old" ]; then
      show_code_tab "$space" "$code" "$old" >/dev/null
    fi
  fi
  located=$(locate "$code")
  pane=$(cut -f3 <<<"$located")
  if [ -z "$pane" ]; then
    echo "open-gui.sh: the $CODE_AGENT terminal ($code) has no pane to split the panel from" >&2
    exit 1
  fi
  add_side_panel "$code" "$pane"
}

# The --terminals code tab: a terminal tab with its claude in the dotfiles root,
# unless this checkout's code agent runs already (another checkout's is left alone).
add_code_terminal_tab() {
  local created
  if [ -n "$(find_agent "$CODE_AGENT")" ]; then return 0; fi
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

# The space of an engine terminal: its herdr.space label, or octopilot.space once
# park_engine parked it (parking removes herdr.space).
space_of() {
  "$HC" get "$1" --json | jq -r '.labels["herdr.space"] // .labels["octopilot.space"] // empty'
}

# This checkout's engine terminals that have no pane, as "label address" lines.
parked_engine() {
  local label t
  for label in "$ORCH_AGENT" "$PROMPTER_AGENT" "$HEADLESS_AGENT"; do
    t=$(find_agent "$label")
    if [ -n "$t" ] && [ -z "$(locate "$t")" ]; then echo "$label $t"; fi
  done
}

# Parks the engine's terminals (--show-engine keeps them shown): their panes go,
# their processes keep running, and the engine tab empties and goes away. The
# orchestrator also keeps its space in a label, for space_of. The code agent is not
# an engine terminal: it has its own tab.
park_engine() {
  local space=$1 label t
  if [ "$SHOW_ENGINE" = 1 ]; then return 0; fi
  for label in "$ORCH_AGENT" "$PROMPTER_AGENT" "$HEADLESS_AGENT"; do
    t=$(find_agent "$label")
    if [ -z "$t" ] || [ -z "$(locate "$t")" ]; then continue; fi
    if [ "$label" = "$ORCH_AGENT" ]; then
      "$HC" label "$t" "octopilot.space=$space" >/dev/null
    fi
    app do terminal.park --terminal "$t" >/dev/null
  done
}

# Ends this checkout's engine and code agents, by label: their space is gone, so
# octopilot is stopped and built again.
stop_engine() {
  local label t
  for label in "$ORCH_AGENT" "$PROMPTER_AGENT" "$HEADLESS_AGENT" "$CODE_AGENT"; do
    for t in $("$HC" ls --json --label "octopilot.agent=$label" | jq -r '.terminals[].address'); do
      if is_mine "$t"; then
        "$HC" kill "$t" >/dev/null || true
        "$HC" rm "$t" >/dev/null || true
      fi
    done
  done
}

# The space a new orchestrator starts in: the one of a terminal labelled with
# this checkout's dir (after a restart the parked engine is gone but the spaces
# are back), never a match by name. Empty: a new space.
existing_space() {
  local label t s
  for label in "$CODE_AGENT" "$ORCH_AGENT" "$PROMPTER_AGENT" "$HEADLESS_AGENT"; do
    t=$(find_agent "$label")
    if [ -z "$t" ]; then continue; fi
    s=$(space_of "$t")
    if [ -n "$s" ] && space_exists "$s"; then echo "$s"; return 0; fi
  done
}

# Runs at the end of every path that did its work: the engine parked (the GUI
# layout), then the launcher's own pane.
finish() {
  local space=$1
  if [ "$TERMINALS" = 0 ]; then park_engine "$space"; fi
  if [ "$CLOSE_LAUNCHER" = 1 ]; then close_launcher; fi
}

# Shows the space and its OCTOPILOT tab.
focus_main() {
  app do space.select --id "$1" >/dev/null
  app do tab.select --id "$(tab_named "$1" "$MAIN_TAB")" >/dev/null
}

# The space is found before the reap, which may end the terminals that prove it.
known_space=$(existing_space)
for a in "$ORCH_AGENT" "$PROMPTER_AGENT" "$HEADLESS_AGENT" "$CODE_AGENT"; do reap_dead "$a"; done
orch=$(find_orch)
if [ -z "$orch" ]; then
  other=$("$HC" ls --json --label "octopilot.agent=$ORCH_AGENT" | jq -r '.terminals[0].address // empty')
  if [ -n "$other" ]; then
    echo "open-gui.sh: the $ORCH_AGENT agent ($other) runs from another octopilot" \
      "(not $DIR). Close it, or run this from its own checkout." >&2
    exit 1
  fi
fi
if [ -n "$orch" ]; then
  located=$(locate "$orch")
  if [ -n "$located" ]; then
    IFS=$'\t' read -r space tab pane <<<"$located"
  else
    # Parked by an earlier run: no pane. Its space must still be shown, else
    # octopilot was closed with it and is stopped here.
    space=$(space_of "$orch")
    if [ -z "$space" ]; then
      echo "open-gui.sh: the $ORCH_AGENT agent ($orch) is not in a Herdr space" >&2
      exit 1
    fi
    if space_exists "$space"; then
      tab=""
      pane=""
    else
      echo "open-gui.sh: the space of the $ORCH_AGENT agent is closed; stopping" \
        "octopilot and building it again" >&2
      stop_engine
      orch=""
      known_space=""
    fi
  fi
fi

if [ -n "$orch" ]; then
  if [ "$TERMINALS" = 1 ] || [ "$SHOW_ENGINE" = 1 ]; then
    parked=$(parked_engine)
    if [ -n "$parked" ]; then
      echo "open-gui.sh: these engine terminals are parked (no pane); show each with" \
        "herdr-app do terminal.keep --terminal <address>:" >&2
      sed 's/^/  /' <<<"$parked" >&2
      exit 1
    fi
  fi
  if [ "$TERMINALS" = 1 ]; then
    if [ -n "$(tab_named "$space" "$MAIN_TAB")" ] && [ "$(tab_named "$space" "$MAIN_TAB")" != "$tab" ]; then
      echo "open-gui.sh: the space already has an $MAIN_TAB tab (the GUI layout);" \
        "run without --terminals" >&2
      exit 1
    fi
    app do tab.rename --id "$tab" --name "$MAIN_TAB" >/dev/null
    if [ -z "$(find_agent "$PROMPTER_AGENT")" ]; then add_prompter "$space" "$pane" down; fi
    add_code_terminal_tab "$space"
    app do agent.focus --terminal "$orch" >/dev/null
  else
    old=$(legacy_dashboard "$space")
    if [ -n "$old" ]; then
      echo "open-gui.sh: terminal $old is the curses dashboard of the TUI layout;" \
        "close its pane first (two dashboards would run), or use --terminals" >&2
      exit 1
    fi
    if [ -n "$pane" ]; then app do tab.rename --id "$tab" --name "$ENGINE_TAB" >/dev/null; fi
    add_engine_agents "$space" "$pane"
    add_main_tab "$space"
    add_kitchen
    add_code_tab "$space"
    focus_main "$space"
  fi
  finish "$space"
  exit 0
fi

# No orchestrator running: it starts in this checkout's space, or in a new one,
# started ticking straight away.
session=$(new_session)
tab_name="$ENGINE_TAB"
if [ "$TERMINALS" = 1 ]; then tab_name="$MAIN_TAB"; fi
space="$known_space"
if [ -n "$space" ]; then
  if [ "$TERMINALS" = 1 ] && [ -n "$(tab_named "$space" "$MAIN_TAB")" ]; then
    echo "open-gui.sh: the space already has an $MAIN_TAB tab (the GUI layout);" \
      "run without --terminals" >&2
    exit 1
  fi
  created=$(app do tab.new --space "$space" --name "$tab_name" \
    --argv "$(session_argv "$session" "/octopilot:messenger")" --focus false)
else
  created=$(app do space.new --name "$LABEL" --folder "$OCTOPILOT_ORCH_CWD" \
    --tab "$tab_name" --argv "$(session_argv "$session" "/octopilot:messenger")" --focus false)
  space=$(jq -r '.space' <<<"$created")
fi
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
    --argv "$(shell_argv "$(argv_json env "${envs[@]}" bash "$DIR/dashboard.sh")")")
  app do pane.rename --pane "$(jq -r '.pane' <<<"$dash")" --name dashboard >/dev/null
  add_prompter "$space" "$root" down
  add_code_terminal_tab "$space"
  app do agent.focus --terminal "$orch" >/dev/null
else
  add_engine_agents "$space" "$root"
  add_main_tab "$space"
  add_kitchen
  add_code_tab "$space"
  focus_main "$space"
fi
finish "$space"
