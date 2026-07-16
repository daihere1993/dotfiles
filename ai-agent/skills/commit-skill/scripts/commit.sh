#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: commit.sh [--dry-run] -m "<commit message>"

Options:
  -m, --message   Commit message (supports multiline with embedded newlines)
  --dry-run       Validate only; do not create a commit
  -h, --help      Show this help message
USAGE
}

dry_run=0
message=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--message)
      shift
      [[ $# -gt 0 ]] || { echo "Error: missing value for --message" >&2; exit 1; }
      message="$1"
      ;;
    --dry-run)
      dry_run=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

[[ -n "$message" ]] || { echo "Error: commit message is required" >&2; usage >&2; exit 1; }

# Use first line as subject for format checks.
subject="${message%%$'\n'*}"

if [[ ${#subject} -gt 72 ]]; then
  echo "Error: commit subject must be 72 chars or fewer (${#subject})" >&2
  exit 1
fi

if ! [[ "$subject" =~ ^(feat|fix|refactor|perf|docs|test|build|ci|chore|revert)(\([a-z0-9._/-]+\))?:\ [a-z] ]]; then
  echo "Error: subject must match Conventional Commits format:" >&2
  echo "  <type>(<scope>): <summary> or <type>: <summary>" >&2
  exit 1
fi

if [[ "$subject" =~ (wip|misc|stuff|changes|update things|temp|tmp) ]]; then
  echo "Error: subject is too vague; use a concrete summary" >&2
  exit 1
fi

if git diff --cached --quiet; then
  echo "Error: no staged changes to commit" >&2
  exit 1
fi

if [[ $dry_run -eq 1 ]]; then
  echo "Commit message validation passed."
  echo "Dry run only; no commit created."
  exit 0
fi

git commit -m "$message"
