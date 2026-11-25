#!/usr/bin/env bash
# The GUI twin of open.sh: the Octopilot space in herdr-app, with three tabs:
#   OCTOPILOT: the octopilot-dashboard and octopilot-chat mods
#   engine: the orchestrator, the prompter, the headless dashboard and the code
#     agent (a claude for changing octopilot itself), as hc terminals; parked
#     after building (no pane, still running), so the tab goes away
#   Octopilot (code changes): the octopilot-chat mod over the code agent
# Each claude is labelled octopilot.agent=<name> and octopilot.session=<uuid>
# (its transcript, read by scan.py speech and chat). --terminals builds the
# TUI-style layout instead. --show-engine keeps the engine tab visible (no park).
# After building it switches to the `octopilot` layout (the kitchen corner) when
# herdr-app/install.sh made one and the shown layout is `main` (a layout you
# picked stays); --no-layout skips that. --close-launcher closes this terminal's
# own pane at the end (the tab goes with its last pane), for the key or the
# palette (programs.json). From a worktree it needs OCTOPILOT_STATE_DIR (see
# herdr/README.md).
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
# The roles of the mod panes. Each pane is named role-<hash of the checkout's dir> (pane_name),
# and its mod finds it in panes() by the name given in props.pane_name.
DASHBOARD_PANE="octopilot-dashboard"
PROMPTER_PANE="octopilot-prompter"
MAIN_TAB="OCTOPILOT"
ENGINE_TAB="engine"
CODE_TAB="Octopilot (code changes)"
CODE_CWD="$(cd "$DIR/../.." && pwd -P)"   # the checkout this octopilot lives in

TERMINALS=0
CLOSE_LAUNCHER=0
LAYOUT=1
SHOW_ENGINE=0
for arg in "$@"; do
  case "$arg" in
    --terminals) TERMINALS=1 ;;
    --close-launcher) CLOSE_LAUNCHER=1 ;;
    --no-layout) LAYOUT=0 ;;
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

# The name of a mod pane: its role and a short hash of this checkout's dir, so two
# checkouts in one window each find their own.
DIR_HASH=$(printf '%s' "$DIR" | sha1sum | cut -c1-8)
pane_name() {
  printf '%s-%s' "$1" "$DIR_HASH"
}

# The props of the mods, which read their octopilot from them.
MOD_PROPS="$(jq -nc --arg dir "$DIR" --arg state "$STATE_DIR" '{dir: $dir, state_dir: $state}')"
DASH_PROPS="$(jq -nc --argjson mod "$MOD_PROPS" --arg name "$(pane_name "$DASHBOARD_PANE")" \
  '$mod + {pane_name: $name}')"
PROMPTER_PROPS="$(jq -nc --argjson mod "$MOD_PROPS" --arg name "$(pane_name "$PROMPTER_PANE")" \
  '$mod + {pane_name: $name}')"
# The code tab's chat mod: the code agent it talks to, and its copy.
CODE_PROPS="$(jq -nc --argjson mod "$MOD_PROPS" --arg agent "$CODE_AGENT" --arg name "$(pane_name "$CODE_AGENT")" \
  '$mod + {agent: $agent, pane_name: $name, title: "Code changes", subject: "the code changes agent",
    chips: ["status of the last change", "what did you change?", "run the checks"]}')"

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

