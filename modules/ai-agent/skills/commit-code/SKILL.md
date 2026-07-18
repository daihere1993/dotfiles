---
name: "commit-code"
description: "Create clean git commits with high-quality commit messages and safe staging. Use when asked to commit code, craft or improve a commit message, split changes into logical commits, or run a standardized git commit workflow. Typical trigger requests include: \"commit these changes\", \"write a proper commit message\", \"make a conventional commit\", and \"split this into two commits\"."
---

# Commit Code

## Overview
Use this skill to turn working-tree changes into focused commits with clear, conventional commit messages.

Path note: resolve any relative path in this file from the directory containing this `SKILL.md`, not from the repo root or the current working directory.

## Workflow
1. Read `references/commit-code-core.md` and use it as the primary commit workflow.
2. Inspect repo state with `git status --short` and `git diff --stat`.
3. Stage intentionally with `git add <paths>` unless the user explicitly asks for blanket staging.
4. If the `writing-clearly-and-concisely` skill is available, use it to tighten the final commit message.
5. Validate and commit with `scripts/commit.sh`.

## Trigger Examples
Use this skill when the user says things like:
- "Commit these changes."
- "Write a proper commit message for this diff."
- "Use Conventional Commits for this commit."
- "Split this work into separate commits."
