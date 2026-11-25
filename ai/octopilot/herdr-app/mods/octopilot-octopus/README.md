# octopilot-octopus

The messenger as a reluctant octopus: a floating window with the octopus and a
speech bubble holding the orchestrator's last message (`scan.sh speech --json`),
plus the kitchen's last lines and pan count from `$STATE_DIR/view.json`.

- Click the octopus: peek the messenger's terminal (`terminal.peek`).
- Click the bubble: the whole message in a larger dialog (the same mod, `full` props).
- `–` folds the bubble to the octopus alone (`▸` brings it back), `✕` closes the window.

## Opening it

The dashboard opens it as a window that remembers its place:

```js
openOverlay({ mod: "octopilot-octopus", kind: "window", frame: "none", key: "octopilot-octopus", keep: true })
```

Props, all optional: `dir` (the octopilot code dir, default `~/.dotfiles/ai/octopilot`),
`state_dir` (default `~/.local/state/octopilot`). Each falls back to
`shared("octopilot.dir")` / `shared("octopilot.state_dir")`, then the default.

## Poses

`idle` (breathes, sighs now and then), `talking` (a new message, for about 4 s),
`working`, `blocked` (needs you), `sleeping` (paused), `offline` (no messenger, with
the reason in the bubble), `happy`, `worried`, `sad`, `surprised` (kitchen moods, the
newest event for 5 s) and `doze` (no kitchen event for 10 minutes).
The art is `art/make.py`: `python3 art/make.py --png` rewrites `art/svg/` and renders
`art/png/<pose>-<n>-{160,320}.png` (inkscape, or magick without it).

## Testing without the backend

`props().fixture` reads the speech JSON from a file instead of running `scan.sh`, and
`props().state_dir` reads `view.json` from a folder. `fixtures/*.json` has one speech
sample per status and `fixtures/state/view.json` a kitchen. Kitchen moods only show
while their event is fresh, so set `at` to the current epoch to see them.

`herdr-app check` runs without polling (`checking()`).
