#!/usr/bin/env bash
# Taller, the board of every project the user works on and its agents. Hands
# off to board.py, run by uv, which provides `rich` without touching the
# system Python. Config: config.toml next to this script, or $TALLER_CONFIG.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --quiet --script "$DIR/board.py" "$@"
