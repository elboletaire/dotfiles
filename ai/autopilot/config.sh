# PR Autopilot configuration. Sourced by scan.sh and the pr-autopilot skill.

# Repos where every open PR is a candidate regardless of author (canonical
# slugs -- resolved via `gh repo view`, NOT directory names. vocdoni/ui-scaffold
# redirects to vocdoni/vocdoni-app; using the old slug silently drops the repo).
HOME_REPOS="vocdoni/vocdoni-app vocdoni/vocdoni.io vocdoni/vocdoni-integrator-sdk"

# Orgs whose issues are candidates when assigned to you. Add "elboletaire" here
# if you want issue candidates from your personal repos (manga-downloader etc).
ISSUE_ORGS="vocdoni"

# Slash command for review. `/review` is a verified alias of `/code-review`
# (aliases:["review"] in the 2.1.267 bundle); both work.
REVIEW_CMD="/review"
REVIEW_LEVEL="high"

# Max concurrent work/review sessions autopilot will run. Candidates above the
# cap queue as PROPOSE rows instead of spawning.
MAX_ACTIVE=6

# A session with no PR and no activity for this long is reported STALE.
STALE_HOURS=48

# Issues untouched for longer than this are not proposed. Without it, every
# ancient org issue ever assigned to you shows up as a candidate.
ISSUE_MAX_AGE_DAYS=120

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pr-autopilot"
STATE_FILE="$STATE_DIR/state.json"
PROMPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/prompts"
