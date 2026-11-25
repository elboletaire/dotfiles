#!/usr/bin/env bash
# Live dashboard for Octopilot: load config.sh, hand off to dashboard.py
# (run by uv, which provides `rich` without touching the system Python).
# Modes: the TUI (default), --once (one frame), --headless (the loops, with the
# view in view.json), --action <id> [key] [--arg k=v] (one action, JSON out).
set -euo pipefail
# A herdr server started by a remote client has a bare PATH; uv lives here.
PATH="$HOME/.local/bin:$PATH"
# It has no desktop session either, so `o` (gh --web) cannot reach a browser:
# take the missing display variables from the systemd user session.
if [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v systemctl >/dev/null; then
  while IFS='=' read -r k v; do
    # xdg-open's KDE path needs KDE_SESSION_VERSION too, or it tries kfmclient.
    case $k in DISPLAY|WAYLAND_DISPLAY|XAUTHORITY|XDG_*DESKTOP|XDG_SESSION_TYPE|DESKTOP_SESSION|KDE_*)
      export "$k=$v" ;;
    esac
  done < <(systemctl --user show-environment 2>/dev/null)
fi
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
set -a
# shellcheck source=config.sh
source "$DIR/config.sh"
set +a
exec uv run --quiet --script "$DIR/dashboard.py" "$@"
