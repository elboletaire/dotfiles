# Fixtures

`view.json` is a sample of the `view.json` the headless backend writes (see
`../CONTRACT.md`). The mod reads a fixture when given `props.fixture`, which
is how a throwaway tab shows it without the real state.

For layout tests the mod's fixture is copied outside the worktree, to
`~/drafts/octopilot-dash-fixture/view.json` (the same content plus 30 running
rows). Reading the fixture from the worktree path returned nothing in the
herdr app, so test with a copy outside the repo.
