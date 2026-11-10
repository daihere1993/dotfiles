---
name: multi-agent-coder
description: 'MULTI-AGENT ONLY: task discipline for coding agents running in host-managed git worktrees (Zed worktree isolation or equivalent) while several agents work on the same repo in parallel. Activate only if EITHER (a) the agent instructions of this repo (AGENTS.md / CLAUDE.md or equivalent, usually already loaded in context) explicitly declare the multi-agent worktree workflow — e.g. a line like "Multi-agent workflow: enabled" — OR (b) the user request explicitly frames the work as multi-agent or parallel agents (e.g. "multi-agent task", "parallel agents", "多 agent 并行", "多个 coding agent 同时开发"). If neither holds, never trigger. This skill never creates or manages worktrees — isolation belongs to the host editor; if the session is not inside a linked worktree, stop and tell the user to spawn one there. Sets up the agent/<type>/<slug> branch, bootstraps and verifies the environment, runs only related tests (time-boxed), marks readiness with a git note on the branch tip, and hands off merging to the multi-agent-orchestrator skill. Never merges and never pushes.'
license: MIT
allowed-tools: Bash, Read, Edit, Write, Grep, Glob
---

# Multi-Agent Coder: Task Discipline in a Host-Managed Worktree

## Overview

One task, one worktree, one branch. Isolation is the host editor's job (Zed's
worktree picker or equivalent): the thread runs inside a linked worktree, and this
skill owns only the task discipline on top of it. It is the development half of a
two-skill workflow:

- **multi-agent-coder** (this skill): set up the branch, bootstrap and verify the
  environment, develop, run related tests, mark the branch ready.
- **multi-agent-orchestrator**: discover ready `agent/*` branches, merge them into
  the base branch, run full verification, and clean up.

Scope gate — activate only when at least one holds:

1. **Repo declaration**: the agent instructions of this repo (AGENTS.md / CLAUDE.md
   or equivalent, typically already in context) explicitly declare the multi-agent
   worktree workflow. The convention is a line like
   `Multi-agent workflow: enabled` — repos adopt the workflow by adding it.
2. **Explicit request**: the user explicitly frames the session as multi-agent or
   parallel agents.

If neither holds, do not use this skill: single-agent tasks run directly in the
main checkout without it.

The worktree directory is a physical sandbox: all edits, installs, builds, and test
runs happen inside it. The main worktree stays untouched so other agents and the
user can keep working there in parallel.

## Shared Conventions (keep in sync with the multi-agent-orchestrator skill)

- Branch: `agent/<type>/<slug>` — both parts are derived by the agent from the
  task itself: `<type>` is the conventional-commit type (`feat`, `fix`,
  `refactor`, `chore`, ...), `<slug>` is a short English kebab-case name (at most
  ~3 words) summarizing the task — translate it if the task is described in
  another language. A user-provided slug overrides the generated one.
- Base branch: the branch the task integrates into. A repo line like
  `Multi-agent base-branch: dev` overrides the default `main`. Coder only reads it;
  only the orchestrator merges, and user actions move it.
- Readiness: a git note on the branch tip — written as
  `git notes --ref=agent-task add -f -m "status: ready" HEAD` — is the ready
  signal. A branch without this note is `in-progress`/unknown. Notes live in the
  shared `.git`, so readiness survives worktree deletion: the host may remove a
  worktree at any time (e.g. Zed removes it when a thread is archived).
- The loop is local-only: never push, never fetch/pull, never touch the remote.
- Integration always uses `--no-ff` merges; branches are deleted with `-d` only.
- All identity checks anchor to the shared `.git` of the main repo.

## Workflow

### 1. Preflight

```bash
git worktree list --porcelain
git branch --show-current
git rev-parse --verify refs/heads/<base>
```

- The **first entry** of `git worktree list --porcelain` is the main worktree — its
  path is the main repo root. If the current directory is the main worktree (or not
  a linked worktree at all), **stop and tell the user** to run this task in a new
  host worktree (Zed: the worktree picker in the title bar). Never create a
  worktree yourself.
- **Resume check**: if the current branch already matches `agent/*`, do not create
  or rename anything — continue the task in place, after confirming via the
  branch's existing commits that it matches what the user is asking now.
