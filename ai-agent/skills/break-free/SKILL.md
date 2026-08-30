---
name: break-free
description: >-
  Architecture-first refactor mode — when the right design requires it, skip backward
  compatibility and data migration. Goal is the best reasonable architecture, not
  breaking change for its own sake. Invoke via /break-free; use Custom Mode
  (Option+Enter) to keep this stance for the whole session.
disable-model-invocation: true
icon: rocket
color: orange
---

# Break-Free Refactor Mode

## North Star

**The goal is the most reasonable software architecture — not breaking things.**

Break-free mode removes compatibility constraints so you can reach a better design when legacy baggage would otherwise force compromises. Breaking changes, deleted code, and schema resets are **tools**, not objectives. If the current structure is already sound, make the smallest correct change. Only refactor boldly when architecture analysis shows the existing shape is wrong and a cleaner design is worth the break.

## Overview

In break-free mode, treat legacy consumers and stored data as non-blocking when they would prevent a sound architectural decision. You are free to:

- Choose the design that is clearest, simplest, and most maintainable long-term
- Reject shims, adapters, and parallel old/new implementations that exist only to avoid breaking callers
- Drop migration paths when a reset or in-repo rewrite is the honest cost of a better structure

You are **not** free to churn code without architectural justification.

## When to Use

- A task reveals structural problems — wrong boundaries, leaky abstractions, duplicated models — and fixing them properly requires breaking the old shape
- Greenfield rewrites inside an existing repo where the target architecture is clear
- Internal tools with no external API consumers
- Prototypes and pre-release products
- Debt paydown where the user wants the **right** design, not a cosmetic cleanup

**Do not use break-free to:**

- Rename or reorganize files with no design improvement
- Delete code without understanding whether it encodes real behavior
- Replace working patterns with different patterns solely because they are newer
- Expand scope beyond what the architecture problem requires

If the user later says compatibility **is** required, exit break-free behavior for that scope immediately.

## Architecture-First Workflow

1. **Understand the problem** — what behavior must exist? What are the real boundaries and dependencies?
2. **Propose the target architecture** — modules, data flow, APIs, and invariants. State *why* this shape is more reasonable than the status quo
3. **Compare cost** — if a non-breaking patch is architecturally equivalent, prefer it. Choose a break only when compatibility work would produce a worse or more complex design
4. **Implement the target design** — one coherent structure; no parallel legacy implementation unless the user asks for a transition period
5. **Update all callers** — grep/reference search; fix every usage in the same change
6. **Remove what the new architecture makes obsolete** — dead paths, flags, shims, and tests for removed behavior
7. **Verify** — run relevant checks; confirm behavior matches intent under the new structure
8. **Summarize** — explain the architectural improvement, what broke, and any manual reset steps

## Allowed — When Architecture Demands It

- **Breaking API changes** — when the public surface no longer matches the domain model
- **Delete legacy code** — when old paths duplicate or contradict the target design
- **Schema changes without migration** — when the new model is simpler and reset is acceptable
- **Consolidate modules** — when overlapping abstractions violate clear ownership
- **Rewrite in place** — when incremental patching would leave a worse hybrid architecture

## Still Required — Do Not Relax

- **Architecture justification**: every significant break should trace back to a concrete design problem and a clearer target shape
- **Minimal sufficient change**: achieve the better architecture with the least churn that actually gets you there
- **Security**: auth, authorization, input validation, secrets handling, and injection defenses stay strict
- **Scope**: solve the architectural problem at hand; do not refactor unrelated modules
- **Correctness**: fix or update tests affected by the change; run relevant checks
- **Engineering standards**: honor project rules (lint, formatting, existing AGENTS.md constraints)
- **Auto-generated files**: do not hand-edit generated outputs or CHANGELOG unless the user asks
- **User-owned boundaries**: do not delete user data paths, credentials, or deployment secrets without explicit confirmation

## Decision Heuristics

| Situation | Break-free choice |
|-----------|-------------------|
| Current design is sound; only a bug or small feature is needed | Do **not** break — fix or extend minimally |
| Compatibility shim would permanently complicate the architecture | Break and update all in-repo callers in one pass |
| Old API misrepresents the domain model | Redesign the API to match the domain; drop the old surface |
| Deprecated field exists only for old clients | Drop it if architecture no longer needs it |
| "We might need this later" code | Delete only when it conflicts with or duplicates the target design — not by default |
| Migration script vs. schema reset | Prefer reset when it yields a simpler honest model |
| Two ways to do the same thing | Keep one; the architecture should have a single obvious path |

## Anti-Patterns — Avoid

- Refactoring without stating what architectural problem is being solved
- Breaking APIs when a narrow internal change would suffice
- Deleting code to reduce line count rather than to simplify design
- Introducing new abstractions that are more complex than what they replace
- Churning directory structure with no effect on module boundaries or dependencies

## Commits

When committing in break-free mode:

- Use Conventional Commits with `!` or `BREAKING CHANGE:` footer when the change is externally visible
- In the body, lead with the **architectural rationale**, then what broke and what to do instead — skip lengthy migration guides unless asked

## Custom Mode

For a full refactor session, invoke `/break-free` and choose **Use as Mode** (Option+Enter on Mac, Alt+Enter on Windows/Linux). The architecture-first, break-when-needed stance applies to every turn until the mode is exited.
