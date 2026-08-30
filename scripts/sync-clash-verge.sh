#!/bin/bash
set -euo pipefail

die() {
  echo "$*" >&2
  exit 1
}

canonical_directory() {
  local directory=$1
  (CDPATH='' cd -P -- "$directory" && pwd -P)
}

discover_home() {
  local uid username record home_directory
  uid=$(/usr/bin/id -u)
  [[ "$uid" != 0 ]] || die "sync-clash-verge must run as the login user, not root"
  username=$(/usr/bin/id -un)
  record=$(/usr/bin/dscl . -read "/Users/$username" NFSHomeDirectory) \
    || die "could not read the Home directory for $username"
  home_directory=${record#NFSHomeDirectory: }
  [[ "$home_directory" == /* && "$home_directory" != *$'\n'* ]] \
    || die "Directory Services returned an invalid Home directory: $home_directory"
  DISCOVERED_HOME=$home_directory
}

load_local_config() {
  local local_inc=$1
  CLASH_VERGE_MERGE_UID=${CLASH_VERGE_MERGE_UID:-mcHzRvxuE1Af}
  CLASH_VERGE_RULES_UID=${CLASH_VERGE_RULES_UID:-rgJovenHHCl1}
  CLASH_VERGE_PROXY_GROUP=${CLASH_VERGE_PROXY_GROUP:-'🔰 代理'}

  if [[ -f "$local_inc" ]]; then
    # shellcheck disable=SC1090
    source "$local_inc"
  fi

  [[ "$CLASH_VERGE_MERGE_UID" =~ ^[A-Za-z0-9]+$ ]] \
    || die "CLASH_VERGE_MERGE_UID must be an alphanumeric Clash Verge profile UID"
  [[ "$CLASH_VERGE_RULES_UID" =~ ^[A-Za-z0-9]+$ ]] \
    || die "CLASH_VERGE_RULES_UID must be an alphanumeric Clash Verge profile UID"
  [[ -n "$CLASH_VERGE_PROXY_GROUP" ]] \
    || die "CLASH_VERGE_PROXY_GROUP must not be empty"
}

sync_clash_verge() {
  local repository=$1
  local home_directory=$2
  local profiles_directory=${CLASH_VERGE_PROFILES_DIR:-"$home_directory/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles"}
  local local_inc="$home_directory/.config/clash-verge/local.inc"
  local merge_source="$repository/home/config/clash-verge/github-merge.yaml"
  local rules_template="$repository/home/config/clash-verge/github-rules.yaml.in"
  local merge_target rules_target

  [[ -d "$profiles_directory" ]] || {
    echo "Clash Verge profiles directory not found; skipping clash-verge sync."
    return 0
  }
  [[ -f "$merge_source" ]] || die "missing tracked merge config: $merge_source"
  [[ -f "$rules_template" ]] || die "missing tracked rules template: $rules_template"

  load_local_config "$local_inc"

  merge_target="$profiles_directory/${CLASH_VERGE_MERGE_UID}.yaml"
  rules_target="$profiles_directory/${CLASH_VERGE_RULES_UID}.yaml"

  if [[ -e "$merge_target" && ! -L "$merge_target" ]]; then
    if diff -q "$merge_source" "$merge_target" >/dev/null 2>&1 \
      || { grep -Fq '+.github.com' "$merge_target" && grep -Fq 'ssh.github.com' "$merge_target"; }; then
      rm "$merge_target"
    else
      die "refusing to replace non-symlink merge profile: $merge_target"
    fi
  fi
  if [[ -e "$rules_target" && ! -f "$rules_target" ]]; then
    die "rules profile path is not a regular file: $rules_target"
  fi

  ln -sfn "$merge_source" "$merge_target"
  sed "s/__PROXY_GROUP__/${CLASH_VERGE_PROXY_GROUP}/g" "$rules_template" >"$rules_target"

  echo "Synced Clash Verge GitHub fixes:"
  echo "  merge -> $merge_target"
  echo "  rules -> $rules_target"
  echo "Reload the active Clash Verge profile if it is already running."
}

main() {
  local script_directory repository

  script_directory=$(CDPATH='' cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
  repository=${DOTFILES_REPOSITORY:-$(canonical_directory "$script_directory/..")}
  discover_home
  sync_clash_verge "$repository" "$DISCOVERED_HOME"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