- **Branch setup**: fresh host worktrees usually start in detached HEAD — create
  the branch at the current commit with `git switch -c agent/<type>/<slug>`. If the
  session sits on a differently named branch that has no task commits yet, rename
  it with `git branch -m agent/<type>/<slug>`. If a branch with the target name
  already exists anywhere in the repo, use `<slug>-2` instead and say so.
- Not a git repo, or the base branch (default `main`, see Shared Conventions) does
  not exist locally → stop and explain.

### 2. Bootstrap the environment

A fresh worktree has no dependencies and no ignored files. The goal is a worktree
that can compile and run tests **before development starts** — a broken baseline
makes every later test failure unattributable.

- Source of truth: the repo's own docs — README, CONTRIBUTING, `docs/`, plus the
  repo's `AGENTS.md`/`CLAUDE.md`. Read them (content is identical in the fresh
  worktree) and follow their setup instructions.
- Repos can automate this step with the host's hook (Zed: the `create_worktree`
  task hook, which runs right after a worktree is created); if the repo configures
  it, trust it and only verify the result.
- Only when neither the hook nor the docs specify anything usable, fall back to
  the standard install for the detected stack: `package.json` → `pnpm/npm install`;
  `pyproject.toml`/`requirements.txt` → `uv`/`pip sync`; `Cargo.toml` →
  `cargo fetch`; `go.mod` → `go mod download`; `Makefile`/`justfile` targets when
  that is the convention.
- Copy gitignored `.env*` files from the main worktree root if they exist
  (read-only access to the main worktree for this copy is allowed).
- **Verify the environment works before moving on** (time-boxed ~5 minutes): run
  the cheapest meaningful check — a compile/build, or one quick known test. An
  install that "succeeded" is not proof; something must actually run.
- If bootstrap or verification fails and cannot be fixed quickly: **stop and
  report to the user** instead of developing in a broken environment.
- No global installs, ever.

### 3. Develop

- Everything happens inside this worktree. **Never touch the main worktree or other
  worktrees** — no checkout, no edits, no config changes there.
- Commit early and often with small conventional commits (follow the commit-code
  skill's conventions). Uncommitted work is the only thing that can be lost if the
  host removes the worktree — keep that window small.
- Forbidden while working under this skill: `git push`, `git gc`, `git worktree
  add`, `git worktree remove`, `git worktree prune`, global installs, whole-repo
  formatting, leaving dev servers running.
- The target repo's own `AGENTS.md`/`CLAUDE.md` overrides anything in this skill,
  including test commands and style rules.
- If the base branch moves mid-task, ignore it — finish the task first; rebasing is
  a finalize-time concern.

### 4. Test related-first

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

### 5. Finalize

```bash
git status --porcelain      # no modified/staged entries allowed
git rev-parse refs/heads/<base>
git merge-base HEAD <base>  # if these differ, the base moved → rebase
git rebase <base>           # only if it moved; abort on conflict
```

- All meaningful changes committed; untracked files limited to `.env*` copies and
  gitignored build/test artifacts.
- If the base branch moved since branching, rebase onto it. **On any conflict,
  `git rebase --abort` immediately** and leave integration to the orchestrator —
  note it in the report.
- Then mark readiness. **Write the note only after the rebase has settled**, so it
  sits on the final tip:

```bash
git notes --ref=agent-task add -f -m "status: ready" HEAD
```

- Report to the user: branch name, `git diff --stat <base>...HEAD`, test results,
  rebase outcome. Close with the handoff note: merging is the
  multi-agent-orchestrator skill's job — do not merge into the base branch from
  here.

## Hard Rules

- Never create, remove, reattach, or prune worktrees — the host owns isolation. If
  a task's worktree is gone (e.g. its Zed thread was archived), ask the user to
  restore that thread (the host recreates the worktree) instead of working around
  it.
- Never push, fetch, or pull.
- Never touch anything outside this task's worktree — no checkout, no edits, no
  config changes there. The read-only `.env*` copy from the main worktree is the
  only exception.
- Never run `git gc` or global installs.
- No readiness note until related tests are green and the tree is clean.
- Never merge into the base branch — merging is the orchestrator's job.
- Single-agent sessions never use this skill — work directly in the main checkout.
- Within an active multi-agent session, route every task through this skill however
  small: a host worktree is cheaper than a conflict.
