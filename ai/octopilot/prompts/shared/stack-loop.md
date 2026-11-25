## Driving your own loop

You own this stack end to end. Nobody polls you and nobody will prompt you again:
after this message you decide what happens next, and you report when you stop.

`A="${OCTOPILOT_DIR:-$HOME/.dotfiles/ai/octopilot}/scan.sh"`, and your item key is `{{KEY}}`: the
bottom open PR's key, which tracks the whole stack. Rounds, heartbeats and the
report all go on that key, whichever layer a finding is about. Always quote it:
it contains `#` (or `?`), which a shell otherwise reads as a comment and silently
truncates the argument.

The stack, bottom to top, is `{{STACK}}`: the open layers only, and this loop
uses them as given. Take every PR number and branch from there. Shell variables
do not survive between commands, so write the lists out again in each command
that needs them.

**Mixed stack guard.** Every layer must be yours: you opened it or it is
assigned to you. Check before the first claim and again before every push:

```
me=$(gh api user -q .login)
for n in <PR numbers, bottom to top>; do
  gh pr view "$n" -R {{REPO}} --json author,assignees |
    jq --arg me "$me" '.author.login == $me or any(.assignees[]; .login == $me)'
done
```

If any layer prints `false`, push nothing anywhere and report `blocked` with
that PR number. Do not push the layers that are yours either: a restack moves
every layer above a fix, so a partial push leaves the stack broken.

**Sync the layers.** Each layer is a local branch that must equal its remote
and must not be checked out in another worktree. Check the worktrees first:

```
git worktree list --porcelain
```

If a layer branch (`branch refs/heads/<b>`) is listed under any worktree other
than this one, report `blocked`: someone else is using it. Otherwise fetch and
sync, bottom to top:

```
git fetch origin
ok=1
for b in <branches, bottom to top>; do
  [ -z "$(git rev-list "origin/$b..$b" 2>/dev/null)" ] || { echo "$b has local commits origin does not"; ok=0; break; }
  git switch -C "$b" "origin/$b" || { echo "cannot switch to $b"; ok=0; break; }
done
[ "$ok" = 1 ] || echo "SYNC FAILED"
```

If it prints `SYNC FAILED`, stop and report `blocked`: the local branch is yours
to inspect, not to overwrite. Push nothing. The `origin/*` refs this sync leaves
behind are what the push checks its lease against, so **never run `git fetch`
between the sync and the push**. Afterwards the worktree sits on the top layer.

**Restacking.** Fixing a layer moves every layer above it. With the layer's new
head committed on its branch:

```
git rebase --update-refs <layer> <top>
```

The upstream is the layer itself, so the rebase replays exactly the layers above
it onto its new head, and `--update-refs` moves each intermediate layer branch
along. Nothing to do when the layer is the top. Afterwards check every pair with
`git merge-base --is-ancestor <layer> <layer above>`. **A failed ancestor check
means the restack is wrong: push nothing, and report `blocked`.** A `fatal:` line
from a commit hook during the rebase is not a failure: go by the exit status and
the ancestor checks. A conflict that
needs a judgement call means `blocked` too: leave the rebase in progress, name
the files and hunks, and stop. A mechanical conflict you resolve, and you note
that layer, because round 2 reviews it.

**After every push**, do this:

