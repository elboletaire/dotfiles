#!/usr/bin/env bash
# Arxiu, the genealogy research dashboard wired to the tree's agents. Hands
# off to board.py, run by uv, which provides `rich` without touching the
# system Python. Config: config.toml next to this script, or $ARXIU_CONFIG.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --quiet --script "$DIR/board.py" "$@"
