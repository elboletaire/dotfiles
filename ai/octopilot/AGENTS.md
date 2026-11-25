# Octopilot (code changes)

You are changing Octopilot, the code in this directory. The repo-wide guide is
`../../AGENTS.md`: read it for anything outside octopilot (install, layout,
conventions). Changes elsewhere in the dotfiles are fine too, under the same rules.

## What it is

Octopilot drives Claude worktree sessions from GitHub issues and PRs across the
repos in `HOME_REPOS` and `CLONE_ROOTS`. An orchestrator (the messenger skill,
`/octopilot:messenger`) ticks: it reads a table built from GitHub (PR state, CI)
and from the herdr agents, proposes work under "Pick next", and on the user's
`go N` spawns a worker. A worker is a claude in its own git worktree and herdr
workspace, named `ap-<repo>-<number>`. It implements an issue or fixes a PR,
then the review-fix loop runs. When a PR merges, the orchestrator cleans up.

The user watches the dashboard (TUI or GUI) and talks to a prompter chat, which
queues commands for the orchestrator. Nothing is typed into the orchestrator
directly. The Octopilot workspace has two tabs: OCTOPILOT (orchestrator, prompter,
dashboard) and "Octopilot (code changes)", a claude started in the dotfiles for
changing this code (see `herdr/README.md`).

The GUI is native mods over the same Python backend. The decisions stay in
`scan.py` and `dashboard.py`; the mods only render `view.json` and send actions
(`dashboard.sh --action`). `herdr-app/CONTRACT.md` is that contract: the
`view.json` shape, the actions and the remote-space rules.

## Main pieces

- `scan.py`: the state engine. Scans GitHub and agent state, keeps `state.json`
  and `events.jsonl`, and holds the subcommands (`speech`, `chat`, `chat-send`,
  `plugin-settings`, ...).
- `scan.sh`: wrapper. Sources `config.sh`, exports it, then runs `scan.py`.
  `scan.sh doorbell` is the orchestrator's wake-up line.
- `dashboard.py`, `dashboard.sh`: the TUI (default), `--once` (one frame),
  `--headless` (the loops, writing `view.json`) and `--action <id>`. Run by `uv`.
- `config.sh`: repos, clone roots, models, limits. Each value can be overridden
  by an environment variable.
- `prompts/`: the worker and loop prompts (`work.md`, `review-fix.md`, `rebase.md`,
  `investigate.md`, ...), with shared fragments in `prompts/shared/`.
- `plugin/`: the Claude plugin, loaded through `CLAUDE_CODE_PLUGIN_DIRS`. Skills
  `messenger` (the orchestrator loop) and `prompter` (the user's chat), and
  `hooks/` (the takoyaki kitchen feed and scene, in TS/TSX).
- `herdr/`: the herdr TUI plugin `elboletaire.octopilot` (`open.sh`, `open-gui.sh`,
  `herdr-plugin.toml`, `README.md`).
- `herdr-app/`: the GUI mods (`mods/octopilot-{dashboard,kitchen,chat,launcher}`),
  `install.sh` (links the mods and the `programs.json` entry) and `CONTRACT.md`.

## Testing safely

- **Never test against the live state.** `~/.local/state/octopilot` is the
  running octopilot. Set `OCTOPILOT_STATE_DIR` to a scratch directory, and narrow
  the scan with `HOME_REPOS`, `ISSUE_ORGS` and `CLONE_ROOTS`. Do not start the
  orchestrator or spawn workers on the live checkout to try a change.
- **GUI test space**: `open-gui.sh` refuses without `OCTOPILOT_STATE_DIR`. Run it
  from your worktree, then close the test space with
  `herdr-app do space.close --id <space> --confirmed true`. The
  `herdr/README.md` has the full recipe.
- **Mods**: `node --test test/*.mjs` in the mod's directory. Check a mod's layout
  with `herdr-app check` on a copy outside the repo (for example under `/tmp`);
  fixtures are read from there, not from the worktree.
- **TUI changes**: capture `dashboard.sh --once` output with a fixed scratch state
  before and after the change, and diff them. A change that is not meant to alter
  the frame must give byte-identical output.
- **Plugin**: `plugin/tests/kitchen.test.tsx` covers the kitchen's feed and scene.

Keep the changes within the request. Update `herdr/README.md` or
`herdr-app/CONTRACT.md` when behaviour they describe changes.
