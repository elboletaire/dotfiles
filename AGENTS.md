# Dotfiles: agent guide

Personal dotfiles: shell, vim, git, terminal, and the AI tooling under `ai/`.
Coding agents working in this repo read this file. Octopilot's own guide is
`ai/octopilot/AGENTS.md`.

## Machines

The dotfiles run on five machines:

- 3x Arch Linux
- 1x WSL running Arch Linux (GUI apps work there; treat it like any Arch box)
- 1x macOS (Apple Silicon)

Anything you add must work on Arch (pacman/yay) and macOS (Homebrew). OS
detection lives in `scripts/install.sh`. Do not hard-code paths, hostnames or
hardware. Facts about one machine go in `~/.claude/machine.md` on that machine,
never in the repo (`ai/claude/CLAUDE.md` imports that file).

## Layout

Shell and tools:

- `zshenv`, `zprofile`, `zshrc`, `zlogin`, `zlogout`, `zpreztorc`: zsh.
  `zprezto/` is a submodule.
- `completion/`: zsh completions (`_docker-compose`).
- `gitconfig`, `git/`: git config and `allowed_signers`, commit templates in
  `git/templates/`.
- `vimrc`, `vim/`, `vimundo/`: vim. `vim/bundle/Vundle.vim` is a submodule.
- `wezterm.lua`: WezTerm.
- `flexget/`: FlexGet configs (secrets stay out of git).
- `config/`: each entry is linked to `~/.config/<name>`. `kitty/` (its themes
  are a submodule) and `herdr/` (only its `config.toml`, see below).
- `scripts/install.sh`: the installer. Everything else here is what it links.

AI (`ai/`):

- `apm.yml`, `apm.lock.yaml`: the skills. `apm.yml` names each dependency's
  branch; `apm.lock.yaml` pins the commit, and only `skills-bump` moves it.
  Installed through APM (Agent Package Manager, 0.39 or newer).
- `claude/`: global Claude Code instructions (`CLAUDE.md`), `settings.json`,
  subagents in `agents/`.
- `pi/`: global Pi instructions (`AGENTS.md`), subagents in `agents/`.
- `prompts/`: slash-command prompts, shared by Pi and Claude.
- `hooks/`: `gh-hygiene.py`, a tool hook, with its regression suite.
- `octopilot/`: the Octopilot orchestrator and its herdr front ends. See
  `ai/octopilot/AGENTS.md`.
- `arxiu/`: the Arxiu research library and its Claude plugin. See
  `ai/arxiu/README.md`.
- `taller/`: the Taller board and its Claude plugin. See `ai/taller/README.md`.

## How files reach $HOME

Nothing is copied: `scripts/install.sh` creates symlinks.

- `symlink`: every top-level item not in its exclusion list
  (`README.md LICENSE scripts git config ai AGENTS.md CLAUDE.md`) becomes
  `~/.<name>`. A new top-level file is linked automatically, so a file that must
  not become a dotfile goes into that list.
- `symlink_config`: `config/<name>` becomes `~/.config/<name>`. `herdr` is
  skipped there; `link_herdr_config` links only its `config.toml`.
- `symlink_ai` (through `link_ai`):
  - `ai/prompts` to `~/.pi/agent/prompts` and `~/.claude/commands`
  - `ai/pi/agents` to `~/.pi/agent/agents`, `ai/pi/AGENTS.md` to `~/.pi/agent/AGENTS.md`
  - `ai/claude/CLAUDE.md` to `~/.claude/CLAUDE.md`, `ai/claude/agents` to `~/.claude/agents`
- `install_skills`: copies `ai/apm.yml` and `ai/apm.lock.yaml` to `~/.apm/` (as
  regular files) and runs `apm install -g --target agent-skills,claude` there, which
  deploys the skills to `~/.agents/skills/` and `~/.claude/skills/`. A lock APM
  rewrites is copied back to `ai/`. Every dependency must be a plain skill path:
  a native plugin would record per-machine paths in the lock.
  `~/.apm/apm.yml` is owned by the dotfiles and overwritten: add global deps in
  `ai/apm.yml`.
