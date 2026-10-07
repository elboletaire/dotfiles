#!/usr/bin/env bash
# Build the Arxiu workspace -- the board on top, the orchestrator below it
# (50/50), both in the family tree's folder -- or focus it if it
# already exists. Run by the plugin's `open` action.
#
# The orchestrator is a claude agent named [arbre].orchestrator_agent, with
# ARXIU_ROLE=orchestrator in its pane's environment (the librarian mod, Tecla,
# reads it: always on screen below the board). Running anywhere already:
# focused, never started twice. The board ends up focused; prefix+j / prefix+k
# move between the two. ARXIU_DRY_RUN=1 prints what it would run instead.
set -euo pipefail
H="${HERDR_BIN_PATH:-herdr}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="Arxiu"   # agents.py's ARXIU_LABEL
BOARD_SHARE=0.5 # of the height, for the board; Tecla needs ~12 rows below

run() {
  if [ "${ARXIU_DRY_RUN:-}" = 1 ]; then
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

# tree, orchestrator name and extra claude args, one per line (args NUL-free
# and space-free: they are flags like --model haiku).
mapfile -t conf < <(python3 -c 'import sys, tomllib, os
try:
    cfg = tomllib.load(open(sys.argv[1], "rb")).get("arbre", {})
except Exception:
    cfg = {}
print(os.path.expanduser(cfg.get("path", "~")))
print(cfg.get("orchestrator_agent", "arbre"))
print(" ".join(cfg.get("agent_args", [])))' "${ARXIU_CONFIG:-$DIR/config.toml}")
tree="${conf[0]}"
orch="${conf[1]}"
read -r -a args <<<"${conf[2]:-}"
[ -d "$tree" ] || tree="$HOME"

if [ -n "$orch" ] && "$H" agent get "$orch" >/dev/null 2>&1; then
  run "$H" agent focus "$orch" >/dev/null
  exit 0
fi

# The workspace's first pane is the orchestrator's; the board opens below it
# as a plugin pane, then the two swap places and the split is set to BOARD_SHARE.
if [ "${ARXIU_DRY_RUN:-}" = 1 ]; then
  root="<pane>"
  board="<board>"
  run "$H" workspace create --label "$LABEL" --cwd "$tree" \
    --env ARXIU_ROLE=orchestrator --focus
else
  created=$("$H" workspace create --label "$LABEL" --cwd "$tree" \
    --env ARXIU_ROLE=orchestrator --focus)
  root=$(jq -r '.result.root_pane.pane_id' <<<"$created")
fi

if [ -n "$orch" ]; then
  run "$H" pane rename "$root" "$orch" >/dev/null
  start=("$H" agent start "$orch" --kind claude --pane "$root" --timeout 60000)
  [ "${#args[@]}" -gt 0 ] && start+=(-- "${args[@]}")
  if [ "${ARXIU_DRY_RUN:-}" = 1 ]; then
    run "${start[@]}"
  elif ! out=$("${start[@]}" 2>&1); then
    # Claude's "trust this folder?" for the tree is the only dialog answered
    # here; anything else stays on screen for the user.
    if grep -q agent_not_ready <<<"$out"; then
      python3 "$DIR/agents.py" --accept-trust "$orch" "$tree" "$tree" || true
    fi
  fi
else
  run "$H" pane rename "$root" "arxiu" >/dev/null
fi

# A config (or queue file) given to this script goes to the board too.
board_env=()
for var in ARXIU_CONFIG ARXIU_QUEUE; do
  if [ -n "${!var:-}" ]; then board_env+=(--env "$var=${!var}"); fi
done
if [ "${ARXIU_DRY_RUN:-}" = 1 ]; then
  run "$H" plugin pane open --plugin elboletaire.arxiu --entrypoint board \
    --placement split --target-pane "$root" --direction down --focus \
    "${board_env[@]}"
else
  opened=$("$H" plugin pane open --plugin elboletaire.arxiu \
    --entrypoint board --placement split --target-pane "$root" \
    --direction down --focus "${board_env[@]}")
  board=$(jq -r '.result.plugin_pane.pane.pane_id' <<<"$opened")
fi
run "$H" pane swap --source-pane "$root" --target-pane "$board" >/dev/null
# The split starts at 50/50: move the border to BOARD_SHARE if it differs.
amount=$(python3 -c "print(round($BOARD_SHARE - 0.5, 2))")
case "$amount" in
  0|0.0|-0.0) ;;
  -*) run "$H" pane resize --pane "$board" --direction up --amount "${amount#-}" >/dev/null ;;
  *) run "$H" pane resize --pane "$board" --direction down --amount "$amount" >/dev/null ;;
esac
run "$H" pane focus --pane "$root" --direction up >/dev/null
