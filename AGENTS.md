# Dotfiles: agent guide

Personal dotfiles: shell, vim, git, terminal, and the AI tooling under `ai/`.
Coding agents working in this repo read this file. Octopilot lives in its own
repo, see [Per-project docs](#per-project-docs).

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
  Installed through APM (Agent Package Manager, 0.39 or newer). One of the
  dependencies is `elboletaire/skills` (alias `elboletaire-skills`): the personal
  skills, the Claude subagents and the gh hygiene hook, all in that repo.
- `claude/`: global Claude Code instructions (`CLAUDE.md`) and `settings.json`.
  Its subagents and hook come from `elboletaire/skills`.
- `pi/`: global Pi instructions (`AGENTS.md`). Its subagents come from
  `elboletaire/skills` too (`pi/agents/`), which APM does not install for Pi.
- `arxiu/`: the Arxiu research library and its Claude plugin. See
  `ai/arxiu/README.md`.
- `taller/`: the Taller board and its Claude plugin. See `ai/taller/README.md`.

## How files reach $HOME

Mostly symlinks: `scripts/install.sh` creates them. The exception is the APM
manifest and lock, copied into `~/.apm/` because APM refuses symlinks.

- `symlink`: every top-level item not in its exclusion list
  (`README.md LICENSE scripts git config ai AGENTS.md CLAUDE.md`) becomes
  `~/.<name>`. A new top-level file is linked automatically, so a file that must
  not become a dotfile goes into that list.
- `symlink_config`: `config/<name>` becomes `~/.config/<name>`. `herdr` is
  skipped there; `link_herdr_config` links only its `config.toml`.
- `symlink_ai` (through `link_ai`):
  - `ai/pi/AGENTS.md` to `~/.pi/agent/AGENTS.md`, `ai/claude/CLAUDE.md` to `~/.claude/CLAUDE.md`
- `_retire_ai_links` (first step of `install_skills` and `skills-bump`): removes
  the links the old `symlink_ai` made (`~/.claude/agents`, `~/.claude/commands`,
  `~/.pi/agent/prompts`, `~/.pi/agent/agents`) when they point into `ai/` or are
  dangling. Done before APM runs, so it never writes through them into the repo.
- `install_skills`: copies `ai/apm.yml` and `ai/apm.lock.yaml` to `~/.apm/` (as
  regular files) and runs `apm install -g --target agent-skills,claude` there, which
  deploys the skills to `~/.agents/skills/` and `~/.claude/skills/`, the Claude
  subagents to `~/.claude/agents/` and the hook to `~/.claude/settings.json`. A
  lock APM rewrites is copied back to `ai/`. Every dependency must be a plain skill path:
  a native plugin would record per-machine paths in the lock.
  `~/.apm/apm.yml` is owned by the dotfiles and overwritten: add global deps in
  `ai/apm.yml`.
- `link_pi_agents` (after `install_skills`): links `~/.pi/agent/agents` to
  `~/.apm/apm_modules/elboletaire-skills/pi/agents`, APM's module cache of the
  package. It warns and skips when that folder is missing. It moves a real
  `~/.pi/agent/agents` dir to `~/old_dotfiles/.pi/agent/agents` before linking it.
- `merge_claude_settings`: merges `ai/claude/settings.json` into
  `~/.claude/settings.json`, keeping keys other tools wrote (APM's hook included).
  It sets `CLAUDE_CODE_PLUGIN_DIRS`, which loads the Claude plugins of
  `~/src/octopilot/plugin` (Octopilot's repo, see
  [External modules](#external-modules)), `ai/arxiu/bibliotecaria` and
  `ai/taller/plugin`. The gh hygiene hook blocks the local hostname on its own;
  extra names for a machine go in that machine's own environment, never here.

## Commands

`scripts/install.sh [command]` (no argument means `install`):

| Command | What it does |
|---|---|
| `install` | Full setup of a new machine: system packages, nvm, Claude Code and Pi, APM, herdr with herdr-app and herdr-core, uv, submodules, symlinks, AI config, herdr links, external modules, login shell, vim plugins. Files it replaces go to `~/old_dotfiles`. |
| `update` | Refreshes the same pieces without system packages or submodule ref bumps, and fast-forwards the external modules. Reinstalls herdr-app only when its version changed. |
| `ai` | Refreshes only the AI stack: agents, herdr, rtk, skills, AI links, settings, herdr links, and fast-forwards the external modules. |
| `ai-config` | Relinks the global instructions, installs the locked skills, subagents and hook, and runs the external modules' `install.sh` when already cloned. Installs no agents or tooling, clones and pulls nothing, and makes no backups beyond the legacy cleanup below and `settings.json.dotfiles-bak`. |
| `skills-bump` | Moves every skill to the latest commit of its branch (`apm update -g`), copies `ai/apm.yml` and `ai/apm.lock.yaml` back and shows `git diff --stat -- ai/`. The only command that changes skill versions; `install`, `update`, `ai` and `ai-config` install the locked commits. |
| `herdr` | Repairs the herdr setup: installs herdr if missing, its agent integrations, config and plugin links, and clones missing external modules and runs their `install.sh`. Does not pull modules, upgrade herdr or touch herdr-app (`install`, `update` and `ai` do). |

`install`, `update`, `ai` and `ai-config` all start with the legacy cleanup: agent-deck and aoe are uninstalled (Homebrew or pacman), their binaries, hooks in `~/.claude/settings.json` and skills are removed, and their state moves to `~/old_dotfiles/legacy-session-managers-<date>/`.
The retired hand-installed skills (`aoe`, `aoe-fleet`, `impeccable`,
`graphic-designer`, `effective-print-design`, `resume-generator`, `brag`,
`brag-slim`, `tsdown`, `vocdoni-sdk`, `davinci-sdk`, `vocdoni-ballot-protocol`,
`agent-browser` and `create-readme`) are removed where APM's lock does not
deploy them: symlinks are deleted, real copies move to
`~/old_dotfiles/legacy-skills-<date>/`. The one-time APM 0.33 migration in
`install_skills` moves that deployment's skills and hook files there too.

## herdr

[herdr](https://herdr.dev) is the terminal workspace manager that hosts
Octopilot's agents, in two front ends:

- **TUI**: `config/herdr/config.toml` is the tracked herdr config (keys, sidebar,
  notifications). Two herdr plugins are linked with `herdr plugin link` by
  `install.sh`: `elboletaire.arxiu` (`ai/arxiu/herdr`) and `elboletaire.taller`
  (`ai/taller/herdr`). Octopilot's plugin (`elboletaire.octopilot`) is linked by
  its own `install.sh`, see [External modules](#external-modules).
- **GUI**: `herdr-app` runs the terminals in herdr-core (`hc`). Octopilot's
  mods are installed by its own `install.sh` too. Moll's mods (outside the
  dotfiles, in `~/docker/moll`) are linked when that checkout exists, else
  copied from the host named in `MOLL_HOST` or `~/.config/moll/host`.

## Per-project docs

Each `ai/<project>/` has its own guide. Read it before changing that project, and
keep project detail there rather than in this file:

- Octopilot is its own repo, `https://github.com/elboletaire/octopilot.git`, cloned to
  `${OCTOPILOT_DIR:-~/src/octopilot}`. Its `AGENTS.md` covers code changes, its
  `herdr/README.md` the TUI layout and its `herdr-app/CONTRACT.md` the GUI contract.
- `ai/arxiu/README.md`
- `ai/taller/README.md`

## External modules

Some tools live in their own repos. `MODULES` in `scripts/install.sh` lists them
as `name|git-url|dir`, and `install_modules` handles each one:

- **Clone**: when `dir` is missing, it is cloned from `git-url` (`install`,
  `update`, `ai`, `herdr`). The dotfiles' gitconfig rewrites GitHub https URLs to
  ssh (`url "ssh://git@github.com/"`), so the clone needs the machine's GitHub ssh
  key, as the dotfiles' own pushes do.
- **Update**: `update` and `ai` fast-forward a clean checkout on its default
  branch (from `origin/HEAD`, or the upstream when that is main or master). A
  dirty tree, another branch, or an offline or diverged remote is left alone with
  a note. `install` and `herdr` do not pull.
- **Run**: its `install.sh`, when executable, runs last. A missing module
  checkout with no `.git` or a non-executable `install.sh` gets a warning.
  `ai-config` runs it only when the module is already cloned, and never clones or
  pulls; when it is missing, `ai-config` prints a note saying where it belongs.
- **Non-interactive**: git runs with `GIT_TERMINAL_PROMPT=0` and an ssh with
  `BatchMode=yes`, so a clone or pull never waits for a password.

Octopilot's dir is `${OCTOPILOT_DIR:-~/src/octopilot}`. When it is not the
default, `merge_claude_settings` rewrites its `CLAUDE_CODE_PLUGIN_DIRS` entry
(`~/src/octopilot/plugin` in `ai/claude/settings.json`) to `<dir>/plugin`.
`OCTOPILOT_DIR` must be exported in every shell that runs `install.sh`, for
instance from a machine-local `~/.zshenv` override, or the settings keep the
default path.

A failure warns and the install carries on. Octopilot is the only entry; add
arxiu or taller there when they move out.

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

Put a tool that only one machine needs under `ai/<name>/`, as `arxiu` and
`taller` are, or in its own repo, listed in `MODULES` (see
[External modules](#external-modules)). Make it optional: `scripts/install.sh`
should set it up only when its command exists (`command -v`) or an opt-in env var
or marker is set, and skip it quietly otherwise. Document it in `ai/<name>/AGENTS.md`
and link that file from this one.
