# Octopilot GUI contract (herdr-app)

The herdr-app interface is native mods over the same backend the TUI uses. All
decisions stay in Python (dashboard.py / scan.py); mods only render and send
actions. `$DIR` is the octopilot code dir (`props().dir`, else
`shared("octopilot.dir")`, else `~/.dotfiles/ai/octopilot`); `$STATE_DIR` is
`props().state_dir`, else `shared("octopilot.state_dir")`, else
`~/.local/state/octopilot`.

## Pieces

| piece | where | role |
|---|---|---|
| headless dashboard | `dashboard.sh --headless` in an hc terminal ("engine" tab) | runs every dashboard loop (GitHub refresh, doorbell, notifications, desktop notify, sidebar tokens) and writes `$STATE_DIR/view.json` |
| `octopilot-dashboard` mod | pane in the Octopilot tab | renders view.json, keyboard + mouse, sends actions |
| `octopilot-chat` mod | pane in the Octopilot tab | the prompter as a chat over its hc terminal |
| `octopilot-octopus` mod | floating window (`openOverlay` kind window, key `octopilot-octopus`, keep) | the messenger: what the orchestrator last said + kitchen log |
| `herdr/open-gui.sh` | launcher | builds the space, starts terminals with `--session-id`, opens the mods |
| `octopilot-launcher` mod | palette entry "Open Octopilot" (no view) | runs `herdr/open-gui.sh --close-launcher` in a new tab |
| `herdr-app/install.sh` | installer | symlinks mods into `~/.config/herdr-app/mods/`, adds the `octopilot` program to `programs.json`; `--key` also binds ctrl-alt-o |

## view.json (written atomically by `dashboard.sh --headless`, on change and at least every 5 s)

```jsonc
{
  "v": 1, "generated_at": 1732530000.0,           // epoch seconds
  "header": {
    "needs": 2, "running": 3, "pick": 14,           // running counts running + next tick
    "active": 4, "max_active": 6, "untracked": 1,
    "github": {"state": "ok|stale|old|refreshing|none", "age_s": 42, "error": null},
    "last_tick_s": 120,                             // seconds ago, null = never
    "orch_label": "octopilot",
    "paused": false,
    "wind_down": {"state": "yes|no|off", "at": "16:00"}
  },
  "columns": [                                      // always these four, in this order
    {"id": "running", "title": "🟡 Running",   "entries": [Entry]},
    {"id": "orch",    "title": "⏭ Next tick", "entries": [Entry]},
    {"id": "needs",   "title": "🔴 Needs you", "entries": [Entry]},
    {"id": "done",    "title": "💤 Done",      "entries": [Entry], "hidden": 3}  // hidden = not shown unless show_all_done
  ],
  "pick": [ {"repo": "owner/repo", "entries": [Entry]} ],   // scan order, never re-sorted; Entry.index = the # shown
  "notes": [ {"kind": "UNCLONED|STALE|UNKNOWN", "key": "owner/repo#12"} ],
  "activity": [ {"at": 1732530000.0, "kind": "report", "key": "repo#12", "detail": "ready: tests pass"} ],  // last 6, no ticks, newest first
  "kitchen": [ {"at": 1732530000.0, "kind": "report", "mood": "happy", "text": "ready repo#12: …", "good": true} ], // last 20, takoyaki feed.ts mapping
  "global_actions": [Action]                        // refresh, pause|resume, investigate, toggle_done, prompter
}
```

Entry:
```jsonc
{
  "key": "owner/repo#12", "label": "repo#12" /* "repo#12 +2" for stacks */, "index": 3 /* pick rows only */,
  "kind": "WORKING", "section": "running", "title": "…", "draft": false, "url": "https://…",
  "checks": "pass|fail|pending|none", "agent": "running|waiting|idle|stopped|error|null",
  "rounds": 1, "max_rounds": 3, "quiet_s": 600, "stalled": false, "needs": false, "why": "ready to merge",
  "note": "…", "pick_kind": "issue|review only|adopt PR|your PR",
  "session": "sp…|w…|null", "backend": "hc|herdr|null", "pane": "t7|null", "path": "/…|null",
  "branch": "…", "pr": 12, "stack": 1, "open": true, "parked": false, "tracked": true,
  "actions": [Action]                               // exactly the TUI's allowed actions for this row
}
```

