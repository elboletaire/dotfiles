# La Tecla, l'arxivera

A Claude Code mod: Tecla, a kawaii archivist who keeps a little library
corner above the prompt while the agents work on the family tree. She reads
along while the agent works, stamps every new source, searches the shelves
with a magnifier when the agent goes searching, frowns at contradictions,
cheers when validation passes, looks up when the agent needs you, and dozes
off when nothing happens. She speaks Catalan.

## How she looks

She is pixel art, drawn with the terminal's `Raster` element in half blocks
(each cell two stacked pixels): a chibi girl with chestnut hair and a stray
hair on top, reading glasses pushed up on her head, a pink star clip, big
violet eyes, blush, a lavender cardigan over a cream blouse, a pleated plum
skirt and a red book. The band is 12 rows tall: her 30 x 24 px sprite on the
left, a pixel bookshelf in the tree's branch colours (from `families.yml`)
beside her on wide bands, and to the right the header, what she says, the
last commits and the research counts:

```
[shelf] [Tecla]   📚 Tecla · 416 persones · 371 fonts · última F399
                  « He arxivat de la F392 a la F399! 📜 (8 fonts) »
                  22:15 Retiro F380 del prestatge… adeu 🍂
                  22:21 He arxivat de la F392 a la F399! 📜 (8 fonts)
                  22:32 Endreçant: dates D-M-AAAA de les biografies 🧹
                  📋 288 pendents · 🤔 64 incoherències · 📚 121 per revisar
```

| Pose | Shown when | Frames |
| --- | --- | --- |
| idle | nothing in particular | closed book, blinks every few seconds (now and then twice) |
| reading | the agent works, reads a source or a person | open book, blinks, turns a page |
| stamping | a new source or person, a commit, the agent writes one | rubber stamp up, down on the page with a thud, the red mark left |
| ladder | WebSearch, WebFetch, a subagent | a magnifier held up, eyes up at the shelves |
| puzzled | a contradiction, a failed validation, an error | eyes aside, a wobbly mouth, a bobbing `?` |
| happy | validation passed, a review, an item done | ^^ eyes, closed book with its gold bookmark, sparkles |
| sleepy | 8 minutes without activity | closed eyes, drifting `z`s |
| lookup | the agent needs you (permission, a question) | eyes on you, an open mouth, a bobbing `!` |

Sizes, by what the band has (`maxRows`, `bodyColumns`):

- 12 rows and at least 56 columns: the full sprite (30 x 12 cells); from 87
  columns the shelf (10 cells) joins her;
- 8 rows and at least 46 columns: a mini Tecla (20 x 16 px, 8 rows), the
  same girl in fewer pixels, with the latest log line;
- less, or on the desktop: one kaomoji line, `(ᵕ‿ᵕ)📖 Llegint la F119… 📖`.

She is animated with `$.ui.blit`: a frame tick every 125 ms advances the
pose's timeline and repaints the sprite's cells in place only when the frame
changed, so an idle Tecla repaints a couple of times every few seconds (a
blink) and the band itself is redrawn only when what she says or the
counts change.

## Where she shows up

Only in sessions whose working directory is inside the tree or one of its
worktrees (`<tree>/.worktrees/<name>`); she follows that checkout. Anywhere
else the mod does nothing: no band, no `/tecla` command, no reads. The check
runs at session start and again whenever the session's directory changes.

The tree is, in order:

1. `ARXIU_TREE`, if set;
2. `[arbre].path` in `ARXIU_CONFIG`, or in `~/.dotfiles/ai/arxiu/config.toml`;
3. `~/src/arbre`.

## Orchestrator or research session

The tree's agents run in herdr, and each one gets `ARXIU_ROLE` in its pane's
environment. Tecla reads it at session start:

- `orchestrator`: the full Tecla described here, with the investigation
  tracker below;
- `research` (or any other value): a quiet mini Tecla, her 8-row sprite (or
  the kaomoji line when the band is smaller), `🔎 investigació` in her header,
  no greeting and no small talk. She still reacts to her own session's work,
  commits and research files.

With no `ARXIU_ROLE`, inside herdr (`HERDR_ENV=1`) she finds her own agent in
`herdr agent list` by `HERDR_PANE_ID`: the one named `[arbre].orchestrator_agent`
(`arbre`) is the orchestrator, any other the research version. Until herdr
lists her agent she stays quiet and asks again on each poll (two minutes at
most, then she settles for research). A plain session outside herdr keeps the
full Tecla, with nothing to track.

## The investigation tracker

The orchestrator, inside herdr only, runs `herdr agent list` every 4 seconds
(read only: she never prompts an agent) and follows the agents whose `cwd` is
inside the tree or its worktrees, her own pane left out. The first poll takes
what is running as it is, silently; after that:

| The agent… | She… |
| --- | --- |
| appears | stamps: «Comença una investigació: investigacio 🔎» |
| works | glances at it now and then (reading, no word) while she is idle |
| is blocked, waiting on you | looks up, «investigacio et necessita, Òscar! 🙋», and keeps looking up until no investigation is blocked |
| goes from working or blocked to done or idle | happy: «investigacio ha acabat ✨», with the subject of its last commit since it started working when there is one (`git log -1 --since`) |
| disappears | a soft goodbye in the log: «investigacio plega. Fins aviat! 👋» |

Her band lists them under what she says, a glyph each: `◐` working, `⏸`
waiting on you, `✓` done, `○` idle.

