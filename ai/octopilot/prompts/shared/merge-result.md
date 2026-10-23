## Review the merge result, not the branch

A branch reviewed on its own is checked against the base it forked from, and
that base may be far behind. Two changes that each look fine, and that Git
merges cleanly because they touch different lines, can still break each other:
a function on the base starts taking a context or holding a lock, and the PR
changes what it calls in a way that ignores both. So every review reads and
tests the code as it will be **after the merge**.

This worktree must be at the PR's current head. On someone else's PR, check
that `git rev-parse HEAD` matches `gh pr view {{PR}} -R {{REPO}} --json
headRefOid -q .headRefOid`; if not, `git fetch origin "pull/{{PR}}/head"` and
`git checkout --detach FETCH_HEAD` (that ref works for fork PRs too). On your
own PR, HEAD is what you just pushed.

**Before pass 1**, build the merge result in a throwaway worktree:

```
git fetch origin {{BASE}}
head=$(git rev-parse HEAD)
base=$(git rev-parse origin/{{BASE}})
mwt=$(mktemp -d)/merge
git worktree add --detach "$mwt" "$base"
git -C "$mwt" -c commit.gpgsign=false -c user.name=octopilot \
  -c user.email=octopilot@localhost merge --no-ff --no-edit "$head"
echo "head=$head base=$base mwt=$mwt"
```

Shell variables do not survive between commands: keep the three printed
values and use them literally wherever `$head`, `$base` and `$mwt` appear
below. If the merge conflicts, `git -C "$mwt" merge --abort`, remove the
worktree, and report the conflicting files instead of reviewing: a review of
a merge that cannot happen yet is a review of the wrong code.

Then record which base you merged, so a later update to `{{BASE}}` can be told
apart from the one you reviewed against:

```
~/.dotfiles/ai/octopilot/scan.sh review-base "{{KEY}}" "$base"
```

`$mwt` is a fresh checkout: install the project's dependencies there before
running anything (the same install step the repo's CI or AGENTS.md uses).

From here on:

- **Scope is still the PR.** Findings are only about lines the PR changes
  (`git diff $base...$head`), or the narrower range this review was given.
  But read callers, callees and tests, and run the tests, in `$mwt`, never in
  the branch worktree.
- **Every subagent works in `$mwt`.** Give both passes that path, not the
  branch worktree, and tell them it is the PR merged into current `{{BASE}}`
  (`$base`).
- **"Not new" is judged against current `{{BASE}}`.** Give the pass-2
  verifier this rule verbatim: *a candidate may be rejected as pre-existing
  only if the same defect exists at `$base` without the PR. If it appears only
  once the PR's change meets code that is on `{{BASE}}` today -- even code the
  branch has never seen -- it is the PR's defect.*
- **Inline comments anchor to the PR head.** When you post them, GitHub only
  accepts lines from the PR diff: use `commit_id` = `$head` and take each line
  number from the file at `$head` (`git show "$head":<file>`), not from
  `$mwt`, where the same line can sit elsewhere.
- **Say what you reviewed.** Your report names the base sha (`${base:0:7}`)
  the PR was merged into.

When the review is over: `git worktree remove --force "$mwt"` and
`rm -rf "$(dirname "$mwt")"`.
