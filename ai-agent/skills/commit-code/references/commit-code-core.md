# Commit Code Core

Use this core spec when the task is to turn working-tree changes into one or more clean commits.

Typical triggers:

- "Commit these changes."
- "Write a proper commit message for this diff."
- "Use Conventional Commits for this commit."
- "Split this work into separate commits."

## Goal

Create focused commits with clear, concrete commit messages and safe staging.

## Workflow

1. Inspect repo state with `git status --short` and `git diff --stat`.
2. Decide whether the changes belong in one commit or multiple logical commits.
3. Stage intentionally with `git add <paths>`. Avoid blanket staging unless the user explicitly requests it.
4. Draft the commit message in Conventional Commits style.
5. Apply clear, concise writing. If the `writing-clearly-and-concisely` skill is available, use it to tighten wording and remove vague phrasing.
6. If the change is complex, require a body as defined in "Body requirements".
7. Run `scripts/commit.sh --dry-run -m "<message>"` from this skill directory to validate the message.
8. Commit with `scripts/commit.sh -m "<message>"` from this skill directory.
9. Report the commit hash and a concise summary of committed files.

## Commit Message Rules

Use this subject format:

- `<type>(<scope>): <summary>`
- `<type>: <summary>`

Allowed types:

- `feat`
- `fix`
- `refactor`
- `perf`
- `docs`
- `test`
- `build`
- `ci`
- `chore`
- `revert`

Subject requirements:

- Keep the subject line at 72 characters or fewer.
- Use imperative mood such as `add`, `fix`, or `update`, not past tense.
- Describe what changed and why in concrete terms.
- Avoid vague text such as `update stuff`, `misc changes`, or `wip`.

## Body Requirements

- Simple changes: body is optional.
- Complex changes: body is required.
- Treat a change as complex when it touches more than 3 files or changes more than 120 lines.
- For complex changes, the body must be a short bullet list where each bullet describes one concrete change.
- Prefer 3 to 6 bullets.
- Start each bullet with an imperative verb such as `set`, `remove`, `ensure`, `maintain`, `rename`, or `add`.
- Keep bullets specific to behavior or code impact.
- Avoid generic bullets such as `misc cleanup`.

Preferred multiline format:

- `subject`
- blank line
- `- change 1`
- `- change 2`

Example:

- `fix(ui): standardize sentence index vertical alignment in notebook`
- blank line
- `- Set .sentenceIndexButton height to match the notebook's --row-height`
- `- Remove manual 0.25rem margin-top offsets from the index circle and button`
- `- Ensure ghost bars remain vertically centered in the row height`
- `- Maintain flex-start for real text rows to align with the first line of text`

## Safety Checks

- Do not commit unrelated changes together.
- Do not stage generated lockfiles or build artifacts unless they are required for the change.
- If there are unrelated local edits, stage only the intended paths.
- If no files are staged, stop and stage intentionally before committing.

## Script

Use `scripts/commit.sh` from this skill directory for deterministic checks and commit execution.

Examples:

- `scripts/commit.sh --dry-run -m "fix(api): handle missing auth token"`
- `scripts/commit.sh -m "refactor(ui): split table toolbar into hooks"`
