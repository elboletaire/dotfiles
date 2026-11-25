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
(code changes)**, a claude started in the dotfiles for changing octopilot itself
(`octopilot-code`). In OCTOPILOT, the dashboard pane is titled
`dashboard`.

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
| **OCTOPILOT** | the `octopilot-kitchen` mod, a pane 300 px tall, on the left, over the `octopilot-chat` mod (the prompter as a chat, its input at the bottom); on the right the `octopilot-dashboard` mod (the table below), full height (`props`: `dir`, `state_dir`; its pane is named by `pane.rename`, the mod reads no name) |
| **engine** | the orchestrator (`octopilot`, `/octopilot:messenger`), the prompter (`octopilot-prompter`) and `dashboard.sh --headless` (`octopilot-headless`), each an hc terminal. Parked after building: they keep running with no pane, so the tab goes away (see below) |
| **Octopilot (code changes)** | the code agent's own claude (`octopilot-code`, a claude in the dotfiles root, an hc terminal that is never parked) |

The engine is hidden on purpose. After building, `open-gui.sh` parks its three
terminals (`herdr-app do terminal.park`): the pane goes, the process keeps
running and core keep is off, so the empty engine tab goes too. They are found
by their `octopilot.agent` labels, not by panes, so a rerun finds them parked.
A parked orchestrator keeps its space in an `octopilot.space` label (parking
removes `herdr.space`). A parked terminal is shown with `terminal.peek` (the
chef in the kitchen, the chat's Terminal button, the dashboard's `v` and `a`),
which works on it. `--show-engine` keeps the engine tab visible (no park, for
debugging). On a rerun, `--terminals` and `--show-engine` refuse and list the
parked engine terminals, each to show with `herdr-app do terminal.keep`.

Viewed from another computer (the Octopilot space is on a remote machine, see
`CONTRACT.md`), the mods run their commands and read `view.json` on that machine,
from their `dir` and `state_dir` props, and poll it every 2 s (no folder watch).
Their headers say `· on <machine>`.

Rerunning finds what is there. A parked orchestrator whose space is closed means
octopilot was closed with it: its engine terminals of this checkout are ended,
and it is built again. After a core restart the parked engine is gone, but the
space and its code agent are back: the orchestrator starts in the space named
`Octopilot` (or the code agent's), in a new tab that the run parks. An engine
terminal not running its claude (or the headless's uv) is ended and started again.
The launcher never ends the code agent: it is your own claude session.

The code agent is not an engine terminal: its claude is the terminal of the code
tab, so its pickers and sub-agents are Claude's own, and `--show-engine` does not
touch it.

A code agent from an earlier run is converted on a rerun. A parked agent (the
previous version's chat tab) is labelled with the space and, if that does not show
it, given a tab with `terminal.keep`; a shown agent is never moved. Only when it is
then alone in a tab of this space does that tab take the name and the old chat tab
go; otherwise the run warns and leaves it. A side panel an earlier run put beside the
agent (its label `octopilot.side=<tab>:<pane>`) is closed when that label names this
tab and `pane.rename` finds the pane, and the label is removed. A tab that holds a
terminal other than the agent's is refused, never closed.

In the `--terminals` layout, the dashboard's `a` peeks the prompter (or the
orchestrator), as the GUI layout does, and the code agent stays a terminal in its
own "Octopilot (code changes)" tab (the TUI layout has no mods).

Every engine terminal starts through the user's interactive shell (`$SHELL -ic
'exec "$@"'`), so the gateway env in `~/.zshrc.local` reaches claude. herdr-app
already runs the argv of `space.new` and `tab.new` in the shell (and keeps the
shell open after the program), but runs `pane.split` argv as given, so the
helpers beside the orchestrator are wrapped by open-gui.sh (`shell_argv`). It
uses `exec`, not herdr's keep-shell form: a shell left behind would keep a dead
agent's terminal alive and labelled, and the reruns would never restart it.

The headless dashboard runs the loops and writes `view.json`; the mods only
render it and send actions. The kitchen is the `octopilot-kitchen` mod, a pane
split down from the chat (`pane.split`), moved above it (`pane.swap`), then sized to 300 px
with `pane.resize` (both only when it is created; a rerun never moves or resizes it).
The run records the chat's pane on the orchestrator (`octopilot.chat=<tab>:<pane>`)
and the kitchen's (`octopilot.kitchen=<tab>:<pane>`). A record counts only when its
tab is this space's OCTOPILOT tab, and a rerun keeps the kitchen while its pane
exists (a `pane.rename` probe), else splits a new one. The
steps are best effort: a failure is warned about and the run goes on. A tab from
an earlier run has no `octopilot.chat` record, so a rerun cannot split its kitchen:
it says so and leaves the tab as it is. Add it once by hand: focus the chat pane,
take its id (`herdr-app status` `focused_pane`) and the OCTOPILOT tab's id
(`herdr-app ls`), record `octopilot.chat=<tab>:<pane>` on the orchestrator, and
rerun `open-gui.sh`.

Each claude starts with `claude --session-id <uuid>` and is labelled
`octopilot.session=<uuid>`. Its transcript (`~/.claude/projects/*/<uuid>.jsonl`)
is found from the claude in the terminal's foreground, through its
`~/.claude/sessions/<pid>.json` (which follows `/clear`); the label is only the
fallback when no claude runs there. `scan.sh speech --json` reads the
orchestrator's last message, `scan.sh chat --json [--after <id>]` the prompter's
conversation, and `scan.sh chat-send <text>` / `chat-keys <keys>` type into the
prompter. Under the TUI backend, or with nothing running, they report
`"status": "offline"`.

**Launch and install.** `herdr-app/install.sh` links each
`herdr-app/mods/<name>` into `~/.config/herdr-app/mods/` (a real file or folder
there is refused, never replaced), removes our links whose mod folder is gone
(dangling links into this checkout's mods; a foreign link is kept), and adds an
`octopilot` entry to
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

**No octopilot layout.** Earlier versions wrote `~/.config/herdr-app/layouts/octopilot.json`
(the kitchen as a floating block of every tab). The installer removes it when it is
ours (recognised by that block), on install and on `--uninstall`; when the app shows
it, the app is switched to `main` first. A layout of that name that is not ours is
left alone. `open-gui.sh --no-layout` is accepted and does nothing.

**Fallback.** `open-gui.sh --terminals` builds the TUI-style layout instead:
one OCTOPILOT tab with the messenger, the curses dashboard and the prompter as
terminal panes, plus the code-changes tab as a terminal tab. On a space that already has the GUI
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
| `o` | PR or issue in the browser, opened on the computer you are at (the mod runs `xdg-open`, `open` or `start`), not on the octopilot's machine; no URL: `dashboard.sh --action browser` |
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
