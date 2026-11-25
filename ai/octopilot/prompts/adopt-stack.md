You own a stack of PRs in {{REPO}}, base `{{BASE}}`. Bottom to top, each one
targets the one below it, and the bottom targets `{{BASE}}`:

    {{STACK}}

(Each entry is `PR:branch`, in merge order. Every entry is open.) The user owns
every layer: you may fix, rebase and push all of them. The item key is
`{{KEY}}`, the bottom PR's, and rounds, heartbeats and the report all go on it.

Check ownership before anything else, as the loop below describes. If a layer
is not yours, stop there and report `blocked`.

1. **Claim round 1 and review it.** Claim it first, as step 3 of the loop below
   describes -- the round number it prints decides what is reviewed. Then review
   exactly as step 4 describes: the loop syncs the layers and builds the merge
   result of the stack onto the current `{{BASE}}`. One pass-1 subagent per layer
   collects candidates, the stack filter drops what a later layer fixes, and a
   fresh pass-2 subagent per layer verifies the survivors. Do not run the review
   with `--fix` or `--comment`, and do not review in this conversation. The
   stack is restacked onto `{{BASE}}` only when the merge result conflicts; the
   loop says how.

2. **Fix only what pass 2 confirmed**, following step 5 of the loop below (from
   round 2 on, only blocking findings). Each fix goes on the branch of the layer
   its finding is attributed to, and the layers above it are restacked. Run the
   full test suite and linter; they must pass. Push every layer that moved, then
   continue the loop from step 1.

3. **Report a summary, one line per layer**, on the lines after the one-line
   report: candidates from pass 1; dropped by the stack filter, with the layer
   that fixes each; confirmed; rejected; what you changed; and anything you
   deliberately did not change.

If nothing blocking is confirmed, say so, push nothing, and report `ready`.

{{STACK_LOOP}}

{{HYGIENE}}