1. **Wait for CI on every PR in the stack.** You need exactly one notification --
   "every layer's checks have settled" -- so use the `Bash` tool with
   `run_in_background: true` on a loop that *exits* when that is true. Do not
   use `Monitor`: that is for a stream of events, and an unbounded command there
   keeps you armed long after the one thing you cared about has happened.

   ```
   A="${OCTOPILOT_DIR:-$HOME/.dotfiles/ai/octopilot}/scan.sh"
   PRS=(<PR numbers, bottom to top>)
   # Per layer: all checks terminal. A layer gh reports no checks for counts as
   # settled once the grace period (10 rounds, about 5 minutes) has passed; any
   # other gh failure (network, rate limit) is waited out, not counted as settled.
   settled() {
     for n in "${PRS[@]}"; do
       c=$(gh pr checks "$n" -R {{REPO}} --json name,bucket 2>|"$err")
       if [ -z "$c" ] || [ "$c" = "[]" ]; then
         if grep -qi 'no checks reported' "$err" && (( i >= 10 )); then
           continue
         fi
         return 1
       fi
       jq -e 'all(.bucket != "pending")' <<<"$c" >/dev/null || return 1
     done
   }
   err=$(mktemp)
   i=0
   start=$(date +%s)
   until settled
   do
     if (( $(date +%s) - start > 5400 )); then echo TIMEOUT; break; fi
     (( i++ % 20 == 0 )) && "$A" heartbeat "{{KEY}}" "waiting for CI on the stack" >/dev/null 2>&1
     sleep 30
   done
   for n in "${PRS[@]}"; do
     c=$(gh pr checks "$n" -R {{REPO}} --json name,bucket 2>/dev/null)
     if [ -z "$c" ] || [ "$c" = "[]" ]; then echo "#$n: no checks"; continue; fi
     jq -r --arg pr "$n" '.[] | "#\($pr) \(.name): \(.bucket)"' <<<"$c"
   done
   rm -f "$err"
   ```

   It exits once **every** layer's checks are terminal -- pass, fail, cancelled,
   timed out -- not just on success, or after 90 minutes, when it prints
   `TIMEOUT`. A layer that never reports checks is settled by the grace period
   above, not waited on forever.

   **Then end your turn. Say nothing further and run nothing further.**

   There is no blocking wait: in this harness, *waiting means ending your turn*.
   The background job keeps running after you stop, and you are re-invoked
   automatically when it exits. If you find yourself writing "I'll wait for the
   monitor rather than poll" and then running another command, you are not
   waiting -- you are polling, and you will do it forever. Arm the job, stop,
   and let the notification wake you.

   Do not run `gh pr checks` yourself to "see how it's going". The loop sends
   your heartbeats while it runs -- the orchestrator cannot see background
   jobs, only those -- so do not send any of your own while it is in flight.
   If the job dies, the heartbeats stop and you are reported stalled.

   If the wait comes back without a verdict -- the job died, it printed
   `TIMEOUT`, or CI never settled -- re-arm it **once**. If the second wait also
   returns nothing, report `stalled` and stop. Do not wait a third time.

2. **Checks failed** -> find the layer whose checks failed (the `#PR` in the
   output), fix build and test failures on that layer's branch, restack the
   layers above it as described above, push, return to 1. At most **two**
   CI-fix attempts. If it is still red after the second, report `failed` and
   stop -- do not keep pushing at it.

   A check that fails for reasons unrelated to your diff (a broken workflow, a
   flaky external service) is not yours to fix. Say so in your report and stop.

3. **Checks passed** -> ask for a review round:

   ```
   $A claim-round "{{KEY}}"
   ```

   - **exit 3, `CAPPED`** -> you are out of rounds. For each layer that has
     something to say, post **one** PR comment on that layer, with two separate
     lists: **Blocking, still open** (CONFIRMED blocking findings attributed to
     that layer which you could not close, or "none") and **Left alone,
     non-blocking** (CONFIRMED findings you deliberately did not fix). Never
     comment on a layer with nothing to list. The human merges on the first
     list, so never fold a blocking finding into the second. Report `capped`,
     and stop. Do not review again. Do not push again.
   - **exit 0, `PROCEED round=N/M`** -> go to 4.

   Never skip this call and never act on a round you were not granted. The cap
   lives in the script, not in this prompt, precisely so it cannot be argued
   with.

