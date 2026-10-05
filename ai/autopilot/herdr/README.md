# PR Autopilot in herdr

A herdr plugin that gives autopilot a home: an **Autopilot** workspace with the
orchestrator on the left and the live dashboard (`../dashboard.sh`) on the
right. The dashboard updates by itself -- no asking the orchestrator for the
table.

With `AUTOPILOT_BACKEND="herdr"` (config.sh, the default) every work session
is a herdr workspace on its worktree, grouped under its repo's workspace, with
a claude agent named `ap-<repo>-<number>`. The orchestrator is the agent named
`autopilot`. Items spawned in aoe before the switch stay there until they are
done; nothing needs migrating.

## Setup

`scripts/install.sh` links the plugin when herdr is installed. By hand:

```sh
herdr plugin link ~/.dotfiles/ai/autopilot/herdr
```

Bind its actions in `~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "prefix+shift+a"          # build or focus the Autopilot workspace
type = "plugin_action"
command = "elboletaire.autopilot.open"

[[keys.command]]
key = "prefix+a"                # the dashboard over whatever you are doing
type = "plugin_action"
command = "elboletaire.autopilot.peek"
```

`open` starts the orchestrator as a fresh claude in `AUTOPILOT_ORCH_CWD`
(`~/.dotfiles`); type `/pr-autopilot` in it to start ticking. If the recorded
orchestrator is still an aoe session, the left pane attaches to it instead.

Show autopilot's state on each worker's row in the herdr sidebar (the
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

The dashboard also runs outside herdr: `~/.dotfiles/ai/autopilot/dashboard.sh`.
It needs `uv` (which provides `rich`); there is nothing else to install.

## What it shows

| Section | Rows |
|---|---|
| 🔴 Needs you | `CAPPED`, `READY`, `PUSHED`, `STALLED`, `CLOSED`, agents waiting on a question, and agents whose last report was `blocked`/`failed`/`stalled`/`capped` |
| ⏭ Next tick | `MERGED`, `REVIEW`, `FEEDBACK`, `BOOTING` -- what the orchestrator will do on its next tick |
| 🟡 Running | `WORKING`, and anything spawned since the last GitHub refresh |
| ✔ Done | `DONE`, `GONE` (hidden; `d` toggles) |
| ⚪ Pick next | `PROPOSE` |

Agent state comes from herdr and aoe every 3s, heartbeats, rounds and reports the moment
they are written, and GitHub (PR state, CI) every `DASHBOARD_REFRESH_SECS`
(config.sh, 120s) or right after an event that changes the table. Several open
dashboards share one refresh.

## Keys

| Key | Does |
|---|---|
| `↑↓` / `jk` | move |
| `⏎` | go to the agent (herdr), or open its aoe session (a popup in herdr; `Ctrl-b d` closes it) |
| `a` | go to the orchestrator |
| `t` | shell in the item's worktree |
| `o` | PR or issue in the browser |
| `g` / `n` | on a Pick next row: send `go <key>` / `no <key>` to the orchestrator (press twice) |
| `P` | pause / resume autopilot (press twice) |
| `r` | refresh from GitHub now |
| `d` | show / hide done rows |
| `q` | quit |
