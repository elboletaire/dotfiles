---
description: Turn this main-branch aoe session into an orchestrator that spawns worktree sessions into a sibling "worktrees" group
---

This aoe session is an **orchestrator**. It stays on the repository's main branch and does not do feature work itself — its job is to create and supervise worktree sessions, each on its own branch.

Every workspace you create lands in a **`worktrees` group sitting next to this session**, mirroring the `Manga Downloader` / `Manga Downloader/worktrees` layout. Resolve both values up front and keep them for the rest of the session:

```bash
PARENT="${AOE_INSTANCE_ID:-$(aoe session current --json | jq -r .id)}"
GROUP=$(aoe session show "$PARENT" --json | jq -r '.group // ""')
WORKTREES="${GROUP:+$GROUP/}worktrees"
```

Use the id, not `aoe session current -q` — that returns the *title*, and duplicate titles make `-P` ambiguous. If this session has no group, `$WORKTREES` is just `worktrees` at top level; mention that rather than inventing a group name.

## Always fetch first

Every workspace request starts with `git fetch origin`, no exceptions. Both flows depend on origin being current: tracking needs the remote ref to exist locally, and creating needs the base branch to be up to date.

## Creating a workspace

When I say **create** a branch (e.g. "create feat/user-auth"), it does not exist yet — it starts blank, off the freshly updated current branch, so I can begin something new:

```bash
git fetch origin
git pull
aoe add . -w <branch> -b --base-branch "$(git branch --show-current)" \
  -P "$PARENT" -t "<Human Readable Title>" -l
aoe group move "<Human Readable Title>" "$WORKTREES"
```

The `git pull` matters — the point is to branch off the *updated* current branch, not a stale local one.

## Tracking a workspace

When I say **track** a branch, it already exists on origin — do not create it. Same flow, but omit `-b` so aoe attaches to the existing branch:

```bash
git fetch origin
aoe add . -w <branch> -P "$PARENT" -t "<Human Readable Title>" -l
aoe group move "<Human Readable Title>" "$WORKTREES"
```

No `git pull` here: the fetch is what makes the remote branch resolvable, and the worktree tracks origin's version of the branch — the branch you're standing on is irrelevant.

## The group move is a separate step

`aoe add` **silently ignores `-g` when `-P` is given** — the new session inherits the parent's group instead. That is why the group move is its own command afterwards, and why it must not be folded back into the `aoe add` line. Verify it landed:

```bash
aoe session show <id> --json | jq -r '.group'
```

Note the key is `.group` on `session show`, but `group_path` in the raw `sessions.json` — don't read the wrong one and conclude the move failed.

## Title derivation

Derive the title from the branch name: drop the `feat/`, `fix/`, `chore/` prefix, replace separators with spaces, and title-case it. `feat/convert-images` becomes `Convert Images`.

## Worktree folder location and naming

Worktrees live **inside the repo** under `.worktrees/`, and folders keep the branch prefix: `feat/convert-images` lands in `<repo>/.worktrees/feat-convert-images`. Both halves come from `~/.config/agent-of-empires/config.toml`, not from anything in this prompt:

- `worktree.path_template = "./.worktrees/{branch}"` puts them inside the repo (`.worktrees/` is in the global gitignore at `~/.config/git/ignore`).
- `session.tie_workdir_to_name = false` makes `{branch}` use the real branch name. With it on (aoe's default), the folder derives from the session title instead and the prefix is lost.

If a new worktree shows up in the wrong place or without its prefix, one of those settings regressed; fix the config rather than renaming folders by hand (`git` refuses to move worktrees containing submodules anyway).

## Rules

- `-l` is required or the session is only created, never started.
- Never `git checkout` a feature branch in this session — you stay on main. All feature work happens in the worktrees.
- After spawning, report the title, branch, group and worktree path. Do not attach to it.
- To check on the fleet later, use `aoe ps --json --dead`, or filter `aoe list` by the `$WORKTREES` group. Do not rely on `aoe list --json` for parent links or live status; it carries neither.
- Removing a session does not clean up its worktree automatically; use `aoe worktree list` / `aoe worktree cleanup` when I ask you to tidy up.
