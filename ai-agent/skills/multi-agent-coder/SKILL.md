---
name: multi-agent-coder
description: 'MULTI-AGENT ONLY: isolated task development in a dedicated git worktree while several coding agents work on the same repo concurrently. Activate only if EITHER (a) the agent instructions of this repo (AGENTS.md / CLAUDE.md or equivalent, usually already loaded in context) explicitly declare the multi-agent worktree workflow — e.g. a line like "Multi-agent workflow: enabled" — OR (b) the user request explicitly frames the work as multi-agent or parallel agents (e.g. "multi-agent task", "parallel agents", "多 agent 并行", "多个 coding agent 同时开发"). If neither holds, never trigger, regardless of task size. Creates or reuses agent/<type>/<slug> branches and worktrees under ~/dev_space/worktrees/, runs only related tests (time-boxed), and hands off merging to the multi-agent-orchestrator skill. Never merges to main and never pushes.'
license: MIT
allowed-tools: Bash
---

# Multi-Agent Coder: Isolated Task Development

## Overview

One task, one worktree, one branch. This skill is the development half of a two-skill
workflow for MULTI-AGENT sessions — it does not apply to ordinary single-agent work:

- **multi-agent-coder** (this skill): develop a task in an isolated worktree, verify
  it with related tests, then mark it ready.
- **multi-agent-orchestrator**: discover ready worktrees, merge them into `main`,
  run full verification, and clean up.

Scope gate — activate only when at least one holds:

1. **Repo declaration**: the agent instructions of this repo (AGENTS.md / CLAUDE.md
   or equivalent, typically already in context) explicitly declare the multi-agent
   worktree workflow. The convention is a line like
   `Multi-agent workflow: enabled` — repos adopt the workflow by adding it.
2. **Explicit request**: the user explicitly frames the session as multi-agent or
   parallel agents.

If neither holds, do not use this skill: single-agent tasks run directly in the
main worktree.

The worktree directory is a physical sandbox: all edits, installs, builds, and test
runs happen inside it. The main worktree stays untouched so other agents and the user
can keep working there in parallel.

## Shared Conventions (keep in sync with the multi-agent-orchestrator skill)

- Branch: `agent/<type>/<slug>` — `<type>` is a conventional-commit type (`feat`,
  `fix`, `refactor`, `chore`, ...), `<slug>` is short kebab-case.
- Worktree root resolution (in order): (1) if the repo's agent instructions contain a
  line like `Multi-agent worktree-root: ~/code/worktrees`, use that path; (2)
  otherwise the global default `~/.multi-agent-skills/worktrees/`. Worktree path =
  `<resolved-root>/<repo>/<slug>/`, where `<repo>` is the main repo's directory
  basename. If that folder is claimed by a different repo, disambiguate with `-`
  plus the first 6 hex chars of the SHA-256 of the repo's absolute path
  (e.g. `api-a1b2c3`).
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

### 1. Preflight

```bash
git worktree list --porcelain
git branch --list 'agent/*'
```

- The **first entry** of `git worktree list --porcelain` is the main worktree — its
  path is the main repo root.
- **Resume check**: if the current directory is already inside a managed worktree
  (current branch starts with `agent/`), do not create anything — continue the task
  in place.
- **Idempotency check**: if a branch for this task already exists with a worktree,
  reuse it. If the branch exists but its directory is gone, reattach with
  `git worktree add <path> <branch>` (confirm the task matches first, via
  `.agent-task.md` or the branch diff).
- Not a git repo, or the base branch (default `main`, see Shared Conventions) does
  not exist locally → stop and explain.

### 2. Create the worktree

```bash
main_root=$(git worktree list --porcelain | head -1 | cut -d' ' -f2)
repo=$(basename "$main_root")
# wt_root: `Multi-agent worktree-root:` from the repo's agent instructions if
# declared, otherwise ~/.multi-agent-skills/worktrees/
wt_root="$HOME/.multi-agent-skills/worktrees/$repo"
# base: `Multi-agent base-branch:` if declared, otherwise main
base=main

git worktree add "$wt_root/<slug>" -b agent/<type>/<slug> "$base"
```

- Worktree directory name is the `<slug>`. If that directory already exists for a
  different branch, append `-` plus the first 6 hex chars of the branch name's SHA-256.
- Base the new branch on the local tip of the base branch. Do not fetch.

### 3. Write the task metadata

