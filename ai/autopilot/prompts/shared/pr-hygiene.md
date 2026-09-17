## Publishing rules (non-negotiable)

Anything you write to GitHub -- PR titles and bodies, issue comments, review
bodies, commit messages -- is public and permanent.

Describe the change and its effect on the repository. Never describe the
environment you ran in: no absolute paths, no home directory, no dotfile
layout, no session/terminal/agent tooling, no "on my machine". If a local
detail feels necessary to explain a finding, it isn't -- restate it as a
property of the repo ("the plugin cache is keyed by version" rather than
"on my machine the cache is at ~/.claude/plugins/cache/...").

Never paste tokens, keys, or environment variables.

A PreToolUse guard blocks publishing commands that violate this. If it fires,
rewrite the body -- do not try to work around it.

Sign GitHub comments and reviews per the global CLAUDE.md rule, using your actual model name (never a hardcoded one).
Never add a Co-authored-by trailer to commits.
