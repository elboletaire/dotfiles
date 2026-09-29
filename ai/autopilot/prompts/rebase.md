{{REPO}} merged something into `{{BASE}}`. Bring branch `{{BRANCH}}`
(PR #{{PR}}) up to date.

1. `git fetch origin`
2. Rebase onto `origin/{{BASE}}`.
3. Resolve conflicts. If a conflict is ambiguous -- if resolving it means
   guessing at intent rather than mechanically combining changes -- stop,
   leave the rebase in progress, and report exactly which files and hunks
   you could not resolve. Do not guess.
4. Run the full test suite. If it fails after a clean rebase, fix it.
5. `git push --force-with-lease`

Report: whether it was clean, what you resolved, test result, pushed or not.

{{LOOP}}

{{HYGIENE}}
