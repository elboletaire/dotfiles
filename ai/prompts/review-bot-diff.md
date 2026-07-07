---
description: Enter review mode (read-only, plan-based analysis)
---

Review the work done by the previous agent in read-only mode.

Inspect the git log up to the latest published version and review the relevant diffs carefully. Look for matching plans/specs/tasks and use them as the main review units.

Always spawn reviewer subagents:
- If one plan/task is found, spawn one reviewer subagent for it.
- If multiple plans/tasks are found, spawn one reviewer subagent per plan/task.
- If work is not covered by any plan/task, spawn one reviewer subagent for the unplanned work.

Each reviewer should focus only on its assigned plan/task or unplanned work and check plan compliance, correctness, regressions, edge cases, maintainability, and test coverage.

Synthesize all reviewer results into a final review. End with this table:

| Plan or commit name | Plan followed | Execution |
|---|---|---|

