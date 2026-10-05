---
description: Turn this main-branch herdr agent into an orchestrator that spawns worktree workspaces, each with its own agent
---

This agent is an **orchestrator** running in herdr. It stays on the repository's main branch and does not do feature work itself -- its job is to create and supervise worktree workspaces, each on its own branch with its own agent.

Check you are inside herdr first; if this fails, say so and stop:

```bash
test "${HERDR_ENV:-}" = 1
```

Resolve the repo root once and keep it for the rest of the session:

```bash
REPO=$(git rev-parse --show-toplevel)
```

## Always fetch first

Every workspace request starts with `git fetch origin`, no exceptions. Both flows depend on origin being current: tracking needs the remote ref to exist locally, and creating needs the base branch to be up to date.

## Creating a workspace

When I say **create** a branch (e.g. "create feat/user-auth"), it does not exist yet -- it starts blank, off the freshly updated current branch:

```bash
git fetch origin
git pull
herdr worktree create --cwd "$REPO" --branch <branch> \
  --base "$(git branch --show-current)" \
  --path "$REPO/.worktrees/<branch with / as ->" \
  --label "<Human Readable Title>" --no-focus
```

The `git pull` matters -- the point is to branch off the *updated* current branch, not a stale local one.

## Tracking a workspace

When I say **track** a branch, it already exists on origin -- do not create it. **Do not use `herdr worktree create` for this**: for a branch that only exists on origin it makes a new local branch off HEAD instead of tracking the remote one, and the agent ends up on the wrong code. Make the worktree with git, then open it in herdr:

```bash
git fetch origin
WT="$REPO/.worktrees/<branch with / as ->"
if git show-ref --verify --quiet "refs/heads/<branch>"; then
  git worktree add "$WT" <branch>
else
  git worktree add --track -b <branch> "$WT" "origin/<branch>"
fi
herdr worktree open --cwd "$REPO" --path "$WT" --label "<Human Readable Title>" --no-focus
```

## Starting its agent

Both commands return JSON; take the new workspace's root pane from `.result.root_pane.pane_id` and start claude in it, named after the branch (lowercase `[a-z0-9-]`, at most 32 characters, unique in `herdr agent list`):

```bash
herdr agent start <name> --kind claude --pane <root-pane-id>
```

If it returns `agent_not_ready`, the agent is sitting on a dialog: read it with `herdr agent read <name> --source visible` and tell me what it asks. Do not answer it yourself.

## Grouping

herdr groups every worktree workspace under its repo's workspace on its own -- there is no group to create or move into.

## Title derivation

Derive the title from the branch name: drop the `feat/`, `fix/`, `chore/` prefix, replace separators with spaces, and title-case it. `feat/convert-images` becomes `Convert Images`.

## Worktree folder location and naming

Worktrees live **inside the repo** under `.worktrees/`, and folders keep the branch prefix with `/` turned into `-`: `feat/convert-images` lands in `<repo>/.worktrees/feat-convert-images`. herdr's default is `~/.herdr/worktrees`, which is why `--path` is always passed explicitly. `.worktrees/` is in the global gitignore at `~/.config/git/ignore`.

## Rules

- Never `git checkout` a feature branch in this workspace -- you stay on main. All feature work happens in the worktrees.
- After spawning, report the title, branch, workspace id, agent name and worktree path. Do not focus it.
- Talk to a worktree's agent with `herdr agent prompt <name> "..."`. If it answers `agent_blocked`, it is waiting on an approval or a question: tell me, do not answer it.
- To check on the fleet, use `herdr agent list` and `herdr worktree list --cwd "$REPO"`.
- Only remove a workspace when I ask: `herdr worktree remove --workspace <id> --force` deletes the checkout and closes the workspace, keeping the branch. `herdr workspace close <id>` stops it but keeps the checkout.
