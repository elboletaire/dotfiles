0. On a stack, sync the layers and switch to this one before you read or edit
   anything. Run the sync from the loop below ("Sync the layers"), which leaves
   the worktree on the top layer, then `git switch {{BRANCH}}`. A sync that
   prints `SYNC FAILED` means `blocked`: stop and push nothing. Edits made before
   the sync land on the wrong layer, or make it fail.

`{{BASE}}` in the header above is the stack's base. Only the bottom layer's PR
targets it; every other layer's PR targets the layer directly below it.
