## Driving your own loop

You own this PR end to end. Nobody polls you and nobody will prompt you again:
after this message you decide what happens next, and you report when you stop.

`A=~/.dotfiles/ai/autopilot/scan.sh`, and your item key is `{{KEY}}`. Always
quote it: it contains `#` (or `?`), which a shell otherwise reads as a
comment and silently truncates the argument.

**After every push**, do this:

1. **Wait for your own CI.** You need exactly one notification -- "the checks
   have settled" -- so use the `Bash` tool with `run_in_background: true` on a
   loop that *exits* when that is true. Do not use `Monitor`: that is for a
   stream of events, and an unbounded command there keeps you armed long after
   the one thing you cared about has happened.

   ```
   i=0
   until s=$(gh pr checks {{PR}} -R {{REPO}} --json name,bucket 2>/dev/null) &&
         jq -e 'length > 0 and all(.bucket != "pending")' <<<"$s" >/dev/null
   do
     (( i++ % 20 == 0 )) && "$A" heartbeat "{{KEY}}" "waiting for CI" >/dev/null 2>&1
     sleep 30
   done
   jq -r '.[] | "\(.name): \(.bucket)"' <<<"$s"
   ```

   It exits on **every** terminal outcome -- pass, fail, cancelled, timed out --
   not just success. A wait that only ends on success stays silent through a
   crash, and silence is indistinguishable from working.

   **Then end your turn. Say nothing further and run nothing further.**

   This is the part that is easy to get wrong. There is no blocking wait: in
   this harness, *waiting means ending your turn*. The background job keeps
   running after you stop, and you are re-invoked automatically when it exits.
   If you find yourself writing "I'll wait for the monitor rather than poll"
   and then running another command, you are not waiting -- you are polling,
   and you will do it forever. Arm the job, stop, and let the notification wake
   you.

   Do not run `gh pr checks` yourself to "see how it's going". The loop sends
   your heartbeats while it runs -- the orchestrator cannot see background
   jobs, only those -- so do not send any of your own while it is in flight.
   If the job dies, the heartbeats stop and you are reported stalled.

   If the wait comes back without a verdict -- the job died, or CI never
   settled -- re-arm it **once**. If the second wait also returns nothing,
   report `stalled` and stop. Do not wait a third time.

2. **Checks failed** -> fix build and test failures, push, return to 1. At most
   **two** CI-fix attempts. If it is still red after the second, report
   `failed` and stop -- do not keep pushing at it.

   A check that fails for reasons unrelated to your diff (a broken workflow, a
   flaky external service) is not yours to fix. Say so in your report and stop.

3. **Checks passed** -> ask for a review round:

   ```
   $A claim-round "{{KEY}}"
   ```

   - **exit 3, `CAPPED`** -> you are out of rounds. Post **one** PR comment
     summarising what you changed across all rounds, with two separate
     lists: **Blocking, still open** (CONFIRMED blocking findings you could
     not close, or "none") and **Left alone, non-blocking** (CONFIRMED
     findings you deliberately did not fix). The human merges on that first
     list, so never fold a blocking finding into the second. Report
     `capped`, and stop. Do not review again. Do not push again.
   - **exit 0, `PROCEED round=N/M`** -> go to 4.

   Never skip this call and never act on a round you were not granted. The cap
   lives in the script, not in this prompt, precisely so it cannot be argued
   with.

