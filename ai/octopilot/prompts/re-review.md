You are following up on a review of {{REPO}} PR #{{PR}} (branch `{{BRANCH}}`,
base `{{BASE}}`). The user's account reviewed it at commit `{{PREV}}`; the
author has pushed since.

This PR belongs to someone else. **Do not commit. Do not push. Do not rebase.
Do not modify the branch.**

**This is not a full review.** The rest of the PR was reviewed already. Your
scope is: did the new commits fix what we raised, and did they break
anything? Do not raise issues in code the new commits did not touch, and do
not re-raise anything we did not raise before.

## 1. What we asked for

Collect the findings from the user's account's most recent review on this PR:
the review body (`gh pr view {{PR}} --json reviews`) and its inline comments
(`gh api repos/{{REPO}}/pulls/{{PR}}/comments`, filtered to that review's
id). Number them, and keep each one's file:line and what it asked for. Read
the author's replies on those threads too -- a reasoned "won't fix" is an
answer to weigh, not an omission.

## 2. What changed

`git fetch origin` and look at `{{PREV}}..origin/{{BRANCH}}`: `git log` and
`git diff`. If `{{PREV}}` is no longer in the branch history (the author
rebased or force-pushed), use `git range-diff` against `origin/{{BASE}}` to
isolate the author's changes, and say so in your report. If the range is
empty, the author re-requested the review without pushing: the answers are in
their replies on our threads, so step 1 carries the review.

From that, draft:
- for each earlier finding: FIXED, PARTLY FIXED, NOT FIXED, or ANSWERED (the
  author explained why not, with a reason that holds);
- new-issue candidates: defects **introduced by these commits only**.

Post nothing yet.

## 3. Verify, in a fresh subagent

Use the `Agent` tool with `model: {{COLD_REVIEW_MODEL}}`. Give it the PR
number, the branch, this worktree's path, the commit range, the numbered
earlier findings with your draft statuses, and the new-issue candidates --
not your reasoning:

> On {{REPO}} PR #{{PR}} (worktree <path>, range <range>), check each item
> independently against the code. For each earlier finding, confirm or
> correct its status (FIXED / PARTLY FIXED / NOT FIXED / ANSWERED), citing
> the file:line you read or the test you ran. For each new-issue candidate,
> return CONFIRMED with the concrete input or state that breaks it and what
> you ran or read, or REJECTED with the reason. Do not add findings outside
> the commit range. Do not post anything to GitHub.

Use its verdicts, not your draft. A status or candidate it could not back
with evidence does not go in the review.

## 4. Post

1. Re-read the reviews on the PR. If the user's account has already approved
   it, post nothing and report that.
2. Post exactly one GitHub *review*, not a plain comment:
   - "Approve" if every earlier blocking finding is FIXED or ANSWERED and no
     new issue was CONFIRMED;
   - "Request changes" otherwise.
   The body is short: one line per earlier finding with its status (and the
   commit that fixed it, when there is one), then any CONFIRMED new issue,
   inline on its line with its evidence. Nothing about the rest of the PR.
   - Never mention recall, candidates, or unverified findings. Everything you
     post was verified.
   - If a post fails, check the PR before retrying, so the same review does
     not go up twice.

Then report one paragraph: the verdict, how many earlier findings were fixed
or still open, and new issues confirmed and rejected.

{{HYGIENE}}
