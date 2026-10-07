# Taller

Every coding project the user works on, on one board, one key away from
picking it up again: the git repositories under `[taller].roots` plus `extra`
(minus `hide`), and any folder where a herdr agent runs, each with
its uncommitted and unpushed work, its worktrees, its agents and the last
conversation held there.

It lives in herdr: the **Taller** workspace is a chat on the left (the
orchestrator, a claude that sees every project and session and acts on them
when asked) and the board as a column on the right. The board acts through
herdr -- it shows a project's agent in a popup, goes to it, or brings the
project's last conversation back as a named herdr agent. Run on its own or
as an overlay (`peek`), the board puts the detail beside the list, as below.

```
╭─ 📂 Projectes ──────────────────────────────────────────╮╭─ .dotfiles ───────────────────────────────────╮
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
 ↑↓ mou  ⏎ reprèn a herdr  n agent nou  w worktree  t terminal  o web  z adorm  d adormits  / filtra  u refresca  q surt
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
  for `dormant_days`, or put to sleep with `z`, and no live agent: one line
  until `d`. A worktree put to sleep on its own leaves its project's rows
  for this section, as `<project>/<folder>`.

A row: one glyph per agent (◐ working, ⏸ waiting, ✓ done, ✗ error, ○ idle,
■ stopped), the name, the branch, `✎N` uncommitted files, `↑N` unpushed
commits, `⚠` no remote at all, `⑂N` worktrees and the last touch. Each
worktree has a row of its own under its project (`├ <folder>` with its
branch, its agents, its uncommitted files and when its last conversation
was): the project's row counts its main checkout alone, while its section
counts every agent, a worktree's too. The header counts the sections and
warns about the projects with no copy elsewhere (no remote, or unpushed).

The detail, of the selected row (a worktree's is titled `<project> ⑂
<branch>`): path and remote (or the lack of one), the agents and their state,
the last exchange there (your message, the agent's reply, the session's
title), the last commits, the worktrees and the changed files. Commits and
changes are read for the selected folder only, in the background, and kept
until its HEAD, index or dirty count change. Agents refresh every `[ui].agents_secs`,
git every `[ui].git_secs` and right after an action.

| Key | |
|---|---|
| `↑↓` `j/k` `PgUp/PgDn` | move |
| `⏎` | on a project, its main checkout; on a worktree, that worktree. Its herdr agent (one waiting on you first): focus it. None: a second `⏎` opens the project in herdr -- a new workspace named after it (a tab, if it has one) running that folder's last conversation again (`claude/pi --continue`) as an agent named after the project (or the worktree's branch); a new claude when there is none. A worktree without a workspace opens with `herdr worktree open`, grouped under its repo's in herdr's sidebar. |
| `v` | its herdr agent (one waiting on you first) in a popup over the board, without leaving it; `ctrl+b q` closes it. With no session yet, its last conversation is resumed in the background first (as `⏎` would, without taking the focus or asking twice), then shown. |
| `n` | a fresh claude in the selected folder (second `n` confirms), in a new tab of its herdr workspace or a new workspace |
| `w` | a new worktree: asks the branch, then (second `w`) `git fetch`, `git worktree add -b <branch> <repo>/.worktrees/<branch, / as ->` off the current branch, `herdr worktree open` titled after it and a claude named after it. The main checkout is never touched. |
| `t` | a shell in the selected folder (herdr popup) |
| `g` | its `git log --graph` and `git status` (herdr popup, `q` closes) |
| `o` | the remote in the browser (`wslview`, `explorer.exe`, `xdg-open`) |
| `z` | put it to sleep (second `z` confirms): on a project, the main checkout with every worktree; on a worktree, that one alone. Closes its herdr workspaces (only its agents' panes, in a workspace other agents share; never the board's own), warns about working agents and uncommitted files (they stay), and lists the folder in `$XDG_STATE_HOME/taller/sleep.json` so it shows as dormant whatever its age. Anything done there afterwards -- a commit or a conversation, or an agent started (`⏎`, `n`, `v`) -- wakes it. On something asleep, `z` wakes it right away. |
| `x` | on a worktree only (a whole project is never removed from here): closes its herdr session and workspace (only its agents' panes, in a workspace other agents share or kept for another checkout), `git worktree remove` and `git branch -D` of its local branch. Second `x` confirms. When it has uncommitted files or commits on no remote, `x` only warns, saying what would be lost, and it takes `X` twice to force it (`git worktree remove --force`). |
| `d` | show/hide the dormant projects |
| `/` | filter by name (`Esc` clears) |
| `u` | refresh now |
| `q` | quit (press it, or `ctrl-c`, twice: the first press only asks) |

Agents it starts are always named (`[a-z][a-z0-9_-]{0,31}`, from the project
or branch, `-2`... when taken), so herdr lists them by name. Claude's "trust
this folder?" is answered only for the project's own folder; any other dialog
stays on screen and the board shows its last lines.

## Inside herdr

`herdr/` is a herdr plugin: the **Taller** workspace (`open`), the board as an
overlay over anything (`peek`) and the popups the board opens (`agent`,
`shell`, `git`).

```
╭ minion king ─────────────────────────╮╭ 📂 Projectes ──────────╮
│ the orchestrator: /taller:orchestra- ││ the list, no taller    │
│ tor, a claude in ~/src               ││ than its rows          │
│                                      │├ <project> ─────────────┤
│                                      ││ the selection's detail │
╰──────────────────────────────────────╯╰────────────────────────╯
```

`herdr/open.sh` builds it, in a tab called `TALLER`: the first pane
(`minion king`) runs the orchestrator
-- a claude named `[taller].orchestrator_agent` (`taller`) in the first of
`[taller].roots` (`~/src`; `~` if it's missing), with `agent_args`, its
"trust this folder?" for that folder answered -- continuing the newest claude
conversation held there (it already knows its role), or, with none, a new
one given `/taller:orchestrator`; it keeps 60% of the width, and the board runs beside
it with `TALLER_LAYOUT=column` (the keys between the list and the detail, always below it), its
pane unlabelled so herdr draws no "Taller" around its own sections, which
are title lines rather than boxes there (herdr's frame is enough). The
orchestrator running anywhere already is only focused, and so is an
existing Taller workspace: close it to get a new layout.
`TALLER_LABEL=<label>` and `TALLER_ORCH=<name>` build a second one, to try
changes without touching yours.

### The orchestrator

`plugin/` is a Claude Code plugin, `taller`, loaded through
`CLAUDE_CODE_PLUGIN_DIRS` (`ai/claude/settings.json`) like Octopilot's: its
skill `/taller:orchestrator` is the chat's role. It answers about every
project and session (what's waiting on you, what exists only on this
machine, what a session is on), and acts through `taller.py`'s subcommands,
the board's own actions, which never take your focus:

```sh
python3 taller.py sessions                       # every open herdr session
python3 taller.py show <project> [--worktree <branch>]
python3 taller.py resume <project> [--worktree <branch>]
python3 taller.py new <project> [--worktree <branch>] [--prompt <text>]
python3 taller.py worktree <project> <branch> [--prompt <text>]
python3 taller.py prompt <agent> <text>
```

It reads freely and starts or resumes sessions when asked, but asks first
before anything that publishes (`git push`, PRs), deletes (a worktree, a
branch, a session) or edits a project, and before writing into another
session (`prompt`, `--prompt`).

`scripts/install.sh` links the herdr plugin (`link_herdr_plugin`); by hand:

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