Action:
```jsonc
{"id": "remove", "key": "Delete", "label": "remove",
 "confirm": "⚠ its agent is working -- remove repo#12? (workspace and worktree deleted, untracked)" /* null = no confirm */,
 "args": ["repo", "question", "read_only"] /* investigate only */}
```
Row action ids (TUI key): `focus` (Enter), `peek` (v), `shell` (t), `browser` (o), `go` (g), `no` (n), `grant` (R),
`rereview` (e), `ack` (x), `detach` (z), `park` / `unpark` (d), `remove` (Del).
Global ids: `refresh` (r), `pause` / `resume` (P), `investigate` (i), `prompter` (a). `toggle_done` (D) and
`fold_all` (C), folding and selection are mod-side only (the mod passes `--show-all-done` state to nothing: Done
filtering uses `hidden`/`open` fields).

## Actions: `dashboard.sh --action <id> [key] [--arg name=value …]`

Runs the same code path as the TUI key (refusals, messages, wind-down rules). Prints one JSON line:
`{"ok": true, "message": "queued for the orchestrator: go …"}`.
`go` past wind-down without `--arg confirmed=1` returns `{"ok": false, "kitchen": true, "message": "🍳 The kitchen is closed (past 16:00)"}`;
the mod shows the kitchen-closed dialog and re-sends with `confirmed=1`. Same for `investigate`.
`refresh` kicks the headless daemon (it must start a GitHub refresh within a second).
Focus/peek/shell on hc rows may be done by the mod directly with `run()` using `session`/`pane`/`path`, but
`--action` must also work for them (and is the only way for herdr rows).

## Speech and chat (scan.py)

Both agents are started by open-gui.sh with `claude --session-id <uuid>` and labelled
`octopilot.session=<uuid>`; the transcript is `~/.claude/projects/*/<uuid>.jsonl`.
A `/clear` starts a new transcript and leaves the label stale: when the labelled
file is gone, the newest transcript of the terminal's folder that is no older
than the terminal is used (no SessionStart hook; the plugin's hooks are takoyaki
modules). The chat reports the session it read, so the mod sees the change.

- `scan.sh speech --json` → `{"agent": "hc:t7", "terminal": "t7", "status": "working|blocked|idle|done|offline",
  "paused": false, "text": "<last orchestrator assistant message, markdown>", "at": "<ISO>", "seq": 41}`
  (`seq` is a CRC-32 of the message id and text: it changes whenever the text does).
- `scan.sh chat --json [--after <id>] [--limit 50]` → `{"terminal": "t8", "session": "<uuid>", "status": "…",
  "blocked": {"kind": "permission|question|auth", "msg": "…"} | null, "reset": false,
  "messages": [{"id": "<transcript uuid>", "role": "user|assistant", "text": "markdown", "at": "<ISO>", "tools": ["Bash: $A status"]}]}`.
  Messages are what a person typed (user), and assistant turns: text blocks joined, tool calls in `tools`.
  Harness entries (tool results, meta, command output, notifications, compaction summaries) are not messages;
  `<hc …>…</hc>` is shown unwrapped; an image alone reads `[image]`.
  - Without `--after`: the newest `--limit` messages.
  - With `--after <id>`: the anchor message first, then up to `limit` newer ones, so the mod updates by id.
    The anchor is included even when nothing follows it (an assistant turn still being written keeps its id).
  - An anchor that is not in the transcript (a new session after `/clear`): the newest `limit`, with `"reset": true`.
  - Only the last 5 MB of a transcript is parsed; an older anchor is found by streaming the file.
- `scan.sh chat-send <text…>` → types it into the prompter (`hc send … -- <text>`), `{"ok": true}`.
  Exit 4 (`{"ok": false, "error": "agent_blocked"}`) when the prompter is blocked on a prompt; exit 3 when none runs.
- `scan.sh chat-keys <keys…>` → `hc keys` to the prompter, only while it is blocked (answering permission prompts:
  `1`, `2`, `esc`). Exit 4 `{"ok": false, "error": "prompter is not blocked"}` otherwise; exit 3 when none runs.
- `--json` is accepted; the output is always JSON. Under the TUI backend, or with nothing running, speech and chat
  report `"status": "offline"` and no text or messages.
