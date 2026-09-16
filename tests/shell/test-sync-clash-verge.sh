#!/bin/bash
set -euo pipefail

repository=${DOTFILES_REPOSITORY:-$(CDPATH='' cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)}
# shellcheck disable=SC1091
source "$repository/scripts/sync-clash-verge.sh"

temporary=$(mktemp -d -t dotfiles-clash-verge-test.XXXXXX)
trap 'rm -rf "$temporary"' EXIT

fixture_home="$temporary/home"
fixture_repository="$temporary/repository"
profiles_directory="$temporary/clash-verge/profiles"
mkdir -p "$fixture_home/.config/clash-verge" "$fixture_repository/home/config" "$profiles_directory"
cp -R "$repository/home/config/clash-verge" "$fixture_repository/home/config/"
# Nix exposes the repository fixture read-only; the test removes generated
# files later to verify cleanup, so make only this temporary copy writable.
chmod -R u+w "$fixture_repository/home/config/clash-verge"

cat >"$fixture_home/.config/clash-verge/local.inc" <<'EOF'
CLASH_VERGE_MERGE_UID=TestMergeUid
CLASH_VERGE_RULES_UID=TestRulesUid
CLASH_VERGE_PROXY_GROUP='Test Proxy'
EOF

DISCOVERED_HOME=$fixture_home
CLASH_VERGE_PROFILES_DIR=$profiles_directory
sync_clash_verge "$fixture_repository" "$fixture_home"

merge_target="$profiles_directory/TestMergeUid.yaml"
rules_target="$profiles_directory/TestRulesUid.yaml"

[[ -L "$merge_target" ]]
[[ "$(readlink "$merge_target")" == "$fixture_repository/home/config/clash-verge/github-merge.yaml" ]]
grep -F '+.github.com' "$merge_target" >/dev/null
grep -F 'ssh.github.com' "$merge_target" >/dev/null

[[ -f "$rules_target" ]]
grep -F 'DOMAIN,ssh.github.com,Test Proxy' "$rules_target" >/dev/null
grep -F 'DOMAIN-SUFFIX,github.com,Test Proxy' "$rules_target" >/dev/null
if grep -F '__PROXY_GROUP__' "$rules_target" >/dev/null; then
  exit 1
fi

conflict_home="$temporary/conflict-home"
conflict_profiles_directory="$temporary/clash-verge-conflict/profiles"
mkdir -p "$conflict_home/.config/clash-verge" "$conflict_profiles_directory"
conflict_target="$conflict_profiles_directory/conflict-merge.yaml"
printf 'manual content\n' >"$conflict_target"
export DISCOVERED_HOME=$conflict_home
export CLASH_VERGE_PROFILES_DIR=$conflict_profiles_directory
export CLASH_VERGE_MERGE_UID=conflict-merge
export CLASH_VERGE_RULES_UID=TestRulesUid
export CLASH_VERGE_PROXY_GROUP='Test Proxy'
if (sync_clash_verge "$fixture_repository" "$conflict_home") 2>/dev/null; then
  echo "non-symlink merge profile was replaced" >&2
  exit 1
fi
