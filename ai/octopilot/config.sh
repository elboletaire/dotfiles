# Octopilot configuration. Sourced by scan.sh and the messenger skill.

# Repos where every open PR is a candidate regardless of author (canonical
# slugs -- resolved via `gh repo view`, NOT directory names. vocdoni/ui-scaffold
# redirects to vocdoni/vocdoni-app; using the old slug silently drops the repo).
HOME_REPOS="vocdoni/vocdoni-app vocdoni/vocdoni.io vocdoni/vocdoni-integrator-sdk"

# Where your local clones live. Octopilot treats every git repo directly under
# these folders (a real `.git` dir; worktrees are skipped) as "cloned", and
# resolves its GitHub slug and base branch with `gh repo view`. Space-separated.
CLONE_ROOTS="$HOME/src/vocdoni $HOME/src/davinci"

# Two clones can resolve to the same slug (ui-scaffold and vocdoni-app are both
# vocdoni/vocdoni-app). The path listed here wins; otherwise the first in
# alphabetical order does. Worktree sessions are matched to a repo by this path,
# so pick the clone your existing worktrees hang off.
CLONE_PREFER="$HOME/src/vocdoni/ui-scaffold"

# Orgs whose issues are candidates when assigned to you. Add "elboletaire" here
# if you want issue candidates from your personal repos (manga-downloader etc).
ISSUE_ORGS="vocdoni"

# Slash command for review. `/review` is a verified alias of `/code-review`
# (aliases:["review"] in the 2.1.267 bundle); both work.
REVIEW_CMD="/review"
REVIEW_LEVEL="xhigh"         # review-fix loop, round 1: the one full review of the whole PR
# Rounds 2+ review only the diff the loop's own fixes produced since round 1,
# so a narrow pass is cheap. A full re-review every round kept finding new
# nits in its own fixes and always burned the whole MAX_REVIEW_ROUNDS budget.
REVIEW_LEVEL_FOLLOWUP="high"
# Public reviews of someone else's PR: high recall for pass 1 (candidates, never
# posted), then a fresh subagent verifies each one and only CONFIRMED findings
# are posted. Posting pass 1 directly put unverified candidates on GitHub.
REVIEW_LEVEL_COMMENT="high"

# Model pinned per spawned session, by the prompt that CREATES it. Written
# explicitly onto the `claude` command line, so a worker never inherits the
# orchestrator's model -- running octopilot on haiku still gets you opus
# workers. Later prompts (rebase, address-feedback) land in an existing
# session and run on whatever it was spawned with; the model cannot be changed
# without restarting the session, which would destroy its conversation.
#
# A full model id, never a bare alias: an alias resolves to whatever the
# gateway maps it to, and that has started old models. Empty means "do not
# pass --model", i.e. inherit the global default. Append [1m] for 1M context
# (quoted, since [..] is a glob). Standard-context workers were
# auto-compacting mid review loop.
MODEL_WORK='claude-opus-5-5[1m]'               # issue -> implementation, ambiguous spec
MODEL_INVESTIGATE='claude-opus-5-5[1m]'        # open-ended question
MODEL_REVIEW_FIX='claude-opus-5-5[1m]'         # own/assigned PR: rebase, 3 review rounds, CI waits -- the longest-lived session
MODEL_REVIEW_COMMENT='claude-opus-5-5[1m]'     # public review of someone else's PR
MODEL_COLD_REVIEW=opus                         # the Agent-tool review pass inside the loop; that
                                               # tool takes only aliases, so settings.json pins
                                               # opus to a full id (ANTHROPIC_DEFAULT_OPUS_MODEL)

# Max concurrent work/review sessions octopilot will run. Candidates above the
# cap queue as PROPOSE rows instead of spawning.
MAX_ACTIVE=6

# Local time (HH:MM) from which the day winds down: every tick reminds you to
# close what is open rather than start anything new, and a "go" asks for
# confirmation before spawning. Empty disables it.
WIND_DOWN_AT="15:00"

# How many self-review rounds octopilot runs on one PR before it stops and
# hands back. Each round is one review-fix pass; the counter increments on
# mark-reviewed, resets when a human leaves a GitHub review (mark-feedback) or
# on `scan.sh reset-rounds <key>`. At the cap the item prints CAPPED and
# octopilot takes no further action on it.
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

# Address of the orchestrator, where agent reports and dashboard commands are
# sent: "herdr:<agent name>". Empty means
# "whichever agent last ran a scan", which the scan records itself -- leave it
# empty unless that guesses wrong.
OCTOPILOT_ORCH=""

# Folder the herdr plugin starts the orchestrator in. Claude asks once whether
# to trust it. ~/src holds the clones on every workstation; the skill itself
# is global, so it works from any folder.
OCTOPILOT_ORCH_CWD="$HOME/src"

# How often the dashboard re-reads GitHub (a read-only scan), in seconds. Agent
# state and octopilot events update instantly; only PR/CI data waits for this.
DASHBOARD_REFRESH_SECS=120

# OCTOPILOT_STATE_DIR in the environment points octopilot at another state
# (a sandbox, a second profile); unset, it is the usual XDG state dir.
STATE_DIR="${OCTOPILOT_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/octopilot}"
STATE_FILE="$STATE_DIR/state.json"
PROMPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/prompts"