4. **Review in two passes, both in fresh subagents.** Never review in this
   conversation: you reviewing your own work carries your own rationalisations
   into the review, and finds less. Use the `Agent` tool: `model: {{FIND_MODEL}}`
   for pass 1 and `model: {{VERIFY_MODEL}}` for pass 2. The review is where the
   thinking happens, so both are pinned regardless of what this session runs on,
   and pass 2 on another model does not repeat pass 1's blind spots.

   Round 1 is the one full review of the whole stack. Every later round reviews
   only what the previous round's fixes changed, layer by layer (below) --
   re-reviewing the whole stack each round just finds fresh nits in the previous
   round's fixes, forever.

   **Every round: sync, then build the merge result.** Run the sync from the
   section above first, so the `origin/*` refs are fresh and the layers are
   checked out. Then merge the top of the stack into the current base in a
   throwaway worktree, so the review reads the code as it will be after the
   whole stack lands. Pass 1 and pass 2 both work there, and so does every test
   run for the review.

   ```
   base=$(git rev-parse origin/{{BASE}})
   top=$(git rev-parse origin/<top branch>)
   mwt=$(mktemp -d)/merge
   git worktree add --detach "$mwt" "$base"
   git -C "$mwt" -c commit.gpgsign=false -c user.name=octopilot \
     -c user.email=octopilot@localhost merge --no-ff --no-edit "$top"
   echo "top=$top base=$base mwt=$mwt"
   ```

   Keep the printed values (`top`, `base`, `mwt`) and use them literally below.
   If the merge conflicts, `git -C "$mwt" merge --abort`, remove the worktree,
   and restack the stack onto `origin/{{BASE}}`: the upstream is the fork point of
   the bottom, `git merge-base origin/{{BASE}} origin/<bottom>`, and the command
   is `git rebase --onto origin/{{BASE}} <upstream> <top> --update-refs`. Resolve
   what is mechanical, run the tests, push the moved layers as the push step below
   does, and build the merge result again. A conflict that needs a judgement call
   is `blocked`: a review of a merge that cannot happen yet is a review of the
   wrong code. The merge result is a fresh checkout: install the project's
   dependencies there before running anything (the same install step the repo's
   CI or AGENTS.md uses).

   Record the base you merged into, so a later move of `{{BASE}}` can be told
   apart from the one you reviewed against:

   ```
   $A review-base "{{KEY}}" "$base"
   ```

   Then the review heads. Keep the previous file as `<file>.prev` (it holds the
   heads the last round started from), then overwrite the file with this round's
   heads. Its first line is the fork point of the bottom, the commit below the
   stack; then one `<branch> <head>` line per layer, bottom to top, where the head
   is `origin/<branch>`:

   ```
   f="$(git rev-parse --git-dir)/octopilot-stack-review-base"
   cp -f "$f" "$f.prev" 2>/dev/null
   { echo "fork $(git merge-base origin/{{BASE}} origin/<bottom>)"
     for b in <branches, bottom to top>; do echo "$b $(git rev-parse "origin/$b")"; done
   } >| "$f"
   ```

   The first round has no previous file: the heads it writes are the baseline
   that round 2 reviews from. In round 2+, the previous heads are in `$f.prev`:
   the `fork` line is the commit below the bottom, and each `<branch>` line is a
   layer's head.

   **Pass 1 -- candidates (nothing is changed).** Launch one `Agent` per layer
   **in a single message**, so they run concurrently, each with
   `model: {{FIND_MODEL}}`. Give each only the PR number, its branch, its range
   (below), and the merge-result worktree's path -- no history, no summary of
   what you already did, no defence of your earlier choices.

   *Round 1* -- the layer's own range:

   > In worktree <$mwt> (`{{REPO}}` PR #<PR>, the whole stack merged into
   > current `{{BASE}}`), run `{{REVIEW_CMD}} {{REVIEW_LEVEL}} <PR>`, without
   > `--fix` and without `--comment`. Restrict your findings to that PR's own
   > range, `<range>`: do not judge the other layers. Read callers, callees and
   > tests in <$mwt>, never in a branch worktree. Return a numbered list of
   > candidate findings: file, line, the claimed defect, and whether it would
   > block a merge. Change nothing and post nothing.

   *Round 2 and later* -- only what the previous round's fixes changed, for each
   layer that you committed a fix to, and each layer whose restack needed a
   conflict resolution (you know which; keep the list). Compare the layer's
   commits before and after the round with `git range-diff`, which lines the
   commits up by content, so a moved base or a restack does not show up as a
   change:

   > In worktree <$mwt> (`{{REPO}}` PR #<PR>, the whole stack merged into
   > current `{{BASE}}`), run
   > `git range-diff <prev below>..<prev head> origin/<below>..origin/<branch>`.
   > Review the new side of every commit it marks `!` or `>` (`git show <new
   > sha>`; for `!`, the interdiff `git range-diff` printed under it shows the
   > change). The rest of the layer was already reviewed. These commits were meant to fix:
   > <numbered list of the CONFIRMED findings attributed to this layer, file:line
   > and defect>. Check that each one is actually fixed, and that the change
   > introduces no new defect -- security and correctness first. Do not raise
   > findings on code outside those commits. Return a numbered list of candidate
   > findings: file, line, the claimed defect, and whether it would block a
   > merge. Change nothing and post nothing.

   Here `<prev below>` is the sha on the line directly above this layer's own
   line in `$f.prev` (the `fork` line, for the layer that was the bottom then).
   That line may belong to a layer a restack has since dropped: a merged bottom
   is still the right base for the range the layer had before, so use its head.
   `<prev head>` is the layer's own `$f.prev` line; `<below>` is the layer below
   in `{{STACK}}`, or the fork point for the bottom. Those ranges are the scope
   of what each review may comment on, and the code is always read in the merge
   result. For round 1, a layer's range is `<fork>..origin/<branch>` for the
   bottom and `origin/<below>..origin/<branch>` for each other layer, where
   `<fork>` is `git merge-base origin/{{BASE}} origin/<bottom>`.

   This pass casts a wide net, so some candidates are false positives.

   **Stack filter -- after pass 1, before pass 2.** Merge the layers' candidate
   lists into one, tagged with the layer each came from, and keep the numbering
   stable. For every candidate, look at the same code at the top of the stack:

   - If a later layer changed or removed the lines so the defect no longer
     exists at the top, mark it `FIXED-LATER in #N` (the first layer whose
     range touches it) and drop it. Use `git log -S` / `git blame` across the
     ranges when the origin of a change is unclear.
   - If two layers raised the same defect, keep the lowest layer that
     introduces it and drop the duplicate.
   - Otherwise it survives, attributed to the layer whose own range introduces
     the defective lines -- which may differ from the layer whose review raised
     it.

   Keep the list of what was dropped and why: it goes in the report. Pass 2
   then gets only the survivors, grouped by attributed layer.

   **Pass 2 -- verification.** Launch one fresh subagent per layer that still
   has survivors, **in a single message**, each with `model: {{VERIFY_MODEL}}`.
   Give each only the PR number, its branch, the merge-result worktree's path
   and the printed `base` sha, and that layer's numbered survivor list -- not
   pass 1's reasoning, and no hint of which ones you believe:

   > Verify each candidate finding on `{{REPO}}` PR #<PR> independently, against
   > the code as it will be once the whole stack merges into current `{{BASE}}`
   > (worktree <$mwt>, `{{BASE}}` at <$base>). For each one, read the code,
   > trace the call path, and run the tests or a small repro when that settles
   > it. A candidate may be rejected as pre-existing only if the same defect
   > exists at <$base> without the stack. Return one verdict per candidate:
   > - CONFIRMED -- with the concrete input or state that makes it go wrong,
   >   the file:line, and what you ran or read to confirm it;
   > - REJECTED -- with the reason it does not hold, including "a later layer of
   >   the stack already fixes it" when that is the reason.
   > Do not add new findings. Change nothing and post nothing.

   A candidate with no verdict, or a CONFIRMED without concrete evidence, counts
   as REJECTED.

