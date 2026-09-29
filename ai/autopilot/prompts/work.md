You are working on {{REPO}} issue #{{ISSUE}}, on branch `{{BRANCH}}` in a
dedicated worktree. Base branch is `{{BASE}}`.

The issue is reproduced verbatim below -- title, body and every comment. Read
it before anything else. If it is ambiguous, or turns out to be a discussion
rather than a task, stop and say so instead of guessing.

{{CONTEXT}}

Only run `gh issue view {{ISSUE}} -R {{REPO}} --comments` if you need something
the text above cannot carry: an image, a linked issue, or a comment posted
after this prompt was written.

Then:

1. Explore the codebase and follow its existing patterns. Reuse what is there.
2. Implement the change. Write or update tests.
3. Run the project's full test suite and linter. They must pass.
4. Commit with conventional commit messages.
5. Push and open a PR against `{{BASE}}` with `Closes #{{ISSUE}}` in the body.
6. Report the PR number as the last line of your reply, as `PR: <number>`.

If you get blocked, stop and report what blocked you. Do not open a PR for
work that does not build or whose tests do not pass.

{{LOOP}}

{{HYGIENE}}
