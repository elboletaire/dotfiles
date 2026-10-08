Do NOT use `Co-authored-by` in your commits. You're not going to get blamed for the changes, I will, so your participation doesn't need to be added there.

When creating issues or pull requests, rather than ending with youre signature, start by saying something like "This is {model} speaking on behalf of elbolataire." or "{model} here, controlled by elboletaire."

When I ask you to post a comment on a PR we've just reviewed, post it as a review by default, not as a regular comment. Also, make sure to mark it as either "Request changes" or "Approve", depending on the outcome of the review.

When you create a worktree or a new work branch, `git fetch` first and branch off the remote base, never a possibly stale local branch: `git worktree add --no-track -b <branch> <repo>/.worktrees/<branch with / as -> origin/<base>`. Only when `<base>` is not on the remote, or there is no remote, use the local branch instead. To work on a branch that already exists on the remote (a PR, say), track it: `git worktree add --track -b <branch> <wt> origin/<branch>`. Never pull, check out or otherwise touch the main checkout: I edit it by hand.

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
