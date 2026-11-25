# Fixtures

The fixtures are synthetic, with no real repos, titles or paths: the repos are
`acme/*` and `user/*`, the titles are made up, and the worktrees sit under
`/home/user/src`. `view.json` has the shape the headless backend writes (see
`../CONTRACT.md`) and covers every field of it: every column, every ball state,
a shelf, a focused ball, the tones, a pick tree of several repos, every note
kind and the activity. `view.board.json` is a board with fuller columns for
layout tests. `chat-*.json` are the `scan.sh chat --json` answers (idle,
working, blocked). The mod reads a fixture when given `props.fixture`, which is
how a throwaway tab shows it without the real state.

For layout tests the mod's fixture is copied outside the worktree, to
`~/drafts/octopilot-dash-fixture/view.json` (the same content plus 30 running
rows). Reading the fixture from the worktree path returned nothing in the
herdr app, so test with a copy outside the repo.
