# Arxiu

The genealogy research dashboard for `[arbre].path`, a
[family-tree-kit](https://github.com/elboletaire/family-tree-kit) tree, wired
to the tree's agents: pick a family, a branch, a person or a pending item and
one key puts a prompt about it in front of the orchestrator, or sends it to a
research agent in the background.

It lives in herdr: the **Arxiu** workspace is the board on top and the
orchestrator below it -- a claude session in the tree, with the librarian mod
(Tecla, `bibliotecaria/`) always on screen. herdr's `prefix+j` / `prefix+k`
move between the two; inside the board, `Tab` moves between the list and the
right column.

```
┌ 🌳 Arxiu ──────────────────────────────────────────────┬ Detall · persona ──────────────┐
│ 416 persones · 371 fonts (F399) · 304 pendents · …     │ José Eguiburu Camio c.1842–1896│
│ Aquesta setmana: +161 fonts (F211–F399) · validació ✓  │ ■ 16 fonts · 6 pendents        │
│    Família · branca           Pend Docs Ids Incoh Rev  │ ┌─ Ignacio Eguiburu †c.1874    │
│    ▾ Familia de Margarita      176   45 104    57  79  │ José Eguiburu Camio            │
│      ▸ ●● Alonso y Espino       43   13  22    16  10  │ └─ Juliana de Camio            │
│      ▾ ● Eguiburu               35   18  15    12  10  │ sex M · born c. 1842, …        │
│        ▾ persones (75)                                 │ …                              │
│ ▶        ● José Eguiburu Camio  c.1842–1896  ·6        │ ── Cua (2) ─────────────────── │
│        ▾ documents a aconseguir (18)                   │ ◐  2m investigar Eguiburu …    │
│          • Testamento de Trinidad Eguiburu …           │ ✓  1h entrevista a … · arbre   │
│ Agents  ○ arbre orquestrador  ◐ investigacio recerca   │                                │
└────────────────────────────────────────────────────────┴────────────────────────────────┘
 ↑↓ mou  r investiga la persona  e preguntes d'entrevista → arbre  R/E → investigacio  …
┌ arbre ───────────────────────────────────────────────────────────────────────────────────┐
│ claude (ARXIU_ROLE=orchestrator), Tecla's band                                           │
│ ❯ Fes servir la skill family-interview per preparar una entrevista a José Eguiburu …     │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

## Run it

```sh
~/.dotfiles/ai/arxiu/arxiu.sh
```

It needs `uv` (which provides `rich`) and `python3` >= 3.11; nothing else to
install. Settings are in `config.toml` next to it (or `$ARXIU_CONFIG`).

- `arxiu.sh --once` prints one frame and exits (`COLUMNS`/`LINES` set the
  size); `--keys '<keys>'` replays keys first, e.g. `--keys '\r\x1b[B'`.
- `ARXIU_DRY_RUN=1` makes every action (prefilling and prompting agents,
  starting them, focusing, popups; `herdr/open.sh` too) say what it would run
  instead of running it. Read-only `herdr` calls (listing and getting agents
  and workspaces) still run, and nothing goes into the queue.
- `python3 arbre_data.py ~/src/arbre --summary` shows what the list reads;
  `python3 agents.py` lists the tree's herdr agents.

## Inside herdr

`herdr/` is a herdr plugin: the **Arxiu** workspace, the board as an overlay
over anything, and the popups the board opens (`shell`). `scripts/install.sh`
links it (`link_herdr_plugin`); by hand:

```sh
herdr plugin link ~/.dotfiles/ai/arxiu/herdr
```

and bind its actions in `~/.config/herdr/config.toml`. `prefix+a`,
`prefix+shift+a` (octopilot) and `prefix+t` (shell popup) are taken, so:

```toml
# Arxiu (~/.dotfiles/ai/arxiu/herdr)
[[keys.command]]
key = "prefix+shift+f"          # build or focus the Arxiu workspace
type = "plugin_action"
command = "elboletaire.arxiu.open"

[[keys.command]]
key = "prefix+f"                # the board over whatever you are doing
type = "plugin_action"
command = "elboletaire.arxiu.peek"
```

(`f` for família; neither is a herdr default.)

**The Arxiu workspace** (`prefix+shift+f`, `herdr/open.sh`), in the tree's
folder: the board on top (half the height), below it the
orchestrator, a claude agent named `[arbre].orchestrator_agent` (`arbre`),
with `ARXIU_ROLE=orchestrator` in its pane's environment, which Tecla reads.
The board has the focus. If the workspace exists it is focused; if an agent
with the orchestrator's name already runs anywhere, that agent is focused
instead of starting a second one. `[arbre].agent_args` adds claude arguments
to the agents Arxiu starts (e.g. `["--model", "haiku"]`). An `ARXIU_CONFIG`
(or `ARXIU_QUEUE`) given to `open.sh` reaches the board too.

## The list

Families (open), their branches -- the `groups` of `families.yml`: `Alonso y
Espino` covers the `alonso` and `espino` branches -- and, when you open a
branch, its people (a `persones (N)` folder, by generation from the branch's
founder: `people.branch_people`) and its pending items under their category.
A heading no group matches (`Familia reciente`, `Varias ramas`, `Otras
familias`, `General`) gets a row of its own instead of being dropped.

Families and branches show `Pend` (pending items), `Docs` (documents to
get), `Ids` (people to identify), `Incoh` (contradictions), `Rev` (AI sources
in `revision.md`) and the last research, flagged ⚠ after 3 weeks. A person
shows their years and `·N` open items about them.

The right column is `panel.py` for the selection (a branch's or family's
founder pedigree and completeness, a person's pedigree and lookup card, the
people and sources an item mentions) with the queue at the bottom. Without
`panel.py` (or `people.py`) the board still works: a placeholder there, and
the people read straight from the notes.

## Keys

The footer changes with the selection. Lowercase **prefills**: the prompt is
typed into the orchestrator's input, unsent, and the orchestrator gets the
focus -- read it, edit it, press Enter there. Uppercase **sends** the same
prompt to the background research agent after a second press.

| Selection | Key | Prompt (Catalan, one line) |
|---|---|---|
| family | `r` / `R` | research the family with `[arbre].research_skill`, open items first, `lookup.py rama/<key>…` of its branches |
| branch | `r` / `R` | research that branch (group), its open items first, `lookup.py rama/<key>…` |
| person | `r` / `R` | research this person only (full name and slug, branch, family), `lookup.py <slug>` |
| person | `e` / `E` | `family-interview` (`[arbre].interview_skill`): the numbered question list for this person as the relative being interviewed, nothing recorded yet |
| item | `i` / `I` | research this pending item (branch, category, text), `lookup.py` of the people and sources it mentions |

| Key | Does |
|---|---|
| `↑↓` / `jk`, `PgUp/PgDn` | move (in the right column: scroll it) |
| `⏎` / space, `→` / `←` | open / close a family, branch, the people or a category; `←` on a leaf goes to its parent |
| `Esc` | back out to the branch, closed |
| `Tab` | the list or the right column |
| `l` | `uv run scripts/lookup.py <query>` in the tree, in an overlay (empty = the selection: a slug, a source id, `rama/<key>…`) |
| `v` | validate the tree now |
| `w` | open the built site (`build/web/index.html`); never builds it |
| `a` | go to the research agent |
| `t` | shell in the tree (a popup) |
| `u` | refresh now |
| `q` | quit (or close the overlay) |

**Prefill** (lowercase) only types when the orchestrator is idle or done.
Working, or blocked on a question or an approval, it gets nothing and the
board says so (the uppercase key sends it to the research agent instead). It
runs `herdr pane send-text <pane> <prompt>` -- literal text, no Enter -- and
then `herdr agent focus <name>`. Prompts are one line.

**Send** (uppercase) shows the prompt and what will happen: `prem R de nou
per enviar a investigacio`, or `… per engegar investigacio (pestanya nova a
Arxiu) i enviar-li` when no herdr agent called `[arbre].research_agent` is
running. The second press:

1. asks herdr for that agent (`herdr agent get`); if it is `blocked` (an
   approval or a question waiting for you) nothing is sent, the board says so;
2. if it is not running: a new tab in the Arxiu workspace (or a workspace of
   its own named after it, if there is no Arxiu one), in the tree, with
   `ARXIU_ROLE=research`, and `herdr agent start <name> --kind claude` there,
   waiting until claude is ready. The only dialog answered for you is
   claude's "trust this folder?" for the tree; anything else is left on
   screen and the board shows its last lines;
3. `herdr agent prompt <name> <prompt>` (a working agent queues it).

The footer shows the progress (`⟳ engegant investigacio…`) while it runs.

## The queue

Every prefill and send that worked is appended to `~/.cache/arxiu/queue.json`
(`$ARXIU_QUEUE`; the newest 50): `{id, at, kind, target, label, agent, mode,
status}`. Every `[ui].agents_secs` the board follows herdr's agent states
into it: a prefill is `prefilled` (typed, waiting for your Enter), a send
`sent`; then `working`, `waiting` (blocked on you), `done`. `stopped`: the
agent is gone; `discarded`: a newer prefill replaced one never sent. Only the
newest open entry of an agent follows it while it works.

## What it reads

Everything comes from the tree's `families.yml`: its data folders (`paths`),
families, branches with their colours and founders, and the `groups` -- the
`###` headings of the research files. Nothing in Arxiu names a folder or a
branch, so it works for any tree made from the kit.

- Pending items are the top-level bullets of `pendientes.md`, wrapped lines
  and sub-lists included. A `####` category that logs searches already made
  ("… sin resultado, no repetir") is not pending work: it is counted apart.
- **Última recerca**: a person belongs to the branches of their
  `tags: [rama/<key>]` (untagged people to `other_branch`); a branch's files
  are its people and the sources they cite. The newest commit touching any of
  them is the row's last research -- skipping maintenance sweeps (a
  `chore:`/`style:`/`refactor:`/`docs:`… subject, or more than 80 data files
  in one commit). One `git log` over the data folders, cached until HEAD
  moves.
