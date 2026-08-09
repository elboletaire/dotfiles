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
