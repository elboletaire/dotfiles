<VERY_IMPORTANT>
Read the pi-subagents skill now.

For any non-trivial task, delegation is preferred and should happen immediately; you (the main thread) should generally orchestrate and synthesize rather than do the primary recon, planning, or implementation yourself. If the task is pure read-only review, orchestration, or validation, the main thread may do local analysis when that is more reliable. If unsure whether to delegate, delegate. As soon as you delegate, don't poke the subagents nor repeat the same work the agents are doing; wait until they answer back.

Run subagents async without asking for confirmation. If a default chain is needed, use scout -> planner -> worker -> reviewer, skipping steps that are clearly unnecessary. If I've requested a specific chain order, use it.

NEVER commit plans or specs documents, unless I ask for it.
</VERY_IMPORTANT>

<STARTING_NEW_PROJECTS>
When starting new coding projects, the preferred languages and tools are the following:

- Go
- Typescript
- pnpm
- vite/vitest

If you consider that some of these tools aren't suitable enough and want to propose a different language or toolset, ask directly the user after explaining your issues with the requested toolset.
</STARTING_NEW_PROJECTS>
