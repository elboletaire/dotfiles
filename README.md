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
anything up to `~/old_dotfiles` (its legacy cleanup still moves old session
manager state there, see below):

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
  installed with pacman first. `update` (and `ai`) reruns the installer only when
  `releases.herdr.dev/app/latest.json` names a different version than
  `herdr-app --version`. On macOS it also waits while Herdr is running, and it
  skips with a note when offline. `install` skips the app when it is present.
  macOS installs `~/Applications/Herdr.app` (Apple Silicon only).
- **Legacy session managers**: `install`, `update`, `ai` and `ai-config` remove
  agent-deck and agent-of-empires (`aoe`) left over from before herdr: their
  packages (Homebrew or pacman), binaries, hooks in `~/.claude/settings.json`,
  and skills. Their config and state, plus `~/.tmux.conf` when it holds only
  agent-deck's block, move to `~/old_dotfiles/legacy-session-managers-<date>/`.
  A `~/.tmux.conf` with other lines is kept and a note is printed. Nothing is
  printed when there is nothing to clean.
- **Octopilot** lives in its own repo, [elboletaire/octopilot](https://github.com/elboletaire/octopilot).
  `install` clones it to `${OCTOPILOT_DIR:-~/src/octopilot}` when missing, `update`
  fast-forwards it when clean, and its `install.sh` sets up its herdr plugin and
  herdr-app mods. Details in `AGENTS.md` (External modules).

## AI skills

Skills are managed through [APM](https://github.com/microsoft/apm), 0.39 or
newer (`install_apm` installs or upgrades it). `ai/apm.yml` lists the
dependencies by branch; `ai/apm.lock.yaml` pins each one to a commit.

- **Installing** (`install`, `update`, `ai`, `ai-config`): `install_skills`
  copies both files to `~/.apm/` and runs `apm install -g` there. The lock
  decides the commits, so the same skills come back. If APM rewrites the lock,
  the new one is copied back to `ai/` with a note to review and commit it.
- **Bumping** (`install.sh skills-bump`): the only command that moves skills.
  It runs `apm update -g`, which takes each dependency to the latest commit of
  its branch, copies the manifest and lock back to `ai/`, and prints the diff.
  A failure leaves `ai/` untouched.
- **Global manifest**: `~/.apm/apm.yml` is owned by the dotfiles, which
  overwrites it on every install. Add global dependencies in `ai/apm.yml`, not
  there.
- **Targets**: `agent-skills` (`~/.agents/skills/`) and `claude`
  (`~/.claude/skills/`). Pi reads `~/.agents/skills/` natively.
