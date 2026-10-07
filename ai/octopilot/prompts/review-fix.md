You own {{REPO}} PR #{{PR}} (branch `{{BRANCH}}`, base `{{BASE}}`).

Do one review round now. Claim it first, as step 3 of "Driving your own
loop" below describes -- the round number it prints decides whether this is
the full round-1 review or a review of your fix diff. Then review exactly as
step 4 describes: pass 1 collects candidates in a fresh subagent, pass 2 verifies
them in a second fresh subagent, and only CONFIRMED findings get fixed. Do not
run the review with `--fix` and do not review in this conversation.

Then:

1. Fix only what pass 2 confirmed, following step 5 below (from round 2 on,
   only blocking findings). Run the full test suite and linter. They
   must pass.
2. Commit the fixes with conventional commit messages.
3. Push to `{{BRANCH}}`, and continue with the loop below from step 1.
4. Report a one-paragraph summary: candidates from pass 1, confirmed and
   rejected in pass 2, what you changed, and anything you deliberately did
   not change.

If nothing blocking is confirmed, say so, push nothing, and report `ready`.

{{LOOP}}

{{HYGIENE}}
