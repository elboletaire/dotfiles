#!/usr/bin/env bash
# Build the Taller workspace -- the orchestrator on the left (a claude named
# [taller].orchestrator_agent, in the first of [taller].roots, running
# /taller:orchestrator) and the
# board as a column on the right -- or focus it if it already exists. Run by
# the plugin's `open` action.
#
# The orchestrator running anywhere already: focused, never started twice.
# A claude conversation held in its folder before is continued (it already
# knows its role); with none, a new one is given /taller:orchestrator.
# The chat ends up focused. TALLER_DRY_RUN=1 prints what it would run
# instead; TALLER_LABEL / TALLER_ORCH build a second one under another label
# and agent name (to try changes without touching yours).
set -euo pipefail
H="${HERDR_BIN_PATH:-herdr}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="${TALLER_LABEL:-Taller}"
TAB="TALLER"           # the workspace's tab
ORCH_TITLE="minion king"   # the orchestrator's pane (its agent keeps its name)
BOARD_SHARE=0.4        # of the width, for the board's column

run() {
  if [ "${TALLER_DRY_RUN:-}" = 1 ]; then
    echo "dry-run: $*" >&2
  else
    "$@"
  fi
}

ws=$("$H" workspace list | jq -r --arg l "$LABEL" \
  '.result.workspaces[] | select(.label == $l) | .workspace_id' | head -n1)
if [ -n "$ws" ]; then
  run "$H" workspace focus "$ws" >/dev/null
  exit 0
fi

# Orchestrator name, its folder (the first root: where the projects are)
# and extra claude args (flags like --model haiku: no spaces inside one),
# one per line.
mapfile -t conf < <(python3 -c 'import sys, tomllib, os
try:
    cfg = tomllib.load(open(sys.argv[1], "rb")).get("taller", {})
except Exception:
    cfg = {}
print(cfg.get("orchestrator_agent", "taller"))
print(os.path.expanduser((cfg.get("roots") or ["~"])[0]))
print(" ".join(cfg.get("agent_args", [])))' "${TALLER_CONFIG:-$DIR/config.toml}")
orch="${TALLER_ORCH:-${conf[0]}}"
cwd="${conf[1]}"
[ -d "$cwd" ] || cwd="$HOME"
read -r -a args <<<"${conf[2]:-}"
if "$H" agent get "$orch" >/dev/null 2>&1; then
  run "$H" agent focus "$orch" >/dev/null
  exit 0
fi

# A config given to this script goes to the board too.
board_env=(--env TALLER_LAYOUT=column)
if [ -n "${TALLER_CONFIG:-}" ]; then board_env+=(--env "TALLER_CONFIG=$TALLER_CONFIG"); fi

# The newest claude conversation in its folder, if any, goes on.
held=$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import taller
print("1" if any(t[2] == "claude" for t in taller.transcripts([sys.argv[2]])) else "")' \
  "$DIR" "$cwd")
[ -n "$held" ] && args+=(--continue)
start=("$H" agent start "$orch" --kind claude --pane "<pane>" --timeout 60000)
[ "${#args[@]}" -gt 0 ] && start+=(-- "${args[@]}")
# The workspace's first pane is the orchestrator's; the board opens beside it
# as a plugin pane, and the split (50/50 when made) moves right until the
# board has BOARD_SHARE of the width.
shift_by=$(awk -v s="$BOARD_SHARE" 'BEGIN { print 0.5 - s }')
if [ "${TALLER_DRY_RUN:-}" = 1 ]; then
  run "$H" workspace create --label "$LABEL" --cwd "$cwd" --focus
  run "$H" tab rename "<tab>" "$TAB"
  run "$H" pane rename "<pane>" "$ORCH_TITLE"
  run "${start[@]}"
  [ -n "$held" ] || run "$H" agent prompt "$orch" "/taller:orchestrator"
  run "$H" plugin pane open --plugin elboletaire.taller --entrypoint board \
    --placement split --target-pane "<pane>" --direction right --no-focus \
    "${board_env[@]}"
  run "$H" pane rename "<board>" --clear
  run "$H" pane resize --pane "<board>" --direction right --amount "$shift_by"
  run "$H" agent focus "$orch"
  exit 0
fi
created=$("$H" workspace create --label "$LABEL" --cwd "$cwd" --focus)
root=$(jq -r '.result.root_pane.pane_id' <<<"$created")
"$H" tab rename "$(jq -r '.result.tab.tab_id' <<<"$created")" "$TAB" >/dev/null
"$H" pane rename "$root" "$ORCH_TITLE" >/dev/null
opened=$("$H" plugin pane open --plugin elboletaire.taller --entrypoint board \
  --placement split --target-pane "$root" --direction right --no-focus \
  "${board_env[@]}")
board=$(jq -r '.result.plugin_pane.pane.pane_id' <<<"$opened")
# No "Taller" on the board's frame: its own panels are titled.
"$H" pane rename "$board" --clear >/dev/null
"$H" pane resize --pane "$board" --direction right --amount "$shift_by" >/dev/null

for i in "${!start[@]}"; do [ "${start[$i]}" = "<pane>" ] && start[$i]="$root"; done
if ! out=$("${start[@]}" 2>&1); then
  # Claude's "trust this folder?" for its folder is the only dialog answered
  # here; anything else stays on screen for the user.
  if grep -q agent_not_ready <<<"$out"; then
    python3 "$DIR/taller.py" --accept-trust "$orch" "$cwd" "$cwd" || true
  fi
fi
# A new conversation in a brand-new pane: nobody is typing in it yet.
if [ -z "$held" ]; then
  "$H" agent prompt "$orch" "/taller:orchestrator" >/dev/null || true
fi
"$H" agent focus "$orch" >/dev/null || true
