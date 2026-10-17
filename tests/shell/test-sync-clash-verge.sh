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
mkdir -p "$fixture_home/.config/clash-verge" "$fixture_repository/home/config" "$fixture_repository/scripts" "$profiles_directory"
cp -R "$repository/home/config/clash-verge" "$fixture_repository/home/config/"
cp "$repository/scripts/bind-clash-verge-profiles.rb" "$fixture_repository/scripts/"
# Nix exposes the repository fixture read-only; the test removes generated
# files later to verify cleanup, so make only this temporary copy writable.
chmod -R u+w "$fixture_repository/home/config/clash-verge"

cat >"$fixture_home/.config/clash-verge/local.inc" <<'EOF'
CLASH_VERGE_MERGE_UID=TestMergeUid
CLASH_VERGE_RULES_UID=TestRulesUid
CLASH_VERGE_PROXY_GROUP='Test Proxy'
EOF

cat >"$(dirname "$profiles_directory")/profiles.yaml" <<'EOF'
current: RemoteOne
items:
- uid: RemoteOne
  type: remote
  name: First Airport
  option:
    merge: OldMerge
    rules: OldRules
    script: KeepScript
    proxies: KeepProxies
    groups: KeepGroups
- uid: RemoteTwo
  type: remote
  name: Second Airport
  option:
    update_interval: 1440
- uid: LocalRules
  type: rules
  name: Shared Rules
  file: LocalRules.yaml
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
grep -F 'DOMAIN,appstoreconnect.apple.com,DIRECT' "$rules_target" >/dev/null
grep -F 'DOMAIN,api.appstoreconnect.apple.com,DIRECT' "$rules_target" >/dev/null
grep -F 'DOMAIN,developer.apple.com,DIRECT' "$rules_target" >/dev/null
grep -F 'DOMAIN-SUFFIX,apple-cloudkit.com,DIRECT' "$rules_target" >/dev/null
grep -F 'DOMAIN-SUFFIX,aaplimg.com,DIRECT' "$rules_target" >/dev/null
grep -F 'DOMAIN,notary-submissions-prod.s3-accelerate.amazonaws.com,DIRECT' "$rules_target" >/dev/null
grep -F 'DOMAIN,notary-submissions-prod.s3.us-west-2.amazonaws.com,DIRECT' "$rules_target" >/dev/null
grep -F 'DOMAIN,timestamp.apple.com,Test Proxy' "$rules_target" >/dev/null
grep -F 'DOMAIN,ssh.github.com,Test Proxy' "$rules_target" >/dev/null
grep -F 'DOMAIN-SUFFIX,github.com,Test Proxy' "$rules_target" >/dev/null
if grep -F '__PROXY_GROUP__' "$rules_target" >/dev/null; then
  exit 1
fi

ruby -ryaml -e '
  profiles = YAML.load_file(ARGV.fetch(0))
  remotes = profiles.fetch("items").select { |item| item["type"] == "remote" }
  abort "not all remote profiles were bound" unless remotes.all? { |item| item.dig("option", "merge") == "TestMergeUid" && item.dig("option", "rules") == "TestRulesUid" }
  first = remotes.fetch(0).fetch("option")
  abort "existing profile options were not preserved" unless first["script"] == "KeepScript" && first["proxies"] == "KeepProxies" && first["groups"] == "KeepGroups"
  abort "non-remote profile was modified" unless profiles.fetch("items").fetch(2).fetch("type") == "rules"
' "$(dirname "$profiles_directory")/profiles.yaml"

second_binding=$(ruby "$fixture_repository/scripts/bind-clash-verge-profiles.rb" \
  "$(dirname "$profiles_directory")/profiles.yaml" TestMergeUid TestRulesUid)
[[ "$second_binding" == 'Bound 0 Clash Verge remote profile(s) to merge=TestMergeUid, rules=TestRulesUid.' ]]

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
