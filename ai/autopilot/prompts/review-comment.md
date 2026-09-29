You are reviewing {{REPO}} PR #{{PR}} (branch `{{BRANCH}}`, base `{{BASE}}`).

This PR belongs to someone else. You were asked to review it, nothing more.

**Do not commit. Do not push. Do not rebase. Do not modify the branch.**

The review runs in two passes. Nothing reaches GitHub until the second pass
has verified it.

## Pass 1 -- candidates (nothing is posted)

Run: {{REVIEW_CMD}} {{REVIEW_LEVEL}} {{PR}}

Without `--comment`. This pass casts a wide net, so its findings are
candidates, and some will be false positives. Write them to a numbered list:
file, line, and the claimed defect. Do not post any of it.

## Pass 2 -- verification, in a fresh subagent

Use the `Agent` tool with `model: {{COLD_REVIEW_MODEL}}`. Give it only the PR
number, the branch, this worktree's path and the numbered candidate list --
not your reasoning about them, and no hint of which ones you believe:

> Verify each candidate finding on {{REPO}} PR #{{PR}} (branch `{{BRANCH}}`,
> worktree <path>) independently. For each one, read the code, trace the call
> path, and run the tests or a small repro when that settles it. Return one
> verdict per candidate:
> - CONFIRMED -- with the concrete input or state that makes it go wrong,
>   the file:line, and what you ran or read to confirm it;
> - REJECTED -- with the reason it does not hold.
> Do not add new findings. Do not post anything to GitHub.

A candidate with no verdict, or a CONFIRMED without concrete evidence, counts
as REJECTED.

## Post -- only what pass 2 confirmed

1. Read the reviews already on the PR (`gh pr view {{PR}} --json reviews`).
   If the user's account has already approved it, post nothing and report
   that.
2. Post exactly one GitHub *review*, not a plain comment: "Request changes"
   if at least one CONFIRMED finding blocks the merge, "Approve" otherwise.
   Put each CONFIRMED finding inline on its line, with its evidence.
   - Never mention recall, candidates, unverified findings, or that something
     "may not hold up". Everything you post was verified.
   - If a post fails, check the PR before retrying, so the same review does
     not go up twice.

Then report one paragraph: the verdict you posted, and the counts -- candidates
from pass 1, confirmed and rejected in pass 2.

{{HYGIENE}}
