You own {{REPO}} PR #{{PR}} (branch `{{BRANCH}}`, base `{{BASE}}`).

Do one review round now, exactly as step 4 of "Driving your own loop" below
describes: pass 1 collects candidates in a fresh subagent, pass 2 verifies
them in a second fresh subagent, and only CONFIRMED findings get fixed. Do not
run the review with `--fix` and do not review in this conversation.

Then:

1. Fix only what pass 2 confirmed. Run the full test suite and linter. They
   must pass.
2. Commit the fixes with conventional commit messages.
3. Push to `{{BRANCH}}`, and continue with the loop below from step 1.
4. Report a one-paragraph summary: candidates from pass 1, confirmed and
   rejected in pass 2, what you changed, and anything you deliberately did
   not change.

If nothing is confirmed, say so, push nothing, and report `ready`.

{{LOOP}}

{{HYGIENE}}
