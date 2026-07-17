---
description: Two-model peer-review with cross-validation and confirmed-issues synthesis
argument-hint: "[model1] [model2] [scope]"
---

You are the orchestrator of a two-phase peer-review workflow. Execute the steps below in order.

---

## Step 0 — Resolve models and scope

Raw user-supplied arguments: **$@**

Resolve the reviewer models and review scope using these rules:

1. If no arguments were provided, use these defaults:
   - **Reviewer A model**: `pi-claude-cli/claude-sonnet-4-6`
   - **Reviewer B model**: `zai/glm-5.2`
   - **Scope**: empty
2. If exactly one argument was provided, treat it as the **review scope** and still use the same default models above.
3. If two or more arguments were provided:
   - **Reviewer A model** = `$1`
   - **Reviewer B model** = `$2`
   - **Scope** = `${@:3}`

From this point on, use the resolved values as **Reviewer A model**, **Reviewer B model**, and **resolved scope**.

---

## Step 1 — Determine review scope

Resolved scope: use the scope determined in Step 0.

If the resolved scope is empty, build the diff yourself:
1. Run `git rev-parse --abbrev-ref HEAD` to get the current branch name.
2. Run `git diff origin/<branch>...HEAD` to capture every change since the last push to origin — this includes staged, unstaged, and committed-but-not-yet-pushed changes, not just working-tree modifications.
3. If the branch has no remote tracking branch, fall back to `git diff HEAD~1..HEAD`.

If the resolved scope is not empty, use it as the review target.

Capture the resulting diff or scope as the **review target**. Paste it inline into each reviewer's task prompt.

---

## Step 2 — Check for a plan file

Search for a plan file in this order: `plan.md`, `PLAN.md`, `docs/plan.md`, `docs/PLAN.md`, `planning/*.md`, `docs/superpowers/plans/*.md`.
Also check for files based on the resolved scope (i.e. the argument says to verify phase0 and there's a doc in any of the expected locations named phase0-something.md)
Read the first one found, make sure that's the plan we're looking for, and note its path. If you doubt about the plan, stop and ask the user with your findings, they should clarify which plan to follow or confirm none applies.

Always tell the user which plan file you are using (or that none was found) before proceeding to Step 3. This lets them catch a wrong match early.

If a plan file exists, **both reviewers must evaluate whether the implementation faithfully follows the plan** — missed steps, deviations, and scope creep must all be flagged as issues.

---

## Step 3 — Launch two async reviewers (Phase 1)

Launch **both** reviewer subagents simultaneously with `async: true` and `context: "fresh"`, using the resolved model overrides below. Save both run IDs.

- **Reviewer A** → model = resolved Reviewer A model
- **Reviewer B** → model = resolved Reviewer B model

Each reviewer's task prompt must contain:
- The full review target (diff or scope from Step 1).
- The plan file path and full contents (if found), with this explicit instruction: *"Verify the implementation follows this plan step by step. Any deviation, missing step, or out-of-scope change is a finding."*
- This instruction: *"You are review-only. Do NOT edit any files. Return your findings exclusively as a single Markdown table with columns `| Severity | File/Area | Issue | Recommendation |`. Severity values: Critical / High / Medium / Low / Info. If you find nothing, return an empty table with a short note."*

After launching, inform the user that both reviews are running in the background and the conversation is free.

---

## Step 4 — Wait for Phase 1 results

Wait for each run until both are complete. Only poll `subagent({ action: "status", id: "..." })` if the user explicitly asks to do so. Once both finish, extract the findings tables and display them under clearly labelled headings using the actual resolved model names:

> **Review A — <resolved Reviewer A model>**
> *(table)*
>
> **Review B — <resolved Reviewer B model>**
> *(table)*

---

## Step 5 — Launch two async cross-reviewers (Phase 2)

Each model now peer-reviews the *other* model's findings. Launch both with `async: true` and `context: "fresh"`:

- **Cross-Reviewer 1** → model = resolved Reviewer A model, receives Reviewer B's findings table.
- **Cross-Reviewer 2** → model = resolved Reviewer B model, receives Reviewer A's findings table.

Task prompt for each cross-reviewer:

*"You are given a code-review findings table produced by another model. For each row: (1) verify the issue is real and present in the diff, (2) identify false positives or misreadings, (3) note any significant issue the reviewer clearly missed that you can see from the diff. Return a single Markdown table with columns `| # | Original Issue (brief) | Verdict | Notes |`. Verdict values: Confirmed / False Positive / Needs Clarification."*

Include the original diff (from Step 1) in each cross-reviewer's task so they can validate findings against the actual code.

Save both run IDs.

---

## Step 6 — Wait for Phase 2 results and synthesize

Wait until you get notified both cross-reviews are complete. Then apply these rules to build the final output:

- **Confirmed** — issue raised by a reviewer and upheld (or independently raised) by the cross-reviewer. → Include in final table.
- **False Positive** — issue flagged as "False Positive" by the cross-reviewer. → Move to Discarded section.
- **Needs Clarification** — cross-reviewer is uncertain. → Surface separately.

Present the synthesis in three sections:

---

### ✅ Final Confirmed Issues

| Severity | File/Area | Issue | Source | Recommendation |
|----------|-----------|-------|--------|----------------|

`Source` values: `Both models` / `<resolved Reviewer A model> → upheld by <resolved Reviewer B model>` / `<resolved Reviewer B model> → upheld by <resolved Reviewer A model>`

---

### ❓ Needs Clarification

*(issues where the cross-reviewer could not reach a verdict — include original issue + cross-reviewer's question)*

---

### 🗑️ Disputed / Discarded

*(brief list: original issue + reason it was rejected by the cross-reviewer)*

---

Close with a one-line summary:
**N confirmed · M needs clarification · K discarded**
