# Fixtures

`view.json` is a real capture from the headless backend (see `../CONTRACT.md`);
`view.board.json` is a hand-made board with fuller columns for layout tests. The mod reads a fixture when given `props.fixture`, which
is how a throwaway tab shows it without the real state.

For layout tests the mod's fixture is copied outside the worktree, to
`~/drafts/octopilot-dash-fixture/view.json` (the same content plus 30 running
rows). Reading the fixture from the worktree path returned nothing in the
herdr app, so test with a copy outside the repo.
