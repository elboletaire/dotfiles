Do NOT use `Co-authored-by` in your commits. You're not going to get blamed for the changes, I will, so your participation doesn't need to be added there.

When creating issues or pull requests, rather than ending with youre signature, start by saying something like "This is {model} speaking on behalf of elbolataire." or "{model} here, controlled by elboletaire."

Keep PR descriptions under ~15 lines of markdown (code blocks included): what changed and why, any non-obvious decisions, how it was tested, and **one** usage example if the change has a user-facing surface. Skip anything the diff or README already says.

Review comments follow the same rule: each finding in about three sentences. Say what's wrong, what it breaks, and the fix. Don't walk through every step of the reasoning or restate what the diff shows. Mark nits with "Nit:" and keep them shorter still. The review's summary body gets the same treatment.

Keep issues under ~15 lines of markdown too, code blocks included. Open with the problem in a sentence or two. For a bug, add what happens, what should happen and the shortest way to reproduce it. For a feature, add why it's needed and what "done" looks like. Then add pointers to the relevant code, PRs or issues, and a proposed approach if there's one. Quote only the log lines that matter, label guesses as guesses, and skip anything the title already says.

When I ask you to post a comment on a PR we've just reviewed, post it as a review by default, not as a regular comment. Also, make sure to mark it as either "Request changes" or "Approve", depending on the outcome of the review.

When you create a worktree or a new work branch, `git fetch` first and branch off the remote base, never a possibly stale local branch: `git worktree add --no-track -b <branch> <repo>/.worktrees/<branch with / as -> origin/<base>`. Only when `<base>` is not on the remote, or there is no remote, use the local branch instead. To work on a branch that already exists on the remote (a PR, say), track it: `git worktree add --track -b <branch> <wt> origin/<branch>`. Never pull, check out or otherwise touch the main checkout: I edit it by hand.

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

@RTK.md
