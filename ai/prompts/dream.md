---
description: Sort through agent memories and move each one to where it belongs (repo skill, repo AGENTS.md, global instructions, machine notes) or drop it
argument-hint: "[all | <project path>]"
---

Go through your saved memories and move each one to the place it belongs. Memories stay on this machine, so anything that should hold on every workstation or for every agent has to go into a file that is committed or synced. Scope: $ARGUMENTS (if empty, the current project; `all` means every project under `~/.claude/projects/*/memory/`).

## 1. Gather

- Read every memory file in scope and its `MEMORY.md` index. Read the whole file, not only the index line.
- Read what each memory could move into, so you don't add duplicates: the repo's `AGENTS.md` / `CLAUDE.md` (check which one is the real file and which one only points to the other), its skills (`.claude/skills/`, `.agents/skills/`), the global `~/.claude/CLAUDE.md` and `~/.pi/agent/AGENTS.md`, and `~/.claude/machine.md` if it exists.
- Check each memory against the code and git history. Anything that names a file, flag, command or behaviour must still be true.

## 2. Classify

Put each memory into exactly one bucket:

| Bucket | What goes there | Where it goes |
|---|---|---|
| **Repo skill** | A procedure for this repo that has several steps: how to release, how to add a provider, how to debug some subsystem | `<repo>/.claude/skills/<name>/SKILL.md` (or the skills dir the repo already uses) |
| **Repo instructions** | A short fact or convention about this repo that every agent should know: build or test quirks, layout, "never touch X" | The repo's canonical `AGENTS.md` (or `CLAUDE.md`) |
| **Global instructions** | A preference about how I like to work that isn't tied to one repo | `~/.dotfiles/ai/claude/CLAUDE.md`, plus `~/.dotfiles/ai/pi/AGENTS.md` if pi should follow it too |
| **Machine** | Something true only on this workstation: RAM, CPU or GPU, OS, local paths, installed tool versions, which services run here | `~/.claude/machine.md` (see below) |
| **Keep** | Personal or in-progress context that belongs to this project on this machine and isn't worth committing (an undecided choice, a half-done investigation) | Leave it as a memory |
| **Drop** | Stale, wrong, already said by the code, README or instructions, or only useful in one past conversation | Delete it |

Rules of thumb:
- If a teammate or another of my workstations would want it, it shouldn't stay a memory.
- Prefer one line in `AGENTS.md` over a skill. Make a skill only when it's a procedure of more than a few lines, or something only needed now and then that would bloat `AGENTS.md`.
- The global files live in the dotfiles repo, which every workstation shares. Never put machine facts there.

### Machine facts

`~/.claude/machine.md` holds facts about this one workstation. It is not in dotfiles, and the global `CLAUDE.md` imports it. Pi reads it through `~/.pi/agent/APPEND_SYSTEM.md`, which should be a symlink to it. If either is missing, list creating it as a row in the proposal; don't create anything before I answer.

## 3. Propose

Show the proposal and wait for my answer before you change anything. Steps 1 and 2 only read. With `all`, make one table per project, skip projects with no memories, and number the rows across all tables so each number is unique:

```
## ~/src/manga-downloader
#  memory (file)            bucket          destination                         note
1  low-ram.md               Machine         ~/.claude/machine.md                16 GB, use -p 2 for builds
2  release-flow.md          Repo skill      .claude/skills/release/SKILL.md     merges with notes in 4
3  pnpm-not-npm.md          Drop            -                                   already in AGENTS.md
```

Put what you'd write next to any merge, rewording or new skill. I'll answer with things like `ok`, `ok except 3`, or `2 -> Repo instructions`.

## 4. Apply

- Write the destinations in the style of what's already there. Skills get `name` and a `description` frontmatter that says when to use them. Write the content as an instruction for the agent, not as a note to self.
- Delete each memory you moved or dropped, and remove its line from `MEMORY.md`.
- Don't commit or push. List the files you changed in each repo (the project repo, dotfiles) so I can commit them myself, maybe from another workstation after pulling.
