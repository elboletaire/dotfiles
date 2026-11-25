# Octopilot in herdr

A herdr plugin that gives octopilot a home: an **Octopilot** workspace with the
orchestrator on the left and the live dashboard (`../dashboard.sh`) on the
right. The dashboard updates by itself -- no asking the orchestrator for the
table.

Every work session is a herdr workspace on its worktree, grouped under its
repo's workspace, with a claude agent named `ap-<repo>-<number>`. The
orchestrator is the agent named `octopilot`.

## Setup

`scripts/install.sh` links the plugin when herdr is installed. By hand:

```sh
herdr plugin link ~/.dotfiles/ai/octopilot/herdr
```

Its actions are bound in `config/herdr/config.toml` (tracked; `scripts/install.sh herdr`
links it to `~/.config/herdr/config.toml`):

```toml
[[keys.command]]
key = "prefix+shift+a"          # build or focus the Octopilot workspace
type = "plugin_action"
command = "elboletaire.octopilot.open"

[[keys.command]]
key = "prefix+a"                # the dashboard over whatever you are doing
type = "plugin_action"
command = "elboletaire.octopilot.peek"
```

The workspace has two tabs: **OCTOPILOT**, described below, and **Octopilot
(code changes)**, a claude started in the dotfiles for changing octopilot
itself. In OCTOPILOT, the dashboard pane is titled `dashboard`.

`open` starts the orchestrator as a fresh claude in `OCTOPILOT_ORCH_CWD`
(`~/src`) in a small **messenger** pane, which starts ticking by itself
(`/octopilot:messenger`), and the **prompter** below it, a second claude running
`/octopilot:prompter`. Type in the prompter: it answers from octopilot's state
and queues your commands in the orchestrator's inbox. Agent reports and the
dashboard's keys go to that inbox too, so nothing is ever typed into a pane
you are writing in. On an existing workspace, `open` adds whichever of the prompter and the
code-changes tab is missing, and names the first tab OCTOPILOT.

Show octopilot's state on each worker's row in the herdr sidebar (the
dashboard publishes these tokens; they expire ten minutes after it stops):

```toml
[ui]
agent_panel_sort = "priority"   # blocked and finished agents first
status_indicators = "symbols"
sidebar_width = 34

[ui.sidebar.agents]
rows = [["state_icon", "workspace"],
        ["$ap_kind", "$ap_pr", "$ap_rounds", "$ap_ci"],
        ["$ap_note"]]
```

Notifications: the dashboard sends a desktop notification (`notify-send`) when
an item enters 🔴 Needs you -- once per item and reason, never on repeats --
and the orchestrator and its agents send none of their own. Keep herdr's own
per-turn notifications inside herdr so they do not drown it out:

```toml
[ui.toast]
delivery = "herdr"   # in-app toasts only; "off" silences them entirely

[ui.sound.agents]
claude = "off"       # no state-change sounds from Claude agents (all of them)
```

The dashboard also runs outside herdr: `~/.dotfiles/ai/octopilot/dashboard.sh`.
It needs `uv` (which provides `rich`); there is nothing else to install.

## GUI (herdr-app)

`herdr/open-gui.sh` builds Octopilot in the Herdr app (`herdr-app`, its
terminals run in herdr-core) as one space with three tabs:

| Tab | Holds |
|---|---|
| **OCTOPILOT** | the `octopilot-dashboard` mod (the table below) and, beside it, the `octopilot-chat` mod: the prompter as a chat |
| **engine** | the orchestrator (`octopilot`, `/octopilot:messenger`), the prompter (`octopilot-prompter`) and `dashboard.sh --headless` (`octopilot-headless`), each an hc terminal |
| **Octopilot (code changes)** | a claude for changing octopilot itself |

The headless dashboard runs the loops and writes `view.json`; the mods only
render it and send actions. The octopus window (the orchestrator's last
message and the kitchen log) is the `octopilot-octopus` mod, opened by the
dashboard, not by the launcher.

