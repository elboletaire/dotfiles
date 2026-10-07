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
own range: the bottom PR is `origin/{{BASE}}..origin/<bottom-branch>`, and
every other PR is `origin/<branch-below>..origin/<its-branch>`. Write the
table of `PR | branch | range` down; every later step refers to it.

## 1. Pass 1 -- candidates, one subagent per PR, all at once (nothing is posted)

Launch one `Agent` per PR **in a single message**, so they run concurrently.
Each gets the PR number, its branch, its own range from the table, this
worktree's path, and this instruction:

> Run `{{REVIEW_CMD}} {{REVIEW_LEVEL}} <PR>` without `--comment`. Restrict
> yourself to that PR's own range; do not read or judge the other branches.
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

## 3. Pass 2 -- verification at the top of the stack, in fresh subagents

Check out the top (`git checkout --detach origin/<top-branch>`). Launch one
`Agent` per PR that still has survivors, **in a single message**, each with
`model: {{COLD_REVIEW_MODEL}}`. Give each only the PR number, the top branch,
this worktree's path, the range table and that PR's numbered survivors -- not
your reasoning about them, and no hint of which ones you believe:

> Verify each candidate finding on {{REPO}} PR #<PR> independently, against
> the code as it stands at the top of the stack (`origin/<top-branch>`,
> checked out at <path>). For each one, read the code, trace the call path,
> and run the tests or a small repro when that settles it. Return one verdict
> per candidate:
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
   PR.
   - Never mention candidates, unverified findings, dropped findings, or
     that something "may not hold up". Everything you post was verified.
   - If a post fails, check the PR before retrying, so the same review does
     not go up twice.

Then report one paragraph per PR: the verdict posted (or why nothing), and
the counts -- candidates from pass 1, dropped by the stack filter (with the
fixing PR for each), confirmed and rejected in pass 2.

{{HYGIENE}}