# Names a mod pane (its id, then its name). Best effort: a pane that cannot be named
# is warned about, and its copy falls back to the only pane of its mod.
name_mod_pane() {
  local out
  if [ -z "$1" ]; then
    echo "open-gui.sh: no pane to name $2" >&2
    return 0
  fi
  if ! out=$("$APP" do pane.rename --pane "$1" --name "$2" 2>&1); then
    echo "open-gui.sh: could not name pane $1 $2: $out" >&2
  fi
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
# mod (the prompter) beside it. A rerun keeps the panes the tab has: herdr-app ls
# lists no mod panes, so their names are not set again here.
add_main_tab() {
  local created pane
  if [ -n "$(tab_named "$1" "$MAIN_TAB")" ]; then return 0; fi
  created=$(app do tab.new --space "$1" --name "$MAIN_TAB" \
    --mod octopilot-dashboard --props "$DASH_PROPS" --focus false)
  pane=$(jq -r '.pane // empty' <<<"$created")
  if [ -z "$pane" ]; then
    echo "open-gui.sh: the $MAIN_TAB tab has no pane to split the chat into" >&2
    exit 1
  fi
  name_mod_pane "$pane" "$(pane_name "$DASHBOARD_PANE")"
  created=$(app do pane.split --direction right --pane "$pane" \
    --mod octopilot-chat --props "$PROMPTER_PROPS")
  name_mod_pane "$(jq -r '.pane // empty' <<<"$created")" "$(pane_name "$PROMPTER_PANE")"
}

# The code agent, an engine terminal in the cwd of the dotfiles root: beside the
# orchestrator's pane, or in a tab of the space while it is parked.
start_code_agent() {
  local session term
  session=$(new_session)
  term=$(start_engine_term "$1" "$2" right "$(session_argv "$session" "" "$CODE_CWD")" code)
  name_agent "$term" "$CODE_AGENT" "$session"
  echo "$term"
}

# The code-changes tab: the chat mod over this checkout's code agent, started when
# missing. An old-style terminal tab of that name gives its agent up (parked, not killed).
add_code_tab() {
  local space=$1 pane=$2 code tab created
  code=$(find_agent "$CODE_AGENT")
  if [ -z "$code" ]; then code=$(start_code_agent "$space" "$pane"); fi
  tab=$(locate "$code" | cut -f2)
  if [ -n "$tab" ] && [ "$tab" = "$(tab_named "$space" "$CODE_TAB")" ]; then
    "$HC" label "$code" "octopilot.space=$space" >/dev/null
    app do terminal.park --terminal "$code" >/dev/null
  fi
  if ! code_mod_tab "$space"; then
    created=$(app do tab.new --space "$space" --name "$CODE_TAB" --mod octopilot-chat \
      --props "$CODE_PROPS" --focus false)
    name_mod_pane "$(jq -r '.pane // empty' <<<"$created")" "$(pane_name "$CODE_AGENT")"
  fi
}

# True when the space has a code-changes tab whose only pane is a mod.
code_mod_tab() {
  "$APP" ls | jq -e --arg s "$1" --arg n "$CODE_TAB" \
    '.spaces[] | select(.id == $s) | .tabs[] | select(.name == $n and (.terminals | length == 0))' \
    >/dev/null
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
  for label in "$ORCH_AGENT" "$PROMPTER_AGENT" "$HEADLESS_AGENT" "$CODE_AGENT"; do
    t=$(find_agent "$label")
    if [ -n "$t" ] && [ -z "$(locate "$t")" ]; then echo "$label $t"; fi
  done
}

# Parks the engine's terminals (--show-engine keeps them shown): their panes go,
# their processes keep running, and the engine tab empties and goes away. The
# orchestrator and the code agent also keep their space in a label, for space_of.
park_engine() {
  local space=$1 label t
  if [ "$SHOW_ENGINE" = 1 ]; then return 0; fi
  for label in "$ORCH_AGENT" "$PROMPTER_AGENT" "$HEADLESS_AGENT" "$CODE_AGENT"; do
    t=$(find_agent "$label")
    if [ -z "$t" ] || [ -z "$(locate "$t")" ]; then continue; fi
    if [ "$label" = "$ORCH_AGENT" ] || [ "$label" = "$CODE_AGENT" ]; then
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
# layout), the octopilot layout (the kitchen corner), then the launcher's own pane.
finish() {
  local space=$1
  if [ "$TERMINALS" = 0 ]; then park_engine "$space"; fi
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
    add_code_tab "$space" "$pane"
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
  add_code_tab "$space" "$root"
  focus_main "$space"
fi
finish "$space"
