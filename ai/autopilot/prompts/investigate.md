You are investigating something in {{REPO}}, on branch `{{BRANCH}}` in a
dedicated worktree. Base branch is `{{BASE}}`.

The question, verbatim from the user:

> {{QUESTION}}

1. Investigate first. Read the code, follow the imports, check the build and
   deploy config. Establish what is actually happening before changing
   anything, and say which parts you verified versus assumed.
2. If the answer is "nothing needs to change", stop and report that. Do not
   invent work to justify the session.
3. If a change is warranted, make it: follow the existing patterns, write or
   update tests, and keep the diff to what the question asks for.
4. Run the project's full test suite and linter. They must pass.
5. Commit with conventional commit messages.
6. Push and open a PR against `{{BASE}}` explaining what you found and why
   the change fixes it. Report the PR number as the last line of your reply,
   as `PR: <number>`.

If the investigation crosses into another repository, say so in your report
rather than trying to change it from here -- this worktree only covers
{{REPO}}.

If you get blocked, stop and report what blocked you.

{{LOOP}}

{{HYGIENE}}
