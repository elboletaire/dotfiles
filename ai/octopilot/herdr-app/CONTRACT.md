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
| `herdr-app/install.sh` | installer | symlinks mods into `~/.config/herdr-app/mods/`, adds the key binding |

## view.json (written atomically by `dashboard.sh --headless`, on change and at least every 5 s)

Mods treat a view whose `generated_at` is older than 15 s as stale (no headless dashboard running).

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
  "kitchen": [Log],                                 // last 20 events that have a line (heartbeats have none), oldest first
  "pan": Pan,
  "global_actions": [Action]                        // refresh, pause|resume, investigate, toggle_done, prompter
}
```

Log (one kitchen line, takoyaki's feed.ts `react()`):
```jsonc
{"at": 1732530000.0, "kind": "report", "mood": "happy", "text": "ready repo#12: …", "good": true,
 "key": "owner/repo#12" /* null when the kind has no item */, "ms": 4000 /* how long the mood lasts */,
 "burst": "sparkle" /* steam|batter|sparkle|smoke|bang|heart|zzz|ink|null */}
```

Pan (takoyaki's pan and chef, from feed.ts `readKitchen()` and register.tsx `frame()`/`resting()`):
```jsonc
{
  "holes": 6,                                       // header max_active
  "paused": false, "busy": false,                   // busy = the orchestrator's agent is running
  "balls": [{"key": "owner/repo#12", "label": "repo#12",
             "state": "raw|cooking|ready|capped|burnt|stalled",
             "heat": 0.4,                           // cooking age / 25 min, capped at 1 (feed.ts browns them)
             "focus": true}],                       // the newest event's item, if it is on the pan (at most one)
                                                    // one per tracked item not DONE, oldest first, at most holes
  "shelf": [{"key": "owner/repo#7", "label": "repo#7"}],   // DONE items, newest last, at most 8 (the newest 8)
  "chef": {"mood": "happy", "since": 1732530000.0,  // the transient mood, else the rest mood
           "ms": 4000,                              // the transient mood's duration; 0 when resting
           "resting": "sleep|busy|doze|idle"}       // paused, busy, idle for 10 min (doze), else idle
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
 "confirm": "⚠ its agent is working -- press del again to remove owner/repo#12 (workspace and worktree deleted, untracked)" /* null = no confirm */,
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
`refresh` kicks the headless daemon (it must start a GitHub refresh within a second); with no daemon running
(view.json older than 15 s) it returns `{"ok": false, "message": "no headless dashboard running"}`.
Every call prints exactly one JSON line and exits 0, usage errors included. A row action on a row whose
action is refused (`v` with no live agent, `o` on an investigation) returns the TUI's refusal message, `ok: false`.
Focus/peek/shell on hc rows may be done by the mod directly with `run()` using `session`/`pane`/`path`, but
`--action` must also work for them (and is the only way for herdr rows).

## Speech and chat (scan.py)

Both agents are started by open-gui.sh with `claude --session-id <uuid>` and labelled
`octopilot.session=<uuid>`; the transcript is `~/.claude/projects/*/<uuid>.jsonl`.

- `scan.sh speech --json` → `{"agent": "hc:t7", "terminal": "t7", "status": "working|blocked|idle|done|offline",
  "paused": false, "text": "<last orchestrator assistant message, markdown>", "at": "<ISO>", "seq": 41}`
  (seq changes whenever text changes).
- `scan.sh chat --json [--after <id>] [--limit 50]` → `{"terminal": "t8", "status": "…", "blocked": {"kind": "permission|question|auth", "msg": "…"} | null,
  "messages": [{"id": "<transcript uuid>", "role": "user|assistant", "text": "markdown", "at": "<ISO>", "tools": ["Bash: $A status"]}]}`
  (user messages only those typed by a person, assistant text blocks joined; tool calls summarised in `tools`).
- `scan.sh chat-send <text…>` → types it into the prompter (`hc send`), `{"ok": true}`; exit 4 if blocked.
- `scan.sh chat-keys <keys…>` → `hc keys` to the prompter (answering permission prompts: `1`, `2`, `esc`).
