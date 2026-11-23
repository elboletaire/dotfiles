When you create a worktree or a new work branch, `git fetch` first and branch off the remote base, never a possibly stale local branch: `git worktree add --no-track -b <branch> <repo>/.worktrees/<branch with / as -> origin/<base>`. Only when `<base>` is not on the remote, or there is no remote, use the local branch instead. To work on a branch that already exists on the remote (a PR, say), track it: `git worktree add --track -b <branch> <wt> origin/<branch>`.

When writing code, you plan and delegate; you do not implement it yourself:

1. Split the work into self-contained tasks, each with the files it touches and how to verify it.
2. Each task goes to a `worker` subagent (Haiku). Parallel tasks each get their own worktree and branch, made by you as above, and the worker commits there; a single task runs where we are working, without committing.
3. A `reviewer` subagent (Opus) reviews each task once its worker returns. Must-fix findings go back to a worker with the review attached; after two rounds without approval, redo the task with a `general-purpose` subagent on Sonnet instead.
4. With more than one task, merge the branches yourself, then have an `integrator` subagent (Opus) review the merged whole. Its must-fix findings go through steps 2 and 3 again.

Skip all this for changes of a line or two, which you make directly, and when I ask for something else.

<STARTING_NEW_PROJECTS>
When starting new coding projects, the preferred languages and tools are the following:

- Go
- Typescript
- pnpm
- vite or tsdown
- vitest
- up-fetch

If you consider that some of these tools aren't suitable enough and want to propose a different language or toolset, ask directly the user after explaining your issues with the requested toolset.
</STARTING_NEW_PROJECTS>

Previews (designs, logos, mockups, reports) are local files: write a self-contained `.html` and give me its path (or `! open <path>`). Don't publish or deploy them anywhere, Artifacts included, unless I ask for that explicitly.

@RTK.md

This file is shared by all my workstations through dotfiles. Facts about the current machine only (hardware, OS, local paths, installed tools) go in `~/.claude/machine.md`, which stays on that machine and is imported below; create it if missing.

@~/.claude/machine.md
