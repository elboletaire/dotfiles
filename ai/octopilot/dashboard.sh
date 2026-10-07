#!/usr/bin/env bash
# Live dashboard for Octopilot: load config.sh, hand off to dashboard.py
# (run by uv, which provides `rich` without touching the system Python).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
set -a
# shellcheck source=config.sh
source "$DIR/config.sh"
set +a
exec uv run --quiet --script "$DIR/dashboard.py" "$@"
