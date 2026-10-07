# Taller

Every coding project the user works on, on one board, one key away from
picking it up again: the git repositories under `[taller].roots` plus `extra`
(minus `hide`), and any folder where a herdr agent runs, each with
its uncommitted and unpushed work, its worktrees, its agents and the last
conversation held there.

It lives in herdr: the **Taller** workspace is the board alone, and the
board acts through herdr -- it goes to a project's agent, or brings the
project's last conversation back as a named herdr agent.

```
╭─ 🛠  Taller ────────────────────────────────────────────╮╭─ .dotfiles ───────────────────────────────────╮
│ 🔴 1  🟡 1  🗂  9  💤 11   ⚠ 3 projectes sense còpia     ││ ~/.dotfiles                                   │
│                                                         ││ remot github:elboletaire/dotfiles  main       │
│    🔴        Et necessita (1)                           ││                                               │
│    ✗         dsp-blueprint-editor   main      ✎1     2w ││ Agents                                        │
│    🟡        Treballant (1)                             ││   ○ dotfiles  claude · inactiu                │
│    ○◐○○○     arbre                  main         ⑂2 12m ││                                               │
│    🗂         Aparcats (9)                               ││ Última conversa  claude · fa 13m              │
│ ▶  ○         .dotfiles              main      ✎10   13m ││   «Octopilot dashboard in herdr»              │
│    ○         photo-restore          main      ⚠      1h ││   tu    commit and push everything when …     │
│    ○         planets                master    ✎6 ⑂1  1d ││   agent Will do. When the agent finishes …    │
│    💤        Adormits (11)                              ││ Commits                                       │
│              machine-learning, …    d desplega          ││   2cd02c3 fix(arxiu): split the workspace …   │
╰─────────────────────────────────────────────────────────╯╰───────────────────────────────────────────────╯
 ↑↓ mou  ⏎ reprèn a herdr  n agent nou  w worktree  t terminal  o web  d adormits  / filtra  u refresca  q surt
```

## Run it

```sh
~/.dotfiles/ai/taller/taller.sh
```

It needs `uv` (which provides `rich`) and `python3` >= 3.11. Settings are in
`config.toml` next to it (or `$TALLER_CONFIG`): the roots, extra folders,
hidden ones, `dormant_days`, `agent_args` (extra claude arguments for the
agents it starts, e.g. `["--model", "haiku"]`) and the refresh periods.

- `taller.sh --once` prints one frame and exits (`COLUMNS`/`LINES` set the
  size); `--keys '<keys>'` replays keys first, e.g. `--keys 'jj\r'`.
- `TALLER_DRY_RUN=1` makes every action (focusing, starting agents, the
  worktree, popups, the browser; `herdr/open.sh` too) say what it would run
  instead. Read-only calls (git status/log, `herdr agent list`) still run.
- `python3 taller.py [--json]` shows what the board collects.

## The board

Four sections, a project in the first that applies:

- **🔴 Et necessita** -- one of its agents is waiting on you (blocked on a
  question or an approval), errored, or finished without you having looked
  (herdr's `done`).
- **🟡 Treballant** -- an agent is working.
- **🗂 Aparcats** -- the rest, most recently touched first.
- **💤 Adormits** -- nothing touched (commits on any branch, conversations)
  for `dormant_days` and no live agent: one line until `d`.

A row: one glyph per agent (◐ working, ⏸ waiting, ✓ done, ✗ error, ○ idle,
■ stopped), the name, the branch, `✎N`
uncommitted files (worktrees included), `↑N` unpushed commits, `⚠` no remote
at all, `⑂N` worktrees and the last touch. The header counts the sections and
warns about the projects with no copy elsewhere (no remote, or unpushed).

The detail: path and remote (or the lack of one), the agents and their state,
the last exchange (your message, the agent's reply, the session's title), the
last commits, the worktrees and the changed files. Commits and changes are
read for the selected project only, in the background, and kept until its
HEAD, index or dirty count change. Agents refresh every `[ui].agents_secs`,
git every `[ui].git_secs` and right after an action.

| Key | |
|---|---|
| `↑↓` `j/k` `PgUp/PgDn` | move |
| `⏎` | its herdr agent (one waiting on you first): focus it. None: a second `⏎` opens the project in herdr -- a new workspace named after it (a tab, if it has one) running its last conversation again (`claude/pi --continue` where it ran) as an agent named after the project; a new claude when there is none. |
| `n` | a fresh claude in the project (second `n` confirms), in a new tab of its herdr workspace or a new workspace |
| `w` | a new worktree: asks the branch, then (second `w`) `git fetch`, `git worktree add -b <branch> <repo>/.worktrees/<branch, / as ->` off the current branch, `herdr worktree open` titled after it and a claude named after it. The main checkout is never touched. |
| `t` | a shell in the project (herdr popup) |
| `g` | `git log --graph` and `git status` (herdr popup, `q` closes) |
| `o` | the remote in the browser (`wslview`, `explorer.exe`, `xdg-open`) |
| `d` | show/hide the dormant projects |
| `/` | filter by name (`Esc` clears) |
| `u` | refresh now |
| `q` | quit |

Agents it starts are always named (`[a-z][a-z0-9_-]{0,31}`, from the project
or branch, `-2`... when taken), so herdr lists them by name. Claude's "trust
this folder?" is answered only for the project's own folder; any other dialog
stays on screen and the board shows its last lines.

## Inside herdr

`herdr/` is a herdr plugin: the **Taller** workspace (`open`), the board as an
overlay over anything (`peek`) and the popups the board opens (`shell`,
`git`). `scripts/install.sh` links it (`link_herdr_plugin`); by hand:

```sh
herdr plugin link ~/.dotfiles/ai/taller/herdr
```

and bind its actions in `~/.config/herdr/config.toml`. `prefix+o` is herdr's
`open_notification_target` and `prefix+t` / `prefix+shift+t` are taken (the
shell popup, `rename_tab`), so:

```toml
# Taller (~/.dotfiles/ai/taller/herdr)
[[keys.command]]
key = "prefix+shift+o"          # build or focus the Taller workspace
type = "plugin_action"
command = "elboletaire.taller.open"

[[keys.command]]
key = "prefix+i"                # the board over whatever you are doing
type = "plugin_action"
command = "elboletaire.taller.peek"
```

(`o` for obrador; neither is a herdr default nor used by Octopilot or Arxiu.)

## Tests

```sh
python3 -m unittest discover -s ai/taller/tests                  # stdlib only
uv run --with rich python -m unittest discover -s ai/taller/tests  # + the board
```

They build throwaway repos, transcripts and a fake `herdr` executable
under a temp HOME (with its own `.config/git/ignore`), never the real ones.
