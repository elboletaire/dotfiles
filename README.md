dotfiles
========

My dotfiles (use at your own risk)

Installation
------------

Just clone and run the install script:

~~~bash
git clone https://github.com/elboletaire/dotfiles .dotfiles && cd .dotfiles
./scripts/install.sh
~~~

To refresh only the AI config (prompts, instructions, agents and the pinned
skills from `ai/`) without installing agents or tooling, and without backing
anything up to `~/old_dotfiles`:

~~~bash
./scripts/install.sh ai-config
~~~

The herdr pieces are installed and kept current by `install` and `update`
(`ai` does the same for the AI stack; `herdr` only repairs herdr's setup):

- **herdr** (terminal workspace manager): installed with its official script on
  Linux, Homebrew on macOS. An existing herdr is upgraded by whoever owns it
  (pacman via yay, Homebrew, or `herdr update` for the copy from the script),
  so no second copy appears.
- **herdr-app** (desktop app, with `herdr-core` / `hc` when none is installed):
  installed from `https://releases.herdr.dev/app/install.sh`. On Arch the app's
  runtime libraries (`vulkan-icd-loader mesa libxkbcommon-x11 wayland`) are
  installed with pacman first. `update` reruns the installer, which is
  idempotent and updates the app in place; `install` skips it when present.
  macOS installs `~/Applications/Herdr.app` (Apple Silicon only).
- **Legacy session managers**: `install`, `update`, `ai` and `ai-config` remove
  agent-deck and agent-of-empires (`aoe`) left over from before herdr. Binaries
  are deleted; their config and state, plus `~/.tmux.conf` when it holds only
  agent-deck's block, are moved to `~/old_dotfiles/legacy-session-managers-<date>/`.
  The `fleet` skill goes only where it names agent-deck. A `~/.tmux.conf` with
  other lines is kept and a note is printed. Nothing is printed when there is
  nothing to clean.

## AI skills

Skills are managed via [APM](https://github.com/microsoft/apm) (Agent Package Manager).
The tracked `ai/apm.yml` and `ai/apm.lock.yaml` define the full set. The `ai/`
directory is treated as a local APM package: a global install deploys its
dependencies into `~/.agents/skills/` and `~/.claude/skills/` without
overwriting unrelated global APM entries.

- **Dependencies are commit-pinned** in both `ai/apm.yml` and
  `ai/apm.lock.yaml`; every skill uses a full Git commit SHA. Running
  `install.sh` therefore reproduces the exact version set.
- **`install_apm`** -- installs the APM CLI when absent (macOS: Homebrew;
  Linux: downloaded installer script).
- **`symlink_ai`** -- removes legacy per-skill symlinks (recording them for
  rollback) and globally installs both targets. When the local package already
  exists, it first validates the pinned project, rebuilds APM's flattened
  global graph, and prunes retired skills previously owned by this package
  while preserving unrelated global dependencies. On failure, tracked global
  state and removed legacy symlinks are restored where possible.
- **`update_apm_skills`** -- resolves each configured repository's default
  branch to an exact commit in an isolated temporary project, asks APM to
  validate those pins and rebuild the lock, and only then copies the results
  into `ai/`. This avoids APM's annotated-tag requirement for updating raw SHA
  pins. The update flows then perform one global package sync; resolver or APM
  failures leave the tracked files untouched.
- **Targets**: `agent-skills` (`~/.agents/skills/`) and `claude`
  (`~/.claude/skills/`). Pi discovers skills natively from
  `~/.agents/skills/`.