5. **Nothing CONFIRMED** -> the review found nothing. Go to 6. Rejected
   candidates cost no fix cycle and no push; that is the point of pass 2.

   **Something CONFIRMED** -> in round 1, fix every CONFIRMED finding. From
   round 2 on, fix only CONFIRMED findings that would block a merge -- security,
   correctness, data loss, a broken build or test. A non-blocking one (wording,
   style, a hardening nicety) is not worth another round: note it for the
   comments and leave the code alone. If nothing blocking is left, go to 6.

   Otherwise fix on the layer each finding is **attributed** to -- the layer
   whose range introduces the defect -- never on a higher one, and never on a
   branch that is not in the stack. Work bottom to top, so that a fix below is
   already restacked under the layers above it before you reach them. For each
   layer with a fix:

   ```
   git switch <layer>
   # ... make the fix, run the layer's tests, commit with a conventional message ...
   git rebase --update-refs <layer> <top>
   ```

   Skip the rebase when the layer is the top. Then run the full test suite and
   linter on the top (in this worktree), and on the merge result again when
   practical (rebuilt from the new top, as in step 4). They must pass.

   Then push. Do not fetch first: the `origin/*` refs from this round's sync are
   what the lease checks. Work out which layers moved against those refs:

   ```
   moved=()
   for b in <branches, bottom to top>; do
     [ "$(git rev-parse "$b")" != "$(git rev-parse "origin/$b")" ] || continue
     moved+=("$b")
   done
   echo "moved: ${moved[*]:-none}"
   ```

   Re-run the mixed stack guard above, then push **everything that moved, in one
   go**, and nothing else. Nothing moved means nothing is pushed: the guard stops
   an empty list from becoming a bare `git push` of the current branch.

   ```
   if (( ${#moved[@]} )); then
     git push --atomic --force-with-lease --force-if-includes origin "${moved[@]}"
   fi
   ```

   Keep the lease implicit: with explicit `--force-with-lease=<ref>:<sha>` values
   git ignores `--force-if-includes`, and a stray fetch would then let the push
   overwrite someone else's commit.

   Never push a layer you did not change or move. If the push is refused, do not
   retry it piecemeal and do not fetch-and-retry: someone else pushed to the stack
   while you worked. Report `blocked` with the refused refs. Otherwise return to 1.

