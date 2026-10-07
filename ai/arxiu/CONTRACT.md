# Arxiu internal contract

Three parts are built in parallel; this is what they agree on. Keep it in
sync if an interface changes.

```
ai/arxiu/
  config.toml        shared config (see comments in it)
  CONTRACT.md        this file
  arxiu.sh           launcher: `uv run --script board.py "$@"`         [board]
  board.py           the TUI (PEP 723, rich)                            [board]
  arbre_data.py      parses a family-tree-kit tree, stdlib only         [board]
  taller.py          Taller project collector, stdlib only              [taller]
  herdr/             herdr plugin: "Arxiu" workspace + peek overlay     [board]
  bibliotecaria/     the librarian Claude Code mod                      [mod]
  tests/             unittest tests for arbre_data.py and taller.py
```

Python is stdlib-only except board.py (rich, through uv). Python >= 3.11
(tomllib). UI text is Catalan; code, comments and docs are English.

## config

`load_config(path=None) -> dict` lives in `taller.py` (board.py imports it):
reads `config.toml` next to the module (or `ARXIU_CONFIG` env), expands `~`
in every path, fills defaults for missing keys.

## taller.py

```python
collect(cfg: dict) -> list[Project]      # every project, including the arbre one
find_project(projects, path) -> Project | None
agent_actions: see below
```

`Project` is a plain dict:

```python
{
  "name": str,                 # folder name
  "path": str,                 # absolute, the repo root (not a worktree)
  "git": bool,
  "remote": str | None,        # "github:owner/repo", "gitlab:owner/repo", other host as-is, None = no remote
  "branch": str | None,
  "dirty": int,                # changed + untracked files in the main checkout
  "ahead": int | None,         # commits not on the upstream; None = no upstream
  "behind": int | None,
  "worktrees": [{"path": str, "branch": str | None, "dirty": int}],
  "last_touch": int | None,    # epoch: newest of last commit and last conversation
  "agents": [Agent],
  "last_exchange": {"user": str, "agent": str, "title": str | None, "at": int,
                    "tool": "claude" | "pi",
                    "path": str} | None,   # the folder it ran in (may be a worktree)
  "flags": [str],              # subset of: dirty, unpushed, no_remote, no_upstream, no_git, dormant, error
  "dormant": bool,
}
```

`Agent`:

```python
{
  "host": "herdr",
  "id": str,                   # herdr workspace id
  "name": str,                 # herdr agent name
  "tool": str,                 # claude, pi, ...
  "path": str,                 # its working directory (may be a worktree)
  "state": "working" | "waiting" | "done" | "idle" | "error" | "stopped" | "unknown",
  "pane": str | None,          # herdr pane id
}
```

Actions (each returns `(ok: bool, message: str)`; none of them run when
`ARXIU_DRY_RUN=1`, they return `(True, "dry-run: <command>")` instead):

```python
send(agent: Agent, text: str)            # herdr agent prompt
focus(agent: Agent)                      # herdr agent focus
attach_cmd(agent: Agent) -> list[str]    # argv to attach the agent in the foreground
resume_cmd(project: Project) -> list[str]  # ["env", "-C", <last_exchange path>, "claude"|"pi", "--continue"]
list_agents() -> list[Agent]             # agents alone (~0.2s), for refreshes between full collects
match_agents(projects, agents)           # attach a fresh agent list to the projects, in place
# herdr-native (see the last section); same (ok, message) and dry-run rules
prompt_research(cfg, text, status=None)  # prompt [arbre].research_agent, starting it first;
                                         # refuses when it is blocked; status(msg) reports progress
start_agent(name, role, cwd, root, agent_args=(), status=None)  # new tab of "Arxiu", ARXIU_ROLE=role
accept_trust(name, cwd, root) -> bool    # claude's folder-trust prompt, only for cwd inside root
open_in_herdr(project)                   # new workspace at the project running resume_cmd()
```

## arbre_data.py

```python
load(tree_path: str) -> Tree
```

`Tree` is a plain dict: totals (people, sources, last source id), families
and branches from `families.yml` (key, name, colour, family), per-branch
counts of pending items by category, contradictions and AI sources awaiting
review, per-branch last research (newest commit touching that branch's
people or sources), the items themselves (for the detail pane), the week's
progress from git, and the validation result (cached; the read-only
`scripts/validate.py` runs in the background only after the tree changes --
never `make validate`, which regenerates files first). The exact shape is in
`load()`'s docstring.

## The mod

`bibliotecaria/` reads the tree directly (git log, the research files); it
does not import Python. It only shows up in Claude Code sessions whose
working directory is inside `[arbre].path` (or a worktree of it).

## herdr-native tree

