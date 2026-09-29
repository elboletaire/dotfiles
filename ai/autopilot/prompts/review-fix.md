You own {{REPO}} PR #{{PR}} (branch `{{BRANCH}}`, base `{{BASE}}`).

Run: {{REVIEW_CMD}} {{REVIEW_LEVEL}} --fix {{PR}}

Then, after the review has applied its fixes:

1. Run the full test suite and linter. They must pass.
2. Commit the fixes with conventional commit messages.
3. Push to `{{BRANCH}}`.
4. Report a one-paragraph summary: what the review found, what you changed,
   and anything you deliberately did not change.

If the review finds nothing, say so and push nothing.

{{LOOP}}

{{HYGIENE}}
