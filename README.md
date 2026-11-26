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

To refresh only the AI config (the instructions and the pinned skills from
`ai/`, with the subagents and hook they bring) without installing agents or
tooling, run:

~~~bash
./scripts/install.sh ai-config
~~~

It moves files to `~/old_dotfiles` only for the legacy cleanup and the APM 0.33
migration below. A real `~/.pi/agent/agents` dir goes to
`~/old_dotfiles/.pi/agent/agents`. The settings merge keeps the previous
`~/.claude/settings.json` as `settings.json.dotfiles-bak`.

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
  macOS installs `~/Applications/Herdr.app` (Apple Silicon only). Moll's mods are
  linked when `~/docker/moll` exists, else copied from the host in `MOLL_HOST` or `~/.config/moll/host`.
- **Legacy session managers**: `install`, `update`, `ai` and `ai-config` remove
  agent-deck and agent-of-empires (`aoe`) left over from before herdr: their
  packages (Homebrew or pacman), binaries, hooks in `~/.claude/settings.json`,
  and the fleet and agent-deck skills. Their config and state, plus
  `~/.tmux.conf` when it holds only agent-deck's block, move to
  `~/old_dotfiles/legacy-session-managers-<date>/`. A `~/.tmux.conf` with other
  lines is kept and a note is printed. Nothing is printed when there is nothing
  to clean.
- **Retired skills**: `aoe`, `aoe-fleet`, `impeccable`, `graphic-designer`,
  `effective-print-design`, `resume-generator`, `brag`, `brag-slim`, `tsdown`,
  `vocdoni-sdk`, `davinci-sdk`, `vocdoni-ballot-protocol`, `agent-browser` and
  `create-readme` are removed where APM's lock does not deploy them: symlinks
  are deleted, real copies move to `~/old_dotfiles/legacy-skills-<date>/`. The
  one-time APM 0.33 migration moves its deployed skills and hook files there
  too.
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
- **elboletaire/skills**: the personal skills (`review`, `version`, `init-agents`,
  `dream`, `herdr-orchestrator`), the Claude subagents in `~/.claude/agents/` and
  the gh hygiene hook in `~/.claude/settings.json`, all from
  [elboletaire/skills](https://github.com/elboletaire/skills). APM has no Pi
  target, so the install links `~/.pi/agent/agents` to the Pi subagents in
  APM's module cache (`~/.apm/apm_modules/elboletaire-skills/pi/agents`).
- **Hostnames**: the hook blocks this machine's hostname. Extra names for a
  machine go in that machine's own environment, never in the repo.
