#!/usr/bin/env bash
# Build the Taller workspace -- the board as its only pane, in ~ -- or focus
# it if it already exists. Run by the plugin's `open` action.
# TALLER_DRY_RUN=1 prints what it would run instead.
set -euo pipefail
H="${HERDR_BIN_PATH:-herdr}"
LABEL="Taller"

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

# A config given to this script goes to the board too.
board_env=()
if [ -n "${TALLER_CONFIG:-}" ]; then board_env+=(--env "TALLER_CONFIG=$TALLER_CONFIG"); fi

# The workspace comes with a shell pane: the board opens beside it as a
# plugin pane, then the shell goes.
if [ "${TALLER_DRY_RUN:-}" = 1 ]; then
  run "$H" workspace create --label "$LABEL" --cwd "$HOME" --focus
  run "$H" plugin pane open --plugin elboletaire.taller --entrypoint board \
    --placement split --target-pane "<pane>" --direction right --focus \
    "${board_env[@]}"
  run "$H" pane close "<pane>"
  exit 0
fi
created=$("$H" workspace create --label "$LABEL" --cwd "$HOME" --focus)
root=$(jq -r '.result.root_pane.pane_id' <<<"$created")
"$H" plugin pane open --plugin elboletaire.taller --entrypoint board \
  --placement split --target-pane "$root" --direction right --focus \
  "${board_env[@]}" >/dev/null
"$H" pane close "$root" >/dev/null
