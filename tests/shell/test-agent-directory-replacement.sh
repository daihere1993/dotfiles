#!/bin/bash
set -euo pipefail

repository=${DOTFILES_REPOSITORY:-$(CDPATH='' cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)}
helper="$repository/modules/ai-agent/remove-conflicting-skill-directory.sh"
temporary=$(mktemp -d -t dotfiles-agent-test.XXXXXX)
trap 'rm -rf "$temporary"' EXIT
home_directory="$temporary/home"
root="$home_directory/.agents/skills"
mkdir -p "$root/commit-code/nested" "$root/unrelated"
touch "$root/commit-code/nested/file"

bash "$helper" "$root/commit-code" "$root" commit-code "$home_directory"
[[ ! -e "$root/commit-code" ]]
[[ -d "$root/unrelated" ]]

touch "$root/commit-code"
bash "$helper" "$root/commit-code" "$root" commit-code "$home_directory"
[[ -f "$root/commit-code" ]]
rm "$root/commit-code"
ln -s "$root/unrelated" "$root/commit-code"
bash "$helper" "$root/commit-code" "$root" commit-code "$home_directory"
[[ -L "$root/commit-code" ]]

mkdir -p "$temporary/outside/commit-code"
if bash "$helper" "$temporary/outside/commit-code" "$temporary/outside" \
  commit-code "$home_directory" 2>/dev/null; then
  echo "Agent helper accepted a root outside the allowlist" >&2
  exit 1
fi
[[ -d "$temporary/outside/commit-code" ]]

echo "Agent directory replacement tests passed"