Each claude starts with `claude --session-id <uuid>` and is labelled
`octopilot.session=<uuid>`, which names its transcript
(`~/.claude/projects/*/<uuid>.jsonl`). `scan.sh speech --json` reads the
orchestrator's last message, `scan.sh chat --json [--after <id>]` the prompter's
conversation, and `scan.sh chat-send <text>` / `chat-keys <keys>` type into the
prompter. Under the TUI backend, or with nothing running, they report
`"status": "offline"`.

**Launch and install.** `herdr-app/install.sh` links each
`herdr-app/mods/<name>` into `~/.config/herdr-app/mods/` (a real file or folder
there is refused, never replaced), and adds an `octopilot` entry to
`programs.json` that runs `herdr/open-gui.sh --close-launcher`. The
`octopilot-launcher` mod's palette entry, "Open Octopilot" (ctrl-shift-p), runs
the same thing in a new tab, which closes again once the space is up. The
palette entry always opens the live checkout (`~/.dotfiles`); `--dir` moves only
the mod symlinks and the `programs.json` entry to another checkout. The launcher
closes its own pane when the space is up (never the tab: the tab goes only with
its last pane). `scripts/install.sh` runs the
installer when `herdr-app` is installed. It does not bind a key: pass `--key`
to bind `ctrl-alt-o` in `keys.json` as well (backed up first, a key bound to
something else is left alone). Other options: `--dry-run`, `--uninstall`
(removes what is ours, recognised by shape). `HERDR_APP_HOME` picks another app
home, as herdr-app does. A `keys.json` you edit stops getting herdr-app's new
default shortcuts on upgrade, which is why the key is opt-in. A rejected
`programs.json` or `keys.json` leaves a `.error` file, which the installer reports.

**The octopilot layout.** The installer also writes `~/.config/herdr-app/layouts/octopilot.json`:
a copy of your `layouts/main.json` (recorded as `cloned_from`) plus a floating block
that docks the `octopilot-kitchen` mod in the right-hand corner of every tab. It is
regenerated on each run, a file of that name that is not ours is left alone,
`--uninstall` removes it, and a `layout.error` is reported. After building the
space, `open-gui.sh` switches to it with `layout.switch` when it exists
(`--no-layout` skips that; `--terminals` never switches). Re-run the installer after
changing `main.json`.

**Fallback.** `open-gui.sh --terminals` builds the TUI-style layout instead:
one OCTOPILOT tab with the messenger, the curses dashboard and the prompter as
terminal panes, plus the code-changes tab. On a space that already has the GUI
layout it refuses, and a rerun on a space with the curses dashboard of that
layout refuses too, so two dashboard loops never run.

To test it next to a live TUI octopilot, run it from a worktree with a scratch
state dir. Without `OCTOPILOT_STATE_DIR` it refuses, so a worktree never
shares the live `state.json`:

```sh
OCTOPILOT_STATE_DIR=~/.local/state/octopilot-gui-test \
HOME_REPOS="<owner/repo>" ISSUE_ORGS="<org>" \
  ~/.dotfiles/.worktrees/<branch>/ai/octopilot/herdr/open-gui.sh
```

`HOME_REPOS`, `ISSUE_ORGS` and `CLONE_ROOTS` narrow what the test scans; only
the values you set are passed on, so config.sh's defaults keep applying to
everything else. The script refuses to run when the orchestrator labelled
`octopilot.agent=octopilot` runs from another checkout (`octopilot.dir` label,
since labels are global). Its own sessions (the engine tab, the headless
dashboard and the code tab) get `OCTOPILOT_BACKEND=hc`, `OCTOPILOT_DIR` and
`OCTOPILOT_STATE_DIR` from this script. The workers that scan.py spawns get them
from scan.py, so the test is only isolated as far as that hand-off goes.

