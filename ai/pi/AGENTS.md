<VERY_IMPORTANT>
Read the pi-subagents skill now.

When running subagents, do it async without asking for confirmation. If a default chain is needed, use scout -> planner -> worker -> reviewer, skipping steps that are clearly unnecessary. If I've requested a specific chain order, use it.

NEVER commit plans or specs documents, unless I ask for it.

Before writing a pull request, issue, review, review comment or commit message, read the contributing skill and follow it.

Before writing code, read the comments skill and follow it for every comment added or changed, and have subagents that write code do the same.
</VERY_IMPORTANT>

<STARTING_NEW_PROJECTS>
When starting new coding projects, the preferred languages and tools are the following:

- Go
- Typescript
- pnpm
- vite or tsdown
- vitest
- up-fetch

If you consider that some of these tools aren't suitable enough and want to propose a different language or toolset, ask directly the user after explaining your issues with the requested toolset.
</STARTING_NEW_PROJECTS>

This file is shared by all my workstations through dotfiles. Facts about the current machine only (hardware, OS, local paths, installed tools) go in `~/.claude/machine.md`, which stays on that machine; `~/.pi/agent/APPEND_SYSTEM.md` is a symlink to it, so it is already loaded. Create both if missing.

@~/.claude/machine.md