- Agents in the tree run in herdr only. The Arxiu workspace (`herdr/open.sh`)
  holds the orchestrator, a claude agent named `[arbre].orchestrator_agent`
  (`arbre`), and the board. `i` prompts the agent named
  `[arbre].research_agent` (`investigacio`); when it isn't running, the board
  starts it first in a new tab of the Arxiu workspace, in the tree's folder.
- Every agent the plugin or the board starts gets `ARXIU_ROLE` in its pane's
  environment: `orchestrator` or `research`. Tecla reads it: the full band
  with the investigation tracker for `orchestrator` (or when unset and the
  session's herdr agent is named `arbre`), a quiet mini version otherwise.
- Tecla tracks investigations from the orchestrator by polling
  `herdr agent list` (agents whose cwd is inside the tree): started,
  working, blocked (waiting on the user), finished.
- Taller opens things in herdr: a project with no agent opens in a new
  herdr workspace at its path with `claude --continue` / `pi --continue`.

## Round 3: genealogy-only workspace (supersedes the Taller parts above)

Taller moves, untouched, to `ai/taller/` (taller.py, its test, its config).
`ai/arxiu/` is the genealogy dashboard only and must not import taller.

New modules in `ai/arxiu/` (stdlib only unless noted):

- `agents.py` [core]: herdr helpers the board needs, extracted from what
  board/taller use today: `load_config()`, `herdr()`, agent lookup/start,
  `accept_trust()`, `prompt(agent, text)`, `prefill(agent, text)` (types the
  text into the agent's input without pressing Enter, then focuses its
  pane), `focus(agent)`, `research_status()`, `ARXIU_DRY_RUN` handling.
- `people.py` [panel]: `load(tree_path, tree) -> People`: every person note
  (slug, name, born/died if present, father, mother, parents_confidence,
  branches from `rama/` tags, sources count, research-note presence,
  pending items mentioning them) and helpers `pedigree(people, slug,
  depth=3)`, `branch_people(people, branch_key)`, `completeness(people,
  branch_key) -> dict`. Reads frontmatter with arbre_data's YAML-subset
  parser.
- `actions.py` [core]: the action catalogue: for a selection kind
  (`family`, `branch`, `person`, `item`) the keys, their Catalan labels and
  the prompt each builds (Catalan; names the skill to use:
  `[arbre].research_skill` for research, `family-interview` for
  interviews). Lowercase key = prefill the orchestrator's input and focus
  it; uppercase = send to the background research agent. Every action sent
  or prefilled is appended to the queue.
- `research_queue.py` [core] (not `queue.py`: board.py's folder is first on
  sys.path and would shadow the stdlib `queue`): `~/.cache/arxiu/queue.json`
  (`$ARXIU_QUEUE`; the newest 50): `{id, at, kind, target, label, agent,
  mode: prefill|send, status}`, `at` an epoch; status refreshed from herdr
  agent states: `prefilled` (typed, unsent) or `sent` -> `working` ->
  `waiting` -> `done`; also `stopped` (agent gone) and `discarded` (a newer
  prefill replaced an unsent one). `load()`, `append(...)`, `update(agents)`.
- `panel.py` [panel] (may import rich): `render(tree, people, selection,
  queue_entries, width, height) -> rich renderable` for the right column.

Selection (built by board.py, read by panel.py):

```python
{"kind": "family" | "branch" | "person" | "item",
 "family": str | None, "branch": str | None,     # families.yml keys
 "person": str | None,                           # person slug
 "item": dict | None,                            # arbre_data item
 # also, from board.py (optional for readers):
 "row": str | None,                              # arbre_data row id
 "branches": [str]}                              # the row's branch keys
```

A "branch" in the list is a row of arbre_data (a `groups` entry of
families.yml, which may cover several branches): `branch` is its first
branch key (for a person, the first of theirs the row covers), `branches`
all of them. The board frames the right column and passes its inner size to
`panel.render()`.

`agents.prefill(agent, text)`: refuses (False, reason) when the agent is
missing, `working` or `blocked`; else `herdr pane send-text <pane> <text as
one line>` (no Enter) then `herdr agent focus <name>`. `agents.list_agents(
strict=True)` returns None when herdr could not be asked.

Panel content: branch/family -> pedigree of the branch's founder (from
families.yml) with missing ancestors as `?`, and completeness bars;
person -> their pedigree + lookup card (`uv run --script scripts/lookup.py
<slug>` in the tree, cached per slug and HEAD); item -> lookup card of the
people/sources it mentions; always at the bottom -> the queue.

Workspace (`herdr/open.sh`): board on top, the orchestrator claude
(`ARXIU_ROLE=orchestrator`, Tecla) below, split down, 50/50.
