---
name: multi-agent-orchestrator
description: 'MULTI-AGENT ONLY: integration phase for worktrees produced by the multi-agent-coder skill. Activate only if EITHER (a) the agent instructions of this repo (AGENTS.md / CLAUDE.md or equivalent) explicitly declare the multi-agent worktree workflow — e.g. a line like "Multi-agent workflow: enabled" — OR (b) the user request explicitly frames the task as multi-agent or parallel-agent work (e.g. "merge the multi-agent worktrees", "集成多个 agent 的任务", "multi-agent session 收尾"). If neither holds, never trigger — no ordinary git merging, no branch cleanup, no single-agent work. Discovers agent/* branches, confirms the merge set with the user, merges sequentially into main with --no-ff, runs the full verification suite once, summarizes, and cleans up after explicit confirmation. Strictly local: never pushes, never fetches.'
license: MIT
allowed-tools: Bash
---

# Multi-Agent Orchestrator: Worktree Integration

## Overview

This skill is the integration half of a two-skill workflow for MULTI-AGENT sessions —
it does not apply to ordinary single-agent git work:

- **multi-agent-coder**: develops tasks in isolated worktrees and marks them `ready`.
- **multi-agent-orchestrator** (this skill): discovers ready worktrees, merges them
  into the base branch (default `main`), verifies the result fully, and deletes
  what is confirmed merged.

Scope gate — activate only when at least one holds:

1. **Repo declaration**: the agent instructions of this repo (AGENTS.md / CLAUDE.md
   or equivalent) explicitly declare the multi-agent worktree workflow, e.g. a line
   like `Multi-agent workflow: enabled`.
2. **Explicit request**: the user explicitly frames the task as multi-agent or
   parallel-agent integration.

Otherwise plain git work needs no skill.

The state machine is: **a local managed worktree exists = pending integration;
deleting it = successfully integrated.** Cleanup is therefore the critical step and
is guarded by explicit user confirmation plus git's own merge-safety checks.

## Shared Conventions (keep in sync with the multi-agent-coder skill)

- Branch: `agent/<type>/<slug>` — `<type>` is a conventional-commit type (`feat`,
  `fix`, `refactor`, `chore`, ...), `<slug>` is short kebab-case.
- Worktree root resolution (in order): (1) if the repo's agent instructions contain a
  line like `Multi-agent worktree-root: ~/code/worktrees`, use that path; (2)
  otherwise the global default `~/.multi-agent-skills/worktrees/`. Worktree path =
  `<resolved-root>/<repo>/<slug>/`, where `<repo>` is the main repo's directory
  basename, with a `-` + 6-hex SHA-256 suffix if disambiguation is needed.
- Base branch: the branch tasks branch from and integrate into. A repo line like
  `Multi-agent base-branch: dev` overrides the default `main`. Coder only reads it;
  only the orchestrator merges and user actions move it.
- Metadata: `.agent-task.md` at the worktree root (untracked) — task, branch, base
  commit, created date, status.
- Status values: `in-progress` → `ready`.
- The loop is local-only: never push, never fetch/pull, never touch the remote.
- Integration always uses `--no-ff` merges; branches are deleted with `-d` only.
- All identity checks anchor to the shared `.git` of the main repo.

## Workflow

### 1. Discover

```bash
git worktree list --porcelain
```

- The first entry is the main worktree — that is where integration happens.
- **Managed** = branch matches `agent/*`. Everything else is displayed for context
  but never touched (user's own worktrees).
- Per managed candidate, collect:
  - branch, path, task description and `status` from `.agent-task.md`
  - ahead count: `git rev-list --count main..<branch>`
  - dirtiness: `git status --porcelain` — modified/staged entries = dirty;
    untracked entries acceptable only if limited to `.agent-task.md` / `.env*`
- Broken or prunable entries (e.g. the repo directory was moved/renamed): report
  them and offer `git worktree repair` or removal.

### 2. Confirm with the user

Present a table: `Branch | Task | Status | Ahead | Verdict`.

- Default merge set: `status: ready` + clean + ahead > 0.
- Show skipped ones with reasons: `in-progress`, dirty (uncommitted work), already
  merged, zero diff.
- Ask the user to confirm the merge set and the target branch (default: the repo's
  base branch, itself defaulting to `main`; explicit overrides are accepted).

### 3. Prepare the base branch

- The main worktree must be checked out on the base branch (default `main`) with no
  modified/staged changes. Otherwise stop and ask the user to settle it (commit,
  stash, or switch).
- Do not fetch or pull — this workflow is local-first.
- Record the current base-branch HEAD for the final report.

### 4. Merge sequentially

In the confirmed order, one branch at a time:

```bash
git merge --no-ff agent/<type>/<slug>
```

`--no-ff` keeps a merge commit per branch, which makes precise reverts possible.

Conflict protocol:

1. Inspect `git status` and the conflicted files.
2. Auto-resolve only low-risk patterns: independent additions on both sides
   (union), non-overlapping import lines. Lockfiles are never resolved by picking a
   side — regenerate them with the project's package manager.
3. Never commit conflict markers; never use `--ours`/`--theirs` blindly.
4. Not confident → `git merge --abort`, leave the branch untouched, show the user
   the conflicting files plus the branch's diff context, and ask: resolve manually /
   skip this branch / stop everything.

### 5. Verify once, fully

After all merges (batch testing by design — no per-merge runs):

- Run the full test suite + lint + build in the main worktree, following the repo's
  own conventions (`AGENTS.md`, `justfile`, `Makefile` win). Inform the user if the
  run exceeds ~30 minutes.
- On failure, run the **attribution protocol**:
  1. Freeze the list of failing tests (names and files).
  2. Walk the merge commits from newest to oldest: `git revert -m 1 <merge-sha>`,
     then re-run **only the failing subset** (seconds, not a full re-run).
  3. First revert that turns the subset green identifies the culprit. Leave the
     culprit's merge reverted on the base branch; its worktree and branch stay
     intact for the coder to fix (its future re-merge after a rebase onto the base
     branch carries the fix correctly).
  4. Report the culprit and ask the user how to proceed with the remaining merged
     branches.

### 6. Summarize

Report:

- merged branches with their merge commit SHAs
- conflicts encountered and how each was resolved
- verification results (or the attribution outcome and the reverted culprit)
- skipped branches and why

### 7. Clean up after confirmation

Candidates: every branch successfully merged this session, plus stale managed
branches already contained in `main` from earlier sessions. Confirm the deletion
list with the user first — **never delete anything unconfirmed**, and never delete
non-managed worktrees.

Per confirmed item:

```bash
git worktree remove <resolved-root>/<repo>/<slug>
git branch -d agent/<type>/<slug>
rmdir <resolved-root>/<repo>   # only if left empty
```

- If `git worktree remove` refuses (unexpected untracked or modified files), list
  those files and ask; only use `--force` after the user approves. Never force
  blindly — the user may keep personal files in a worktree.
- `git branch -d` refuses unmerged branches — that refusal is a safety net, never
  work around it with `-D`.

## Hard Rules

- Local-only: no push, no fetch, no pull.
- Never rewrite base-branch history — no `reset`, no `rebase` on it.
- `git branch -d` only; `--force` variants only after explicit user approval.
- Merge target defaults to the repo's base branch (itself defaulting to `main`);
  accept an explicit user override for one run.