6. **The review found nothing blocking** -> for each layer with non-blocking
   findings you set aside, post **one** PR comment on that layer listing them
   under **Left alone, non-blocking**. Never comment on a layer with nothing to
   list. Report `ready` and stop. That is success, not failure.

**Stop and report immediately, without burning a round, if:** a rebase conflict
needs a judgement call, a test fails for a reason you cannot fix without
guessing at intent, a layer is not yours, a sync or ancestor check fails, or the
change needs a decision only a human can make.

### Reporting

Every stop ends with exactly one report, on the bottom key. Its `<sha>` is the
**top** layer's head (`git rev-parse origin/<top branch>`), not the bottom's: the
orchestrator compares a stack's `ready` report against the top layer's head.

```
$A report "{{KEY}}" <ready|capped|blocked|failed|stalled> <sha> "<one line>"
```

It records the report on your item (the dashboard shows it) and queues the
`OCTOPILOT {{KEY}} <state> <sha> <one line>` message in the orchestrator's
inbox. The first line of the message must be that one line -- the
orchestrator reads it as a status, and a human reads it as a summary. Put any
detail on the lines after it, inside the same quotes. Never message the
orchestrator any other way (typing into its terminal): that types into its pane,
over whatever the user is writing there. Never send desktop notifications
(`PushNotification`) either: the dashboard tells the user when your item needs
them.

If you are going to be working for more than half an hour without pushing and
without a CI wait in flight, call
`$A heartbeat "{{KEY}}" "<what you are doing>"` so the orchestrator does not
report you as stalled. Being reported stalled is harmless; going quiet without
a heartbeat and without a final message is what leaves work stranded.

When the review is over, remove the merge worktree: `git worktree remove --force "$mwt"`
and `rm -rf "$(dirname "$mwt")"`.
