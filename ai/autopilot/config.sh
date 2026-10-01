# PR Autopilot configuration. Sourced by scan.sh and the pr-autopilot skill.

# Repos where every open PR is a candidate regardless of author (canonical
# slugs -- resolved via `gh repo view`, NOT directory names. vocdoni/ui-scaffold
# redirects to vocdoni/vocdoni-app; using the old slug silently drops the repo).
HOME_REPOS="vocdoni/vocdoni-app vocdoni/vocdoni.io vocdoni/vocdoni-integrator-sdk"

# Where your local clones live. Autopilot treats every git repo directly under
# these folders (a real `.git` dir; worktrees are skipped) as "cloned", and
# resolves its GitHub slug and base branch with `gh repo view`. Space-separated.
CLONE_ROOTS="$HOME/src/vocdoni $HOME/src/davinci"

# Two clones can resolve to the same slug (ui-scaffold and vocdoni-app are both
# vocdoni/vocdoni-app). The path listed here wins; otherwise the first in
# alphabetical order does. Worktree sessions are matched to a repo by this path,
# so pick the clone your existing worktrees hang off.
CLONE_PREFER="$HOME/src/vocdoni/ui-scaffold"

# Every session autopilot spawns goes into <AUTOPILOT_GROUP>/<repo-name>, where
# repo-name is the slug's repo part (vocdoni/vocdoni-sdk -> vocdoni-sdk). A new
# repo gets its own subgroup on first spawn; nothing to configure.
AUTOPILOT_GROUP="Autopilot"

# Orgs whose issues are candidates when assigned to you. Add "elboletaire" here
# if you want issue candidates from your personal repos (manga-downloader etc).
ISSUE_ORGS="vocdoni"

# Slash command for review. `/review` is a verified alias of `/code-review`
# (aliases:["review"] in the 2.1.267 bundle); both work.
REVIEW_CMD="/review"
REVIEW_LEVEL="high"          # review-fix loop on your own PRs: recall, fixes are tested locally
# Public reviews of someone else's PR: high recall for pass 1 (candidates, never
# posted), then a fresh subagent verifies each one and only CONFIRMED findings
# are posted. Posting pass 1 directly put unverified candidates on GitHub.
REVIEW_LEVEL_COMMENT="high"

# Model pinned per spawned session, by the prompt that CREATES it. Written
# explicitly onto the `claude` command line, so a worker never inherits the
# orchestrator's model -- running autopilot on haiku still gets you opus
# workers. Later prompts (rebase, address-feedback) land in an existing
# session and run on whatever it was spawned with; the model cannot be changed
# without restarting the session, which would destroy its conversation.
#
# Accepts an alias (opus/sonnet/haiku) or a full model id. Empty means "do not
# pass --model", i.e. inherit the global default. The bare aliases give the
# standard context window; append [1m] for 1M context (quoted, since [..] is a
# glob). Standard-context workers were auto-compacting mid review loop.
MODEL_WORK='opus[1m]'              # issue -> implementation, ambiguous spec
MODEL_INVESTIGATE='opus[1m]'       # open-ended question
MODEL_REVIEW_FIX='opus[1m]'        # own/assigned PR: rebase, 3 review rounds, CI waits -- the longest-lived session
MODEL_REVIEW_COMMENT='opus[1m]'    # public review of someone else's PR
MODEL_COLD_REVIEW=opus       # the Agent-tool review pass inside the loop

# Max concurrent work/review sessions autopilot will run. Candidates above the
# cap queue as PROPOSE rows instead of spawning.
MAX_ACTIVE=6

# How many self-review rounds autopilot runs on one PR before it stops and
# hands back. Each round is one review-fix pass; the counter increments on
# mark-reviewed, resets when a human leaves a GitHub review (mark-feedback) or
# on `scan.sh reset-rounds <key>`. At the cap the item prints CAPPED and
# autopilot takes no further action on it.
MAX_REVIEW_ROUNDS=3

# An agent-driven item that has neither pushed nor called `heartbeat` for this
# long is reported STALLED. It is a backstop for an agent that died, whose
# background CI wait never returned, or whose final report never arrived --
# silence must not read as work in progress.
AGENT_STALL_MIN=35

# Follow-up reviews of someone else's PR run when the author re-requests the
# review. A push after our review with no re-request is flagged PUSHED once the
# branch has been quiet this many hours -- flagged for the user, never reviewed.
RE_REVIEW_QUIET_HOURS=4

# A session with no PR and no activity for this long is reported STALE.
STALE_HOURS=48

# Issues untouched for longer than this are not proposed. Without it, every
# ancient org issue ever assigned to you shows up as a candidate.
ISSUE_MAX_AGE_DAYS=120

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pr-autopilot"
STATE_FILE="$STATE_DIR/state.json"
PROMPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/prompts"
