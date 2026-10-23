You are reviewing a **stack** of PRs in {{REPO}}. Bottom to top, each one
targets the one below it, and the bottom targets `{{BASE}}`:

    {{STACK}}

(Each entry is `PR:branch`, in merge order.) The top branch is the whole stack
applied; "the top" below means that branch's `origin/` ref.

These PRs belong to someone else. You were asked to review them, nothing more.

**Do not commit. Do not push. Do not rebase. Do not modify any branch.** You
may `git checkout --detach origin/<branch>` to read or run code.

Reviewing one layer in isolation flags things a later layer already fixes. So
the reviews run per PR, in parallel, and nothing is posted until every
candidate has been checked against the top of the stack and verified there.

## 0. Set up

`git fetch origin {{BASE}}` and every branch in the stack. Derive each PR's
own range: the bottom PR is `origin/<merge-base of {{BASE}} and bottom>..origin/<bottom-branch>`
(`git merge-base origin/{{BASE}} origin/<bottom-branch>`), and every other PR
is `origin/<branch-below>..origin/<its-branch>`. Write the table of
`PR | branch | range` down; every later step refers to it. The ranges are
only the scope of what each review may comment on.

The code is read and tested as it will be **after the whole stack merges into
current `{{BASE}}`**, not at the top branch alone: the bottom may have forked
from a `{{BASE}}` that has since moved, and changes on both sides that merge
cleanly can still break each other. Build that merge result in a throwaway
worktree:

```
base=$(git rev-parse origin/{{BASE}})
top=$(git rev-parse origin/<top-branch>)
mwt=$(mktemp -d)/merge
git worktree add --detach "$mwt" "$base"
git -C "$mwt" -c commit.gpgsign=false -c user.name=octopilot \
  -c user.email=octopilot@localhost merge --no-ff --no-edit "$top"
echo "top=$top base=$base mwt=$mwt"
```

Shell variables do not survive between commands: keep the printed values and
use them literally below. If the merge conflicts, `git -C "$mwt" merge
--abort`, remove the worktree, post nothing, and report the conflicting
files. Otherwise record the base you merged into on the bottom PR's item:
`~/.dotfiles/ai/octopilot/scan.sh review-base "{{REPO}}#<bottom-PR>" "$base"`.
`$mwt` is a fresh checkout: install the project's dependencies there before
running tests. When the review is over, `git worktree remove --force "$mwt"`
and `rm -rf "$(dirname "$mwt")"`.

## 1. Pass 1 -- candidates, one subagent per PR, all at once (nothing is posted)

Launch one `Agent` per PR **in a single message**, so they run concurrently.
Each gets the PR number, its branch, its own range from the table, the
merge-result worktree's path, and this instruction:

> Run `{{REVIEW_CMD}} {{REVIEW_LEVEL}} <PR>` without `--comment`. Restrict
> your findings to that PR's own range; do not judge the other branches. Read
> callers, callees and tests in <$mwt>, the whole stack merged into current
> `{{BASE}}`: a defect can come from the PR meeting code that landed on
> `{{BASE}}` after the stack forked.
> Return a numbered list of candidate findings: file, line, the claimed
> defect, and whether it would block a merge. Do not post anything to GitHub.

Candidates are a wide net and some are false positives. Merge the lists into
one, tagged with the PR each came from. Keep the numbering stable from here on.

## 2. Stack filter -- drop what a later PR already fixes

For every candidate, look at the same code at the top of the stack:

- If a later PR in the stack changed or removed the lines so that the defect
  no longer exists at the top, mark it `FIXED-LATER in #N` (the first PR whose
  range touches it) and drop it. Use `git log -S`/`git blame` across the
  ranges when the origin of a change is unclear.
- If two PRs raised the same defect, keep the lowest PR that introduces it and
  drop the duplicate.
- Otherwise it survives, attributed to the PR whose own range introduces the
  defective lines -- which may differ from the PR whose review raised it.

Keep the list of what you dropped and why; it goes in the report, never on
GitHub.

## 3. Pass 2 -- verification in the merge result, in fresh subagents

Launch one `Agent` per PR that still has survivors, **in a single message**,
each with `model: {{COLD_REVIEW_MODEL}}`. Give each only the PR number, the
top branch, the merge-result worktree's path and base sha, the range table
and that PR's numbered survivors -- not your reasoning about them, and no
hint of which ones you believe:

> Verify each candidate finding on {{REPO}} PR #<PR> independently, against
> the code as it will be once the whole stack merges into current `{{BASE}}`
> (worktree <$mwt>, `{{BASE}}` at <$base>). For each one, read the code,
> trace the call path, and run the tests or a small repro when that settles
> it. A candidate may be rejected as pre-existing only if the same defect
> exists at <$base> without the stack. Return one verdict per candidate:
> - CONFIRMED -- with the concrete input or state that makes it go wrong,
>   the file:line, and what you ran or read to confirm it;
> - REJECTED -- with the reason it does not hold, including "a later layer of
>   the stack already fixes it" when that is the reason.
> Do not add new findings. Do not post anything to GitHub.

A candidate with no verdict, or a CONFIRMED without concrete evidence, counts
as REJECTED.

## 4. Post -- one review per PR, only what pass 2 confirmed

For each PR in the stack, bottom to top:

1. Read the reviews already on it (`gh pr view <PR> --json reviews`). If the
   user's account has already approved it, post nothing there and say so in
   the report.
2. Post exactly one GitHub *review*, not a plain comment: "Request changes"
   if at least one CONFIRMED finding attributed to this PR blocks the merge,
   "Approve" otherwise. Put each CONFIRMED finding inline on its line, in the
   PR it is attributed to, with its evidence. A finding goes on exactly one
   PR. GitHub only accepts lines from that PR's diff, so post with
   `commit_id` = that PR's head sha and take line numbers from the file at
   that head, not from the merge worktree.
   - Never mention candidates, unverified findings, dropped findings, or
     that something "may not hold up". Everything you post was verified.
   - If a post fails, check the PR before retrying, so the same review does
     not go up twice.

Then report the base sha the stack was merged into, and one paragraph per PR:
the verdict posted (or why nothing), and the counts -- candidates from pass 1, dropped by the stack filter (with the
fixing PR for each), confirmed and rejected in pass 2.

{{HYGIENE}}