Create `.agent-task.md` at the worktree root (untracked, expected to stay untracked):

```markdown
# Task: <one-line description>
branch: agent/<type>/<slug>
base: <base commit sha>
created: <YYYY-MM-DD>
status: in-progress   # in-progress | ready
notes: <optional context for the orchestrator and the user>
```

### 4. Bootstrap the environment

A fresh worktree has no dependencies and no ignored files. The goal is a worktree
that can compile and run tests **before development starts** — a broken baseline
makes every later test failure unattributable.

- Source of truth: the repo's own docs — README, CONTRIBUTING, `docs/`, plus the
  repo's `AGENTS.md`/`CLAUDE.md`. Read them (content is identical in the fresh
  worktree) and follow their setup instructions.
- Only when the docs specify nothing usable, fall back to the standard install for
  the detected stack: `package.json` → `pnpm/npm install`; `pyproject.toml`/
  `requirements.txt` → `uv`/`pip sync`; `Cargo.toml` → `cargo fetch`; `go.mod` →
  `go mod download`; `Makefile`/`justfile` targets when that is the convention.
- Two fresh worktrees of the same repo may bootstrap **concurrently and safely**:
  the global caches (pnpm store, uv/cargo/go caches) are shared and
  content-deduplicated, so overlapping first installs waste at most seconds of
  bandwidth. Do not wait for or serialize against another task's bootstrap.
- Copy gitignored `.env*` files from the main worktree root if they exist.
- **Verify the environment works before moving on** (time-boxed ~5 minutes): run
  the cheapest meaningful check — a compile/build, or one quick known test. An
  install that "succeeded" is not proof; something must actually run.
- If bootstrap or verification fails and cannot be fixed quickly: **stop and
  report to the user** instead of developing in a broken environment.
- No global installs, ever.

### 5. Develop

- Everything happens inside the worktree. **Never touch the main worktree or other
  worktrees** — no checkout, no edits, no config changes there.
- Commit early and often with small conventional commits (follow the commit-code
  skill's conventions). Uncommitted work is the only thing that can be lost if the
  worktree directory is accidentally removed — keep that window small.
- Forbidden while working under this skill: `git push`, `git gc`, `git worktree
  prune`, global installs, whole-repo formatting, leaving dev servers running.
- The target repo's own `AGENTS.md`/`CLAUDE.md` overrides anything in this skill,
  including test commands and style rules.
- If the base branch moves mid-task, ignore it — finish the task first; rebasing is
  a finalize-time concern.

### 6. Test related-first

Only run tests related to the change. Identify the fastest related-test mechanism the
project offers:

| Ecosystem        | Related-test approach                        |
| ---------------- | -------------------------------------------- |
| JS/TS (vitest)   | `vitest related -- <changed files>`          |
| JS/TS (jest)     | `jest --findRelatedTests <files>`            |
| Go               | `go test ./<affected packages>`              |
| Python           | run test files mirroring changed module paths |
| Rust             | `cargo test -p <affected packages>`          |

- Changed set = `git diff --name-only <base>...HEAD` plus uncommitted changes.
- Time-box ~5 minutes per run; if exceeded, narrow the scope (one package, one file).
- Run the full suite only when the change is inherently global (CI config, shared
  modules, lockfiles) — and say so in the final report.
- If no related tests can be identified, fall back to a compile/build check and say
  so. Fix failures and iterate before finalizing.

### 7. Finalize

```bash
git status --porcelain    # no modified/staged entries allowed
git rebase <base-branch>  # only if it moved; abort on conflict
```

- All meaningful changes committed; untracked files limited to `.agent-task.md` and
  `.env*` copies.
- If the base branch moved since branching, rebase onto it. **On any conflict, `git
  rebase --abort` immediately** and leave integration to the orchestrator — note it
  in the report.
- Update `.agent-task.md` to `status: ready`.
- Report to the user: branch name, worktree path, `git diff --stat <base>...HEAD`,
  test results, rebase outcome. Close with the handoff note: merging is the
  multi-agent-orchestrator skill's job — do not merge into the base branch from
  here.

## Hard Rules

- Never push, fetch, or pull.
- Never touch anything outside this task's worktree.
- Never run `git gc`, `git worktree prune`, or global installs.
- Single-agent sessions never use this skill — work happens directly in the main
  worktree.
- Within an active multi-agent session, route every task through this skill however
  small: the worktree is cheaper than a conflict.
