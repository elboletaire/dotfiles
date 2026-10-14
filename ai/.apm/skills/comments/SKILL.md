---
name: comments
description: Use whenever writing, adding, editing or reviewing code comments (doc comments, inline comments, JSDoc), and when asked to trim, shorten or clean up comments, on a branch or across a whole project, package or folder. Keeps comments to 1-3 lines that carry the why, and trims existing ones without losing anything only they said.
---

# Code comments

- **Trimming comments** (`/comments trim` for a branch, `/comments trim project [path]` for the whole project or a folder, a request to trim or clean them up, or a diff that adds blocks over 3 lines): follow [trim.md](trim.md).
- **Anything else:** the rules below apply every time you write or change a comment.

## Writing comments

- **Length:** 1-3 lines per block, most of them 1-2. This includes doc comments on exported identifiers.
- **Content:** say the why, or a constraint the code can't show:
  - an external API's quirk,
  - a rate limit,
  - an ordering requirement,
  - an edge case handled silently,
  - why the obvious approach doesn't work.
- **Don't:**
  - restate what the code does,
  - narrate history ("used to", "now", "before this change", the PR or issue story),
  - record measurements,
  - list examples where one does.
- **Don't repeat documented flows.** If a flow is already explained in the repo's docs (README, AGENTS.md/CLAUDE.md, skills, `docs/`) or in another comment of the same package, point to it in a few words instead of repeating it.
- **Claims must match the code.** A comment must not say less or more than the code does.
- **Style:**
  - follow the language's doc-comment convention (Go: start with the identifier's name),
  - match the surrounding comments' punctuation and line width,
  - keep sentences grammatical. Don't telegraph.
- **Before committing:** check the diff for added comment blocks over 3 lines, and trim any with [trim.md](trim.md).
