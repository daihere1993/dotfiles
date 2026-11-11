---
name: multi-agent-orchestrator
description: 'MULTI-AGENT ONLY: integration phase for agent/* branches produced by the multi-agent-coder skill running in host-managed worktrees (Zed worktree isolation or equivalent). Activate only if EITHER (a) the agent instructions of this repo (AGENTS.md / CLAUDE.md) declare the multi-agent worktree workflow — e.g. a line like "Multi-agent workflow: enabled" — OR (b) the user explicitly frames the task as multi-agent or parallel-agent work (e.g. "merge the multi-agent worktrees", "集成多个 agent 的任务"). If neither holds, never trigger — no ordinary git merging, no branch cleanup, no single-agent work. Discovers agent/* branches, confirms the merge set with the user, merges sequentially into the base branch with --no-ff, runs full verification once and fixes failures forward (never by reverting), summarizes, and cleans up after explicit confirmation. Strictly local: never pushes, never fetches.'
license: MIT
allowed-tools: Bash, Read, Edit, Write, Grep, Glob
---

# Multi-Agent Orchestrator: Worktree Integration

## Overview

This skill is the integration half of a two-skill workflow for MULTI-AGENT sessions —
it does not apply to ordinary single-agent git work:

- **multi-agent-coder**: develops tasks in isolated worktrees and marks them `ready`.
- **multi-agent-orchestrator** (this skill): discovers ready `agent/*` branches,
  merges them into the base branch (default `main`), verifies the result fully, and
  deletes the confirmed-merged branches.

Scope gate — activate only when at least one holds:

1. **Repo declaration**: the agent instructions of this repo (AGENTS.md / CLAUDE.md
   or equivalent) explicitly declare the multi-agent worktree workflow, e.g. a line
   like `Multi-agent workflow: enabled`.
2. **Explicit request**: the user explicitly frames the task as multi-agent or
   parallel-agent integration.

Otherwise plain git work needs no skill.

The state machine is: **a managed `agent/*` branch not contained in the base branch
= pending integration; a branch contained in the base branch, deleted after
confirmation = integrated.** Worktrees are host-managed (the editor may delete one
when its thread is archived) and are never the source of truth. Cleanup is guarded
by explicit user confirmation plus git's own merge-safety checks.

## Shared Conventions (keep in sync with the multi-agent-coder skill)

- Branch: `agent/<type>/<slug>` — both parts are derived by the agent from the
  task itself: `<type>` is the conventional-commit type (`feat`, `fix`,
  `refactor`, `chore`, ...), `<slug>` is a short English kebab-case name (at most
  ~3 words) summarizing the task — translate it if the task is described in
  another language. A user-provided slug overrides the generated one.
- Worktrees are host-managed (created and removed by the editor, e.g. Zed worktree
  isolation): their presence is informational only. Branches are the source of
  truth for what is pending integration.
- Base branch: the branch tasks branch from and integrate into. A repo line like
  `Multi-agent base-branch: dev` overrides the default `main`. Coder only reads it;
  only the orchestrator merges and user actions move it.
- Readiness: a git note on the branch tip — `git notes --ref=agent-task show
  <branch>` reading `status: ready`. A missing note means `in-progress`/unknown.
  Task context comes from the branch's own commits (`git log <base>..<branch>`).
- The loop is local-only: never push, never fetch/pull, never touch the remote.
- Integration always uses `--no-ff` merges; branches are deleted with `-d` only.
- All identity checks anchor to the shared `.git` of the main repo.

## Workflow

### 1. Discover

```bash
git for-each-ref --format='%(refname:short)' refs/heads/agent/
git worktree list --porcelain
```

- The first worktree entry is the main worktree — that is where integration
  happens.
- **Managed** = any local branch matching `agent/*`. Branches are the source of
  truth; worktrees are host-managed context. A managed branch whose worktree has
  disappeared (e.g. its Zed thread was archived) is normal, not an error.