- Agents: the herdr agents working in the tree, with their state and role
  (orquestrador, recerca). Diari: the latest commits.

**Validation.** `make validate` runs `make references` first, which rewrites
`revision.md` and the generated sections of the notes (and `make folders`
creates folders): Arxiu never writes into the tree, so it runs only the
check, `uv run scripts/validate.py` (read-only, `PYTHONDONTWRITEBYTECODE=1`).
It runs in the background when the tree's notes, research files,
`families.yml` or `places.yml` changed since the last run (or on `v`), and the
result is cached in `~/.cache/arxiu/`. "(antiga)" marks a result older than
the tree.

**Refresh.** The tree is stat-polled every second and re-read when it or its
git HEAD changes (a reload with nothing new costs ~20 ms); the people with it.
Agents and the queue every `[ui].agents_secs`.

## Files

`board.py` (the TUI, rich through uv), `arbre_data.py` (the tree), `people.py`
(the person notes), `panel.py` (the right column), `agents.py` (herdr:
config, lookups, start, prompt, prefill), `actions.py` (the catalogue and
its prompts), `research_queue.py` (the queue). See `CONTRACT.md`. Taller, the
projects column that used to sit on the right, is parked in `ai/taller/`.

## Tests

```sh
uv run --with rich python -m unittest discover -s ~/.dotfiles/ai/arxiu/tests
```

Under bare `python3` the board and panel tests are skipped.