Plugins: settings.json's `CLAUDE_CODE_PLUGIN_DIRS` loads the installed
`octopilot` plugin into every session. A worktree's `--plugin-dir` does not
replace it: the installed copy still wins, and the worktree's takoyaki hook
never loads (`claude -p ... --plugin-dir <worktree>/plugin --debug` prints
`octopilot: hooks module not loaded: another plugin of that name loads first`).
Setting the env var in the process does not replace it either, since settings
env overwrites the process env. What works is `--settings`, which open-gui.sh
and the GUI spawns pass: `scan.sh plugin-settings` prints that JSON, with the
worktree's plugin in place of the installed one and the other plugin dirs
kept, or nothing on the live checkout. Checked with `claude --settings
"$(scan.sh plugin-settings)" plugin list --json`: `octopilot@inline` points at
the worktree, and `arxiu-bibliotecaria@inline` and `taller@inline` remain.

Only the GUI spawns carry `OCTOPILOT_DIR`, `OCTOPILOT_STATE_DIR` and the
`--settings` override. TUI workers spawned by a worktree's octopilot get
neither, so they run the live scan.sh and plugin.

Close the test space with `herdr-app do space.close --id <space> --confirmed true`.

## What it shows

| Section | Rows |
|---|---|
| 🔴 Needs you | `CAPPED`, `READY`, `PUSHED`, `STALLED`, `CLOSED`, agents waiting on a question, and agents whose last report was `blocked`/`failed`/`stalled`/`capped` |
| ⏭ Next tick | `MERGED`, `REVIEW`, `FEEDBACK`, `BOOTING` -- what the orchestrator will do on its next tick |
| 🟡 Running | `WORKING`, and anything spawned since the last GitHub refresh |
| ✔ Done | `DONE`, `GONE`, and cards you parked with `d` (they keep their workspace and hold no slot; new feedback or a re-requested review brings them back). Done rows without a workspace are hidden; `D` shows them |
| ⚪ Pick next | `PROPOSE` |

Agent state comes from herdr every 3s, heartbeats, rounds and reports the moment
they are written, and GitHub (PR state, CI) every `DASHBOARD_REFRESH_SECS`
(config.sh, 120s) or right after an event that changes the table. Several open
dashboards share one refresh. GitHub notifications are polled every 60s
(`NOTIFY_POLL_SECS`) and trigger an early refresh; a new Next tick row rings the
orchestrator's doorbell once (`request tick`).

## Keys

| Key | Does |
|---|---|
| `↑↓` / `jk` | move |
| `⏎` | go to the agent, in its own workspace |
| `v` | the agent in a popup over the dashboard; `ctrl+b q` closes it and leaves the agent running |
| `a` | go to the prompter (the orchestrator if there is none) |
| `t` | shell in the item's worktree |
| `o` | PR or issue in the browser |
| `g` / `n` | on a Pick next row: queue `go <key>` / `no <key>` for the orchestrator (press twice; past `WIND_DOWN_AT` the second press confirms starting anyway) |
| `R` | on a CAPPED row: grant another `MAX_REVIEW_ROUNDS` review rounds (press twice) |
| `e` / `x` | on a PUSHED (stale) row: queue a re-review / ack the new commits (press twice) |
| `i` | start an investigation: type the repo, the question, and whether it is read-only |
| `P` | pause / resume octopilot (press twice) |
| `z` | detach a tracked item: closes its workspace, keeps the worktree, stops tracking it (press twice) |
| `del` | remove a tracked item: deletes its workspace and worktree, stops tracking it (press twice). Not on MERGED rows: the orchestrator cleans those up |
| `r` | refresh from GitHub now |
| `d` | on a tracked card: move it to Done / back (press twice). It keeps its workspace and holds no slot; the orchestrator still merges and cleans up |
| `D` | show / hide done rows (DONE, GONE) |
| `q` | quit |
