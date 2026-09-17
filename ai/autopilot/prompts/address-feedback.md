New review feedback landed on {{REPO}} PR #{{PR}} (branch `{{BRANCH}}`,
base `{{BASE}}`).

1. `gh pr view {{PR}} -R {{REPO}} --comments` and read every review and comment
   you have not already handled, including inline review comments
   (`gh api repos/{{REPO}}/pulls/{{PR}}/comments`).
2. Address each point. If you disagree with one, do not silently skip it --
   reply to it on GitHub explaining why.
3. Run the full test suite and linter.
4. Commit and push to `{{BRANCH}}`.
5. Report point by point: what you changed, and what you pushed back on.

Feedback from a human reviewer outranks feedback from a bot. If the two
conflict, follow the human and say so.

{{HYGIENE}}
