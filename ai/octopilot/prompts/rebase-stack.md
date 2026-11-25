{{REPO}} moved `{{BASE}}` under a stack. Bring the open layers below up to date.
Bottom to top, each PR targets the one under it, and the bottom targets `{{BASE}}`:

    {{STACK}}

Every entry is an open PR: layers that already merged have been dropped from the
list, so the bottom is the first open layer. The item key is `{{KEY}}`, the
bottom open PR's. Restack base (the head of the topmost layer that merged, set
only right after a merge; empty otherwise): `{{RESTACK_FROM}}`

Check ownership of every layer first, as the loop below describes.

1. **Fetch and sync.** `git fetch origin`. Only when the restack base is set (the
   value above is not empty): if the merged layer's head is not here
   (`git cat-file -e <restack base>` fails), find its PR number by head sha, then
   fetch its PR head:

   ```
   base=<restack base>
   n=$(gh pr list -R {{REPO}} --state merged --limit 200 --json number,headRefOid -q ".[] | select(.headRefOid == \"$base\") | .number")
   git fetch origin "refs/pull/$n/head"
   git cat-file -e "$base"
   ```

   If `cat-file` still fails, report `blocked`. Then sync the open layers as the
   loop below describes; a sync failure means `blocked`, with nothing pushed.

2. **Pick the upstream.** The commits to replay are the open layers' own.
   - Restack base empty: no merge happened under the stack, so the upstream is
     the fork point of the bottom, `git merge-base origin/{{BASE}} origin/<bottom>`.
   - Restack base set: the merged layer may be squashed into `{{BASE}}`, so it is
     not an ancestor of it. The upstream is the merged head, as long as the first
     open layer still descends from it: `git merge-base <restack base> origin/<bottom>`.

3. **Restack onto `origin/{{BASE}}`**, moving every layer ref with `--update-refs`:

   ```
   git rebase --onto origin/{{BASE}} <upstream> <top> --update-refs
   ```

   Resolve conflicts. If a conflict is ambiguous -- if resolving it means
   guessing at intent rather than mechanically combining changes -- stop, leave
   the rebase in progress, and report exactly which files and hunks you could not
   resolve. Do not guess. A layer you resolved mechanically is one the loop's
   review must cover. Afterwards check that each open layer is an ancestor of the
   one above it. **A failed check means the restack is wrong: push nothing and
   report `blocked`.**

4. Run the full test suite and linter. If they fail after a clean rebase, fix
   them, on the layer they belong to.

5. **Push, without fetching first.** The `origin/*` refs from step 1 are what the
   lease checks, so `git fetch` between the sync and the push would defeat it.
   Work out which open layers moved against those refs:

   ```
   moved=()
   for b in <open layers, bottom to top>; do
     [ "$(git rev-parse "$b")" != "$(git rev-parse "origin/$b")" ] || continue
     moved+=("$b")
   done
   if (( ${#moved[@]} )); then
     git push --atomic --force-with-lease --force-if-includes origin "${moved[@]}"
   fi
   ```

   That is one atomic push of every layer that moved, and nothing else. Nothing
   moved means nothing is pushed.

   Keep the lease implicit: explicit `--force-with-lease=<ref>:<sha>` values make
   git ignore `--force-if-includes`.

   If the push is refused, report `blocked`: someone pushed to the stack while you
   worked, and the refused refs are theirs to reconcile.

6. If the bottom PR's base is not `{{BASE}}` (`gh pr view <bottom> -R {{REPO}}
   --json baseRefName`), make it so: `gh pr edit <bottom> -R {{REPO}} --base {{BASE}}`.

Report: whether the restack was clean, what you resolved, the upstream you used,
the test result, and whether you pushed.

{{STACK_LOOP}}

{{HYGIENE}}