- Per managed candidate, collect:
  - readiness: `git notes --ref=agent-task show <branch>` → `status: ready`;
    a missing note means `in-progress`/unknown
  - task description: the branch's first commit subject,
    e.g. `git log --format=%s -1 <branch>`
  - ahead count: `git rev-list --count <base>..<branch>`
  - already merged: `git merge-base --is-ancestor <branch> <base>`
  - dirtiness: `git -C <worktree-path> status --porcelain` when the worktree still
    exists — modified/staged entries = dirty; untracked entries acceptable
- Broken or prunable worktree entries (e.g. the directory was moved/renamed):
  report them and offer `git worktree repair` or removal.

### 2. Confirm with the user

Present a table: `Branch | Task | Status | Ahead | Verdict`.

- Default merge set: readiness note `status: ready` + clean + ahead > 0.
- Show skipped ones with reasons: no readiness note (`in-progress`), dirty
  (uncommitted work), already merged, zero diff.
- Ask the user to confirm the merge set and the target branch (default: the repo's
  base branch, itself defaulting to `main`; explicit overrides are accepted).
- At confirmation time, record each confirmed branch's tip SHA
  (`git rev-parse <branch>`): what gets merged must be exactly what was
  confirmed — a coder finishing its finalize rebase in parallel must not silently
  change the integration content.

### 3. Prepare the base branch

- The main worktree must be checked out on the base branch (default `main`) with no
  modified/staged changes. Otherwise stop and ask the user to settle it (commit,
  stash, or switch).
- Do not fetch or pull — this workflow is local-first.
- Record the current base-branch HEAD for the final report.

### 4. Merge sequentially

In the confirmed order, one branch at a time. Before each merge, verify the branch
tip still matches the SHA recorded at confirmation (`git rev-parse <branch>`);
if it moved — a coder finalized after you confirmed — stop and ask: take the new
tip or re-confirm. Then:

```bash
git merge --no-ff agent/<type>/<slug>
```

`--no-ff` keeps a merge commit per branch, so each task's contribution stays a
visible, self-contained unit in history.

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
- On failure, **fix forward — never revert or undo merged work**:
  1. Freeze the list of failing checks (test names/files, lint or build errors).
  2. Diagnose the root cause: read the failures and map them to the merged
     branches (`git log <recorded-head>..HEAD`, per-branch diffs). The failure may
     be one branch's bug or an interaction between two branches.
  3. Fix it directly on the base branch as a new conventional commit, then re-run
     **only the failing subset** to confirm. If the proper fix is too large for an
     integration session, stop and report; the follow-up work goes through the
     coder skill as a new task.
  4. If the failure cannot be fixed quickly or confidently, stop: report the
     failing output, the suspected branch(es) and their diffs, and ask the user
     how to proceed. Offer no cleanup for branches implicated in an unresolved
     failure.

### 6. Summarize

Report:

- merged branches with their merge commit SHAs
- conflicts encountered and how each was resolved
- verification results, plus any fix-forward commits made on the base branch
- skipped branches and why

### 7. Clean up after confirmation

Candidates: every branch successfully merged this session, plus stale managed
branches already contained in the base branch from earlier sessions. Confirm the
deletion list with the user first — **never delete anything unconfirmed**.

Per confirmed item:

```bash
git branch -d agent/<type>/<slug>
```

- Worktrees are host-managed: never remove them yourself. Deleting the branch is
  the integration record; the editor removes the worktree with its own thread
  lifecycle (Zed also recreates a worktree automatically if its thread is
  restored from history).
- If `git branch -d` fails because the branch is still checked out in a live
  worktree, ask the user to close/archive that agent thread first, then retry.
  Only with explicit user approval may you `git worktree remove` that worktree
  first — never force blindly, the user may keep personal files in it.
- `git branch -d` refuses unmerged branches — that refusal is a safety net, never
  work around it with `-D`.

## Hard Rules

- Local-only: no push, no fetch, no pull.
- Never rewrite base-branch history — no `reset`, no `rebase` on it.
- Never revert or undo merged work — verification failures are fixed with new
  commits on the base branch.
- Never remove host-managed worktrees — the editor owns their lifecycle.
- `git branch -d` only; `--force` variants only after explicit user approval.
- Merge target defaults to the repo's base branch (itself defaulting to `main`);
  accept an explicit user override for one run.