```
[shelf] [Tecla]   📚 Tecla · 416 persones · 371 fonts · última F399
                  « investigacio et necessita, Òscar! 🙋 »
                  🔎 investigacio ⏸ · cosins ◐
                  22:15 Comença una investigació: cosins 🔎
                  ...
```

herdr missing, its server not running or any answer that is not its JSON
means nothing tracked and nothing said.

## What she reacts to

Everything is read straight from the tree, read-only and throttled: one
`stat` of the git reflog and of the three research files every 5 seconds, a
read or a `git log` only when one of them changed. No Python, no model calls.

| Event | Where it comes from | She… |
| --- | --- | --- |
| New sources / people in a commit | `git log --name-status` since the last HEAD; added `<sources>/F*.md`, `<people>/*.md` | stamps: «He arxivat la F399! 📜», «Hola, Sinforosa Fernandez Diaz! Ja ets a l'arbre 🌱» |
| A source removed | deleted `<sources>/F*.md` | «Retiro F380 del prestatge… adeu 🍂» |
| Any other commit | its subject (`feat:`, `fix:`, `docs:`, `chore:`) | logs it |
| A contradiction appears | `- **` items per branch and kind in `incoherencias.md` | puzzled: «Hi ha una incoherència de dates a la branca Alonso i Espino…» |
| A contradiction or pending item goes | the same counts, in `incoherencias.md` and `pendientes.md` (done-search sections left out) | happy |
| A source reviewed | «**N documentos pendientes de revisar**» in `revision.md` | happy: «Una font revisada! En queden 120 ✧» |
| The agent reads / writes a source or a person | `tool.call` on Read, Write, Edit | reads along, stamps: «Llegint la F119… 📖», «Catalogant la F400… ✒» |
| The agent searches the web or sends a subagent | WebSearch, WebFetch, Agent | searches the shelves with a magnifier |
| `make validate` (or `validate.py`) | the Bash call and its result | happy if it passed, puzzled if not |
| A tool fails, a turn errors or is interrupted | `tool.call` result, `turn.complete` | puzzled |
| The agent needs you | permission / idle / elicitation notifications, AskUserQuestion | looks up: «Òscar, cal el teu permís 🙏» |
| Nothing for 8 minutes | | sleepy: «zZz… els lligalls fan tanta sonsoneta…» |
| Quiet for 3 minutes (orchestrator only) | the counts | small talk: «Els Eguiburu tenen 35 pendents… 📋» |

Commands, in the tree only: `/tecla` sends her for a coffee and back (hides
and shows the band), `/tecla demo` plays sample events.

## Enabling it

Like the takoyaki kitchen, she loads through `CLAUDE_CODE_PLUGIN_DIRS` in the
`env` block of `~/.claude/settings.json` (a path list, `:`-separated on
Linux and macOS). Add her folder next to the takoyaki one:

```json
"env": {
  "CLAUDE_CODE_PLUGIN_DIRS": "~/.dotfiles/ai/octopilot/plugin:~/.dotfiles/ai/arxiu/bibliotecaria"
}
```

Then start (or restart) a Claude Code session in `~/src/arbre` or one of its
worktrees. The variable is read at startup, so running sessions don't pick
it up. Since the variable is global, every new session loads the mod; the
scope check keeps her out of all of them but the tree's.

To try her in a single session without touching settings:

```sh
cd ~/src/arbre && claude --plugin-dir ~/.dotfiles/ai/arxiu/bibliotecaria
```

then `/tecla demo`.

## Developing

```sh
claude plugin validate ai/arxiu/bibliotecaria
claude plugin test ai/arxiu/bibliotecaria
```

Once the engine has loaded the mod it lays its types in
`.claude-plugin/types/` (git-ignored) and `tsc -p ai/arxiu/bibliotecaria`
type-checks it. Before that, type-check from a folder outside the mod with a
`tsconfig.json` like the one in the header of the engine's `claude-code.d.ts`,
its `include` naming that file and the mod's `hooks`, `types` and `tests`.

To look at her in a truecolor terminal, from the same maps the mod draws:

```sh
python3 ai/arxiu/bibliotecaria/tools/preview.py                  # every pose, full and mini
python3 ai/arxiu/bibliotecaria/tools/preview.py stamping         # one pose's frames
python3 ai/arxiu/bibliotecaria/tools/preview.py reading --anim   # play it (ctrl+c)
python3 ai/arxiu/bibliotecaria/tools/preview.py --anim --mini    # every pose, the mini size
python3 ai/arxiu/bibliotecaria/tools/preview.py --frames         # every frame by name
```

- `hooks/art.ts`: the pixel art: palette, every frame of both sizes as a
  character map (one letter per pixel, `.` transparent; a frame may be
  another with some rows replaced), and each pose's timeline. The object is
  strict JSON so `tools/preview.py` reads it as is.
- `hooks/sprite.ts`: maps to Raster cells (pairs of rows to half blocks,
  little-endian u32 triplets in base64), the timelines, the pixel shelf, the
  kaomoji.
- `hooks/register.tsx`: the hooks: scope, polling, reactions, the band, the
  frame ticks and blits.
- `hooks/tree.ts`: pure readings of the tree: config, scope, `families.yml`, research files, `git log`.
- `hooks/herdr.ts`: pure readings for the role and the tracker: `herdr
  agent list`'s JSON, the agents in the tree, what changed between polls, the
  band's line.
- `hooks/voice.ts`: what she says and which pose she takes for each event.
- `types/index.d.ts`: the `$.state` contract.
- `tools/preview.py`: the preview above (stdlib only).
