# Trimming a branch's comments

Comments only: never change code. What a good comment says is in [SKILL.md](SKILL.md).

## 1. Scope

1. **Base:** use the ref you were given, or else the merge base with the remote default branch (`git fetch`, then `origin/HEAD`, else `origin/main` or `origin/master`). Read `git diff <base>...HEAD`, plus uncommitted changes if the tree is dirty.
2. **A block** is a run of consecutive comment lines.
3. **In scope** means one of:
   - the branch created the block, or
   - the block existed on the base and the branch made it longer. Compare with `git show <base>:<file>`.
4. **Out of scope:** everything else stays exactly as it is, however long. That includes blocks the branch only edited, shortened or left at the same length.
5. **Skip:**
   - generated files: bindings, `*.pb.go`, lockfiles, vendored code,
   - docs: README, AGENTS.md/CLAUDE.md, skills, `docs/`.

## 2. Trim each in-scope block over 3 lines

For every piece of information you'd drop, classify it:
- **(a) The code says it:** names, logic or types make it obvious. Drop it.
- **(b) It's documented elsewhere:** in the repo's docs or another comment in the same package. Search for it and note the file and line. Drop it, or leave a short pointer.
- **(c) It's only here:** if it's a real constraint, a non-obvious why or a gotcha, it **must stay**.
  - Rework the comment so it fits in 3 lines and still carries it,
  - or move it to the line or field it concerns, still within 3 lines.

Then:
- **Always drop:** restated code, history and narration, measurements.
- **Keep the core message:** the comment still answers what a reader would ask at that spot.
- **Check each claim against the code:** a trimmed comment must not be narrower or broader than what the code does. For example, "an unknown X is an error" is wrong when the code also lets a no-X case through.
- **Look again:** check for in-scope blocks you missed that are still over 3 lines.

## 3. Who does it

- **Use judgement:** this needs judgement on every block, so do it yourself, or delegate to a subagent on the strongest model available. This overrides any rule that sends code changes to a small worker model.
- **Never a small model:** don't hand it to a small, fast model. It drops constraints that were only stated in the comment.
- **Large diffs:** split them by package or module across several such subagents.

## 4. Verify

- **Comments only:** the diff contains no code changes beyond what the formatter does.
- **Formatter:** gofmt, prettier or the project's equivalent is clean on the touched files.
- **Checks:** build, vet or lint, and tests pass for the touched modules.
- **No commit:** leave the result for review.

## 5. Report

- **One entry per block**, a table when there are more than a few:
  - file:identifier,
  - in scope (created, or grown from N to M lines) or out of scope (why),
  - what was dropped,
  - where that lives: code / file:line / doc section, or "only here: kept".
- **Restored or reworked:** the blocks restored to their original text or reworked to keep a constraint.
- **Leftovers:** any in-scope block still over 3 lines. There should be none; if there is one, say why.
- **Stale docs:** docs that pointed at a shortened comment and now read wrong. List them; don't fix docs unasked.
- **Verification results.**
