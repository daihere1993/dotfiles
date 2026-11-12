---
name: multi-agent-coder
description: Develop and hand off one task in a host-managed worktree when the user explicitly invokes multi-agent-coder. Prepare the environment, run related verification and record readiness for an exact commit; leave integration to multi-agent-orchestrator. Do not activate automatically or merely to review this skill.
license: MIT
allowed-tools: Bash, Read, Edit, Write, Grep, Glob
---

# Multi-Agent Coder

One task, one host-managed worktree, one task branch. The host editor owns task
worktree creation/restoration/archival; the repository owns environment and runtime
commands; this skill owns development and handoff. The orchestrator owns integration.

Use only when the user explicitly invokes `multi-agent-coder`. A repository workflow
declaration, worktree location or general request for parallel work does not invoke
this skill. Otherwise follow the user's chosen checkout and branch; this skill does
not require single-agent work to happen on main.
Explicit user instructions and repository rules override these defaults.

## Shared contract

Keep these rules consistent with multi-agent-orchestrator:

- Default task branch: `agent/<type>/<slug>`; conventional-commit type and short
  English kebab-case slug. Honor an explicit user/repo branch choice. Default base:
  `main`, overridden by `Multi-agent base-branch: <name>` or user instruction.
- Identify the repository through its canonical Git common directory. Task code
  belongs to its worktree. Shared Git refs/notes and documented repository-managed
  caches, immutable baselines and checkout-specific runtime data are permitted.
  Never modify another task's code, credentials, runtime data or processes.
- Local-only by default: no push, fetch, pull, gc or global installs.
- Ready describes a verified commit, not an application health response. Store the
  JSON receipt below in `refs/notes/agent-task` on that exact commit. Missing,
  malformed or legacy `status: ready`-only notes require verification again.
- Ignore rules handle generated output and secrets. Every non-ignored untracked
  file must be committed, deliberately ignored, or explicitly accounted for by
  repository policy; it cannot be dismissed merely because it is untracked.
- Temporary integration-test worktrees are allowed only through an explicitly
  documented repo test harness that owns and cleans its disposable fixtures.
  This does not permit creating/removing/repairing host task worktrees.

## Prepare

Read the repo instructions and development runbook. Inspect worktree list, branch,
status and local base ref before changing anything. The first worktree entry is the
main checkout. Normally request a host worktree when running there; an explicit
user authorization to work in main or another location takes precedence.

Before modifying task files or starting development, create or confirm the task
branch and verify that HEAD is attached to it. If branch creation or verification
fails, stop and report the blocker; do not start development. If the worktree
already contains changes, preserve them and inspect their ownership before acting.

Resume an existing task branch only after checking that its commits match the
request. From detached HEAD, create the task branch at the current commit. Do not
rename an existing user/host branch without authorization. If the chosen branch
name exists, select the next free numeric suffix; never reuse another task branch.
If the worktree disappears, stop task work and request host restoration.

Use the repo's bootstrap command. A configured host hook can prepare it, but verify
its actual result. Do not duplicate setup or fall back to generic package installs
when the repo has a documented procedure. Only use stack-standard installs when
no such procedure exists. Copy only the development config files explicitly named
by the repo; never bulk-copy `.env*` or release/server credentials.

Run a cheap meaningful build/check before development. Five minutes is a progress
checkpoint, not permission to skip validation or abandon a healthy long install.
Investigate failures and narrow checks when possible; report a concrete blocker
when the environment cannot be made usable. Do not publish/reset shared test data
or silently choose empty onboarding data to bypass a missing baseline.

## Develop and verify

Keep changes and commits scoped to this task; use conventional commits without
agent co-author attribution. Never format the whole repo as incidental cleanup.
Run related checks first, including uncommitted and non-ignored new source files.
Broaden when shared contracts, CI or other global changes justify it. Record what
actually ran and what remains unverified; time budgets do not turn failures green.

Use the repository's start/status/logs/stop commands for functional checks. You may
leave an explicitly identified session running while waiting for requested human
acceptance. Report its checkout, session and phase through the repo status command.
That phase is **waiting for acceptance**, not ready for integration. Do not start a
new session blindly when one already exists, or kill processes using cached PIDs.

Before normal finalization, stop this task's session and confirm shutdown. If the
user asks to keep it open, hand off that state and defer the ready receipt until
shutdown (unless the user explicitly overrides the readiness policy). Never stop
another task's services. Manual acceptance is required only when the user or repo
requires it, not for every change.

## Finalize an exact commit

1. Finish the required human acceptance and stop owned services.
2. Commit all meaningful files. Check `git status --porcelain=v1 --untracked-files=all`;
   a clean tree includes non-ignored untracked files under the shared contract.
3. Do **not** automatically rebase because the base moved. Report the tested base
   and let integration validate the combination. If rebase/reset/cherry-pick is
   explicitly requested, stop the runtime first. On uncertain conflicts abort the
   operation; after a successful history/content change, rerun affected checks and
   any acceptance invalidated by the change before marking ready.
4. Run required verification against the final commit. Record its SHA and the
   included base SHA (`git merge-base <testedHead> <base>`) as baseHead and the
   base ref at verification time as observedBaseHead; confirm HEAD and tree are unchanged when
   writing the note. If they changed during verification, validate again.
5. Write the following receipt as JSON with actual values (redact command secrets); use a temporary file
   and `git notes --ref=agent-task add -f -F <receipt-file> <testedHead>`.

```json
{
  "schemaVersion": 1,
  "status": "ready",
  "branch": "agent/fix/example",
  "testedHead": "<full task commit SHA>",
  "baseBranch": "main",
  "baseHead": "<full merge-base SHA included in testedHead>",
  "observedBaseHead": "<full current base-ref SHA at verification>",
  "checks": [{"command": "<actual command>", "result": "passed"}],
  "manualAcceptance": {"required": false, "result": "not-required"},
  "runtime": {"state": "stopped"}
}
```

`baseHead` is included in the tested branch; observedBaseHead may be newer and
is not claimed to have been integrated or tested with this task.

For required human acceptance use `required: true, result: "passed"` only after
actual acceptance. Runtime may be `not-started` if no session was launched. Do not
mark ready with pending/failed checks, pending acceptance or a running session by
default. Git notes attach to commits, so the branch field must also match: a branch
alias pointing at a ready commit does not automatically inherit task readiness.

Before replacing an existing note, verify it belongs to this task branch; do not
overwrite another branch's receipt on an aliased commit. Concurrent notes updates
can contend on the shared ref. For a Git lock/ref-update conflict only, reread the
note and retry a bounded number of times while HEAD/tree remain unchanged; do not
remove lock files or retry unrelated failures blindly.

Report branch, tested SHA/base, diff summary, checks, acceptance, stopped runtime
and any remaining risks. Hand off merging to multi-agent-orchestrator. Do not merge
into the base, delete task branches, or archive host worktrees from this skill.
