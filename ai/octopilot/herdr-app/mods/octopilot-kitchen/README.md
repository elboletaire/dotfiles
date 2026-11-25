# octopilot-kitchen

The takoyaki kitchen, as a pane or a floating block: the octopus chef (white hachimaki, pick in one
tentacle) behind a cast-iron pan with one takoyaki per tracked item, flames under it, a
shelf of served boats, and a speech bubble with the orchestrator's last message and the
kitchen log. It is the GUI version of the band `plugin/hooks/scene.ts` draws in the
orchestrator's session.

## As a pane

```js
run("pane.split", { pane, direction: "down", mod: "octopilot-kitchen", props: {} });
```

The kitchen fills its pane, wide and short (about 950x300 under the prompter's chat): the
scene on the right, scaled to the pane's height, and the bubble in the width that is left,
with as many log lines as fit (up to 12) under at least three lines of the message. When
the bubble would get under 250 px, the scene shrinks to leave it that; in a pane too
narrow for both (under about 500 px) the scene stands alone. A pane has no fold button and
ignores `folded`: herdr's pane header closes and zooms it. `layout.js` works the sizes out.

## Floating in a layout

```json
"floating": [ { "id": "kitchen", "content": { "mod": "octopilot-kitchen" }, "edge": "right", "align": "end" } ]
```

Drag it to any edge or corner. On a side edge the bubble sits over the scene; on the top
or bottom edge it sits to its left. Either way its tail points at the chef.

- `–` on the counter folds the bubble away and leaves the kitchen; `+` brings it back.

Either way:

- Click the chef: peek the orchestrator's terminal (`terminal.peek`).
- Click the message: the whole text in a dialog (the same mod, `full` props).

Props, all optional: `dir` (the octopilot code, default `~/.dotfiles/ai/octopilot`) and
`state_dir` (default `~/.local/state/octopilot`), each falling back to
`shared("octopilot.dir")` / `shared("octopilot.state_dir")`; `folded: true` to start folded
(floating only). `mod.json` is `"place": "none"`: the mod shows only where a layout floats
it or a `pane.split` puts it, so the same folder serves both.

## What it reads

- `$STATE_DIR/view.json`, watched, and re-read every 2 s as a fallback: `pan` (holes,
  balls, shelf, the chef's mood, `busy`, `paused`), `kitchen` (the log, and the newest
  event's burst) and `header`. A `generated_at` older than 15 s is an offline kitchen:
  dimmed, flames out, the chef dozing.
- `$DIR/scan.sh speech --json` for the bubble's message, status and terminal (not while
  folded), run through
  `env` with `OCTOPILOT_BACKEND=hc`, `OCTOPILOT_DIR` and, when a state folder was set,
  `OCTOPILOT_STATE_DIR`.

| On the pan | Drawn as |
|---|---|
| `raw` | a pool of batter with octopus and spring onion in it |
| `cooking` | a ball browning with `heat`, in five steps, steaming |
| `ready` | sauce, mayo and bonito flakes, in a warm pulsing glow |
| `capped` | the same with a red flag and a faster red glow |
| `burnt` | charred, cracks glowing, smoking |
| `stalled` | cold and frosted, no steam |

The focused ball has a ring and the chef's pick over it (the batter jug while he pours);
while the orchestrator is busy the pick walks along the pan. Flames roar while `busy`
and drop to a pilot light otherwise, paused too; they only go out when offline. Paused,
the chef sleeps, but an event's mood still shows for its time. Chef moods: `idle`, `busy`,
`flip`, `pour`, `happy`, `serve`, `worried`, `sad`, `surprised`, `sleep`, `doze`.

## The art

`python3 art/make.py` draws every piece as SVG (`art/svg/`, not kept in git), renders
`art/png/*.png` at 2x (rsvg-convert, else inkscape or magick) and writes `atlas.js`, the
place of each piece in the 360x220 scene. `--preview [mood...]` renders the composed
scene to `art/svg/preview-<mood>.png` to judge it without the app.

`main.js` stacks the pieces and animates them natively (`loop`): no timer redraws the
window, except a blink every few seconds and the pick's walk every 1.2 s while busy.

## Testing without the backend

`props().fixture` reads view.json from a file instead, and stops its clock at the
fixture's `generated_at` (or `fixture_now`, an epoch) so moods and bursts stay on show;
`props().fixture_speech` reads the speech JSON from a file. Without `fixture_speech` a
fixture kitchen has no bubble text. `../../fixtures/kitchen-view.json` has every ball
state, a focus, a shelf and a live burst; `kitchen-view-paused.json` the paused kitchen
with a stalled ball on an 8-hole pan.

`kitchen.js` (what to show, from view.json), `layout.js` (the pane's sizes) and `clip.js`
(the bubble's cut) are pure and have node tests: `node --test test/*.mjs`. `herdr-app check` runs without polling.
