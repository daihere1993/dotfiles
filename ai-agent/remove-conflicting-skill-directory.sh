#!/bin/bash
set -euo pipefail

target=$1
expected_root=$2
expected_id=$3
home_directory=$4

if [[ "$(dirname -- "$target")" != "$expected_root" \
  || "$(basename -- "$target")" != "$expected_id" ]]; then
  echo "Refusing unsafe Agent skill target: $target" >&2
  exit 1
fi

case "$expected_root" in
  "$home_directory/.agents/skills"|\
  "$home_directory/.claude/skills"|\
  "$home_directory/.cursor/skills") ;;
  *)
    echo "Refusing Agent skill root outside the managed allowlist: $expected_root" >&2
    exit 1
    ;;
esac

if [[ -d "$target" && ! -L "$target" ]]; then
  rm -rf -- "$target"
fi
