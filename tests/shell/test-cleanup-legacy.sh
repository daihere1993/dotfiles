#!/bin/bash
set -euo pipefail

repository=${DOTFILES_REPOSITORY:-$(CDPATH='' cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)}
# shellcheck disable=SC1091
source "$repository/scripts/cleanup-legacy.sh"

temporary=$(mktemp -d -t dotfiles-cleanup-test.XXXXXX)
trap 'rm -rf "$temporary"' EXIT
uid=$(/usr/bin/id -u)

home_directory="$temporary/home"
legacy_root="$home_directory/.local/state/dotfiles"
mkdir -p \
  "$legacy_root/platforms/codex/profile/skills" \
  "$legacy_root/platforms/claude/profile" \
  "$legacy_root/platforms/cursor/profile/skills" \
  "$home_directory/.local/bin" \
  "$home_directory/.codex" \
  "$home_directory/.claude/skills" \
  "$home_directory/.agents/skills" \
  "$home_directory/.cursor/skills" \
  "$home_directory/.dotfiles/ai-agent"
ln -s "$legacy_root/platforms/codex/profile/AGENTS.md" "$home_directory/.codex/AGENTS.md"
ln -s "$home_directory/.dotfiles/ai-agent/AGENTS.md" "$home_directory/.claude/CLAUDE.md"
ln -s "$legacy_root/platforms/codex/profile/skills/commit-code" \
  "$home_directory/.agents/skills/commit-code"
ln -s "$legacy_root/platforms/claude/profile/skills/brainstorming" \
  "$home_directory/.claude/skills/brainstorming"
ln -s ../../.agents/skills/find-skills "$home_directory/.claude/skills/find-skills"
mkdir -p "$home_directory/.cursor/skills/unrelated-directory"
ln -s "$legacy_root/cli/bin/dot" "$home_directory/.local/bin/dot"

preflight_legacy_cleanup "$home_directory" "$uid"
[[ ${#LEGACY_AGENT_LINKS[@]} -eq 3 ]]
[[ "$LEGACY_DOT_LINK" == "$home_directory/.local/bin/dot" ]]
[[ "$LEGACY_STATE" == "$legacy_root" ]]
execute_legacy_cleanup "$home_directory" "$uid"
[[ ! -e "$home_directory/.codex/AGENTS.md" && ! -L "$home_directory/.codex/AGENTS.md" ]]
[[ -L "$home_directory/.claude/CLAUDE.md" ]]
[[ ! -L "$home_directory/.agents/skills/commit-code" ]]
[[ ! -L "$home_directory/.claude/skills/brainstorming" ]]
[[ -L "$home_directory/.claude/skills/find-skills" ]]
[[ -d "$home_directory/.cursor/skills/unrelated-directory" ]]
[[ ! -e "$home_directory/.local/bin/dot" && ! -L "$home_directory/.local/bin/dot" ]]
[[ ! -e "$legacy_root" ]]
preflight_legacy_cleanup "$home_directory" "$uid"
if print_cleanup_plan >/dev/null; then
  echo "idempotent cleanup reported work" >&2
  exit 1
fi

conflict_home="$temporary/conflict-home"
conflict_legacy="$conflict_home/.local/state/dotfiles"
mkdir -p \
  "$conflict_legacy/platforms/codex/profile" \
  "$conflict_home/.local/bin" \
  "$conflict_home/.codex"
ln -s "$conflict_legacy/platforms/codex/profile/AGENTS.md" "$conflict_home/.codex/AGENTS.md"
ln -s /tmp/unrelated-dot "$conflict_home/.local/bin/dot"
if (preflight_legacy_cleanup "$conflict_home" "$uid") 2>/dev/null; then
  echo "unrelated dot link was accepted" >&2
  exit 1
fi
[[ -L "$conflict_home/.codex/AGENTS.md" ]]
[[ -d "$conflict_legacy" ]]

unsafe_home="$temporary/unsafe-home"
unsafe_local="$temporary/unsafe-local"
mkdir -p "$unsafe_home" "$unsafe_local"
ln -s "$unsafe_local" "$unsafe_home/.local"
if (preflight_legacy_cleanup "$unsafe_home" "$uid") 2>/dev/null; then
  echo "symlinked ~/.local was accepted" >&2
  exit 1
fi

unsafe_bin_home="$temporary/unsafe-bin-home"
unsafe_bin="$temporary/unsafe-bin"
mkdir -p "$unsafe_bin_home/.local/state" "$unsafe_bin"
ln -s "$unsafe_bin" "$unsafe_bin_home/.local/bin"
ln -s "$unsafe_bin_home/.local/state/dotfiles/cli/bin/dot" "$unsafe_bin/dot"
if (preflight_legacy_cleanup "$unsafe_bin_home" "$uid") 2>/dev/null; then
  echo "symlinked ~/.local/bin was accepted" >&2
  exit 1
fi
[[ -L "$unsafe_bin/dot" ]]

owner_home="$temporary/owner-home"
mkdir -p "$owner_home"
if (preflight_legacy_cleanup "$owner_home" 99999) 2>/dev/null; then
  echo "incorrect Home ownership was accepted" >&2
  exit 1
fi

if printf 'n\n' | confirm_cleanup >/dev/null; then
  echo "negative cleanup confirmation was accepted" >&2
  exit 1
fi
printf 'yes\n' | confirm_cleanup >/dev/null

echo "legacy cleanup tests passed"