- `merge_claude_settings`: merges `ai/claude/settings.json` into
  `~/.claude/settings.json`, keeping keys other tools wrote. It sets
  `CLAUDE_CODE_PLUGIN_DIRS`, which loads the Claude plugins of
  `ai/octopilot/plugin`, `ai/arxiu/bibliotecaria` and `ai/taller/plugin`.

## Commands

`scripts/install.sh [command]` (no argument means `install`):

| Command | What it does |
|---|---|
| `install` | Full setup of a new machine: system packages, nvm, Claude Code and Pi, APM, herdr with herdr-app and herdr-core, uv, submodules, symlinks, AI config, herdr links, login shell, vim plugins. Files it replaces go to `~/old_dotfiles`. |
| `update` | Refreshes the same pieces without system packages or submodule ref bumps. Reinstalls herdr-app only when its version changed. |
| `ai` | Refreshes only the AI stack: agents, herdr, rtk, skills, AI links, settings, herdr links. |
| `ai-config` | Relinks prompts, instructions, agents and the locked skills. Installs no agents or tooling and makes no backups, except the legacy cleanup below. |
| `skills-bump` | Moves every skill to the latest commit of its branch (`apm update -g`), copies `ai/apm.yml` and `ai/apm.lock.yaml` back and shows `git diff --stat -- ai/`. The only command that changes skill versions; `install`, `update`, `ai` and `ai-config` install the locked commits. |
| `herdr` | Repairs the herdr setup: installs herdr if missing, its agent integrations, config and plugin links. Does not upgrade herdr or touch herdr-app (`install`, `update` and `ai` do). |

`install`, `update`, `ai` and `ai-config` all start with the legacy cleanup: agent-deck and aoe are uninstalled (Homebrew or pacman), their binaries, hooks in `~/.claude/settings.json` and skills are removed, and their state moves to `~/old_dotfiles/legacy-session-managers-<date>/`.

## herdr

[herdr](https://herdr.dev) is the terminal workspace manager that hosts
Octopilot's agents, in two front ends:

- **TUI**: `config/herdr/config.toml` is the tracked herdr config (keys, sidebar,
  notifications). Three herdr plugins are linked with `herdr plugin link` by
  `install.sh`: `elboletaire.octopilot` (`ai/octopilot/herdr`),
  `elboletaire.arxiu` (`ai/arxiu/herdr`) and `elboletaire.taller`
  (`ai/taller/herdr`).
- **GUI**: `herdr-app` runs the terminals in herdr-core (`hc`). Octopilot's native
  mods live in `ai/octopilot/herdr-app/mods/`. `ai/octopilot/herdr-app/install.sh`
  links them into `~/.config/herdr-app/mods/` and is run by `install.sh` when
  `herdr-app` is installed.

## Per-project docs

Each `ai/<project>/` has its own guide. Read it before changing that project, and
keep project detail there rather than in this file:

- `ai/octopilot/AGENTS.md`: Octopilot code changes. Also `ai/octopilot/herdr/README.md`
  (the TUI layout) and `ai/octopilot/herdr-app/CONTRACT.md` (the GUI contract).
- `ai/arxiu/README.md`
- `ai/taller/README.md`

## Conventions

- **Global agent instructions** are `ai/claude/CLAUDE.md` and `ai/pi/AGENTS.md`.
  They are linked into `$HOME`, so an edit changes every session on every
  machine. Keep them generic.
- **Comments**: 1-3 lines, saying why, not what.
- **Commits**: conventional commits (`feat(octopilot): ...`, `fix(...)`, `docs: ...`,
  `chore: ...`).
- **Secrets**: never commit them (tokens, `.env`, `flexget/secrets.yml`, anything
  from `~/.claude/machine.md`).
- **Parallel work**: use a git worktree under `.worktrees/` (for example
  `.worktrees/feat-x`), branched from a fresh `origin/<base>`. `.worktrees/` is
  in the repo's `.gitignore`.

## Adding machine-specific dashboards and tools

Put a tool that only one machine needs under `ai/<name>/`, as `octopilot`,
`arxiu` and `taller` are. Make it optional: `scripts/install.sh` should set it
up only when its command exists (`command -v`) or an opt-in env var or marker is
set, and skip it quietly otherwise. Document it in `ai/<name>/AGENTS.md` and
link that file from this one.
