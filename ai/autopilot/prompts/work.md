You are working on {{REPO}} issue #{{ISSUE}}, on branch `{{BRANCH}}` in a
dedicated worktree. Base branch is `{{BASE}}`.

1. `gh issue view {{ISSUE}}` and read it fully, including comments. If the
   issue is ambiguous or turns out to be a discussion rather than a task,
   stop and say so instead of guessing.
2. Explore the codebase and follow its existing patterns. Reuse what is there.
3. Implement the change. Write or update tests.
4. Run the project's full test suite and linter. They must pass.
5. Commit with conventional commit messages.
6. Push and open a PR against `{{BASE}}` with `Closes #{{ISSUE}}` in the body.
7. Report the PR number as the last line of your reply, as `PR: <number>`.

If you get blocked, stop and report what blocked you. Do not open a PR for
work that does not build or whose tests do not pass.

{{HYGIENE}}