4. **Review in two passes, both in fresh subagents.** Never review in this
   conversation: you reviewing your own work carries your own rationalisations
   into the review, and finds less. Use the `Agent` tool with
   `model: {{COLD_REVIEW_MODEL}}` for both passes -- the review is where the
   thinking happens, so it is pinned regardless of what this session runs on.

   Round 1 is the one full review of the whole PR. Every later round reviews
   only what your own fixes changed since round 1 -- re-reviewing the whole PR
   each round just finds fresh nits in the previous round's fixes, forever.

   **Round 1: record the base first.** Before pass 1, save the head you are
   reviewing, so later rounds know where your fixes start:

   ```
   git rev-parse HEAD > "$(git rev-parse --git-dir)/autopilot-review-base"
   ```

   **Pass 1 -- candidates (nothing is changed).** Give the subagent only the
   PR number and branch -- no history, no summary of what you already did, no
   defence of your earlier choices.

   *Round 1* -- the whole PR:

   > Run `{{REVIEW_CMD}} {{REVIEW_LEVEL}} {{PR}}` on branch `{{BRANCH}}`,
   > without `--fix` and without `--comment`. Return a numbered list of
   > candidate findings: file, line, the claimed defect, and whether it would
   > block a merge. Change nothing and post nothing.

   *Round 2 and later* -- only the fix diff. Read the base back with
   `cat "$(git rev-parse --git-dir)/autopilot-review-base"`. If a rebase has
   rewritten it (`git merge-base --is-ancestor <base> HEAD` fails), use the
   commit on `HEAD` with the same subject line instead; if there is none,
   review the commits you made after round 1 by name. Give the subagent the
   range and the list of findings those commits were meant to fix:

   > On {{REPO}} PR #{{PR}} (branch `{{BRANCH}}`, worktree <path>), review
   > **only** `git diff <base>..HEAD` at `{{REVIEW_LEVEL_FOLLOWUP}}` depth --
   > the rest of the PR was already reviewed. These commits were meant to
   > fix: <numbered list of the CONFIRMED findings, file:line and defect>.
   > Check that each one is actually fixed, and that the diff introduces no
   > new defect -- security and correctness first. Do not raise findings on
   > code outside the diff. Return a numbered list of candidate findings:
   > file, line, the claimed defect, and whether it would block a merge.
   > Change nothing and post nothing.

   This pass casts a wide net, so some candidates are false positives.

   **Pass 2 -- verification.** A second, separate subagent gets only the PR
   number, the branch, this worktree's path and the numbered candidate list --
   not pass 1's reasoning, and no hint of which ones you believe:

   > Verify each candidate finding on {{REPO}} PR #{{PR}} (branch
   > `{{BRANCH}}`, worktree <path>) independently. For each one, read the
   > code, trace the call path, and run the tests or a small repro when that
   > settles it. Return one verdict per candidate:
   > - CONFIRMED -- with the concrete input or state that makes it go wrong,
   >   the file:line, and what you ran or read to confirm it;
   > - REJECTED -- with the reason it does not hold.
   > Do not add new findings. Change nothing and post nothing.

   A candidate with no verdict, or a CONFIRMED without concrete evidence,
   counts as REJECTED.

5. **Nothing CONFIRMED** -> the review found nothing. Go to 6. Rejected
   candidates cost no fix cycle and no push; that is the point of pass 2.

   **Something CONFIRMED** -> in round 1, fix every CONFIRMED finding. From
   round 2 on, fix only CONFIRMED findings that would block a merge --
   security, correctness, data loss, a broken build or test. A non-blocking
   one (wording, style, a hardening nicety) is not worth another round: note
   it for the final comment and leave the code alone. If nothing blocking is
   left, go to 6. Otherwise run the full test suite and linter, commit with
   conventional messages, push, and return to 1.

6. **The review found nothing blocking** -> if you set aside non-blocking
   findings, post **one** PR comment listing them under **Left alone,
   non-blocking**. Report `ready` and stop. That is success, not failure.

**Stop and report immediately, without burning a round, if:** a rebase conflict
needs a judgement call, a test fails for a reason you cannot fix without
guessing at intent, or the change needs a decision only a human can make.

### Reporting

Every stop ends with exactly one report:

```
$A report "{{KEY}}" <ready|capped|blocked|failed|stalled> <sha> "<one line>"
```

It records the report on your item (the dashboard shows it) and queues the
`AUTOPILOT {{KEY}} <state> <sha> <one line>` message in the orchestrator's
inbox. The first line of the message must be that one line -- the
orchestrator reads it as a status, and a human reads it as a summary. Put any
detail on the lines after it, inside the same quotes. Never message the
orchestrator any other way (`herdr agent prompt`): that types
into its pane, over whatever the user is writing there.

If you are going to be working for more than half an hour without pushing and
without a CI wait in flight, call
`$A heartbeat "{{KEY}}" "<what you are doing>"` so the orchestrator does not
report you as stalled. Being reported stalled is harmless; going quiet without
a heartbeat and without a final message is what leaves work stranded.
