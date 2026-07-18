#!/bin/bash
set -euo pipefail

LEGACY_AGENT_LINKS=()
LEGACY_DOT_LINK=''
LEGACY_STATE=''

die() {
  echo "$*" >&2
  exit 1
}

discover_account() {
  local uid username record home_directory
  uid=$(/usr/bin/id -u)
  [[ "$uid" != 0 ]] || die "legacy cleanup must run as the login user, not root"
  username=$(/usr/bin/id -un)
  record=$(/usr/bin/dscl . -read "/Users/$username" NFSHomeDirectory) \
    || die "could not read the Home directory for $username"
  home_directory=${record#NFSHomeDirectory: }
  [[ "$home_directory" == /* && "$home_directory" != *$'\n'* ]] \
    || die "Directory Services returned an invalid Home directory: $home_directory"
  DISCOVERED_UID=$uid
  DISCOVERED_HOME=$home_directory
}

validate_owned_directory() {
  local path=$1 expected_uid=$2 required=$3
  if [[ ! -e "$path" && ! -L "$path" ]]; then
    [[ "$required" == false ]] && return
    die "required directory does not exist: $path"
  fi
  [[ ! -L "$path" && -d "$path" ]] || die "unsafe directory path: $path"
  [[ "$(/usr/bin/stat -f '%u' "$path")" == "$expected_uid" ]] \
    || die "directory is not owned by uid $expected_uid: $path"
}

is_legacy_agent_target() {
  local target=$1 legacy_root=$2
  [[ "$target" == "$legacy_root/platforms/"* ]]
}

is_legacy_dot_target() {
  local target=$1 legacy_root=$2
  [[ "$target" == "$legacy_root/"* ]]
}

consider_agent_link() {
  local path=$1 legacy_root=$2 raw_target
  [[ -L "$path" ]] || return 0
  raw_target=$(readlink "$path")
  if is_legacy_agent_target "$raw_target" "$legacy_root"; then
    LEGACY_AGENT_LINKS+=("$path")
  fi
  return 0
}

preflight_legacy_cleanup() {
  local home_directory=$1 expected_uid=$2 legacy_root local_root state_root
  local path skill_root dot_entry raw_target
  LEGACY_AGENT_LINKS=()
  LEGACY_DOT_LINK=''
  LEGACY_STATE=''
  legacy_root="$home_directory/.local/state/dotfiles"
  local_root="$home_directory/.local"
  state_root="$local_root/state"

  validate_owned_directory "$home_directory" "$expected_uid" true
  validate_owned_directory "$local_root" "$expected_uid" false
  validate_owned_directory "$state_root" "$expected_uid" false
  validate_owned_directory "$legacy_root" "$expected_uid" false
  validate_owned_directory "$home_directory/.local/bin" "$expected_uid" false

  consider_agent_link "$home_directory/.codex/AGENTS.md" "$legacy_root"
  consider_agent_link "$home_directory/.claude/CLAUDE.md" "$legacy_root"
  for skill_root in \
    "$home_directory/.agents/skills" \
    "$home_directory/.claude/skills" \
    "$home_directory/.cursor/skills"; do
    [[ -d "$skill_root" && ! -L "$skill_root" ]] || continue
    while IFS= read -r -d '' path; do
      consider_agent_link "$path" "$legacy_root"
    done < <(/usr/bin/find "$skill_root" -mindepth 1 -maxdepth 1 -type l -print0)
  done

  dot_entry="$home_directory/.local/bin/dot"
  if [[ -L "$dot_entry" ]]; then
    raw_target=$(readlink "$dot_entry")
    is_legacy_dot_target "$raw_target" "$legacy_root" \
      || die "refusing unrelated dot symlink: $dot_entry -> $raw_target"
    LEGACY_DOT_LINK=$dot_entry
  elif [[ -e "$dot_entry" ]]; then
    die "refusing unrelated dot entry: $dot_entry"
  fi

  if [[ -d "$legacy_root" && ! -L "$legacy_root" ]]; then
    LEGACY_STATE=$legacy_root
  fi
  return 0
}

print_cleanup_plan() {
  local path
  if [[ ${#LEGACY_AGENT_LINKS[@]} -eq 0 && -z "$LEGACY_DOT_LINK" && -z "$LEGACY_STATE" ]]; then
    echo "No legacy dotfiles state found."
    return 1
  fi
  echo "Legacy cleanup will remove:"
  for path in "${LEGACY_AGENT_LINKS[@]}"; do
    printf '  symlink %s -> %s\n' "$path" "$(readlink "$path")"
  done
  if [[ -n "$LEGACY_DOT_LINK" ]]; then
    printf '  symlink %s -> %s\n' "$LEGACY_DOT_LINK" "$(readlink "$LEGACY_DOT_LINK")"
  fi
  if [[ -n "$LEGACY_STATE" ]]; then
    printf '  directory %s\n' "$LEGACY_STATE"
  fi
}

confirm_cleanup() {
  local reply
  printf 'Remove these targets? [y/N] '
  IFS= read -r reply || return 1
  [[ "$reply" == y || "$reply" == Y || "$reply" == yes || "$reply" == YES ]]
}

execute_legacy_cleanup() {
  local home_directory=$1 expected_uid=$2 legacy_root path raw_target
  legacy_root="$home_directory/.local/state/dotfiles"

  for path in "${LEGACY_AGENT_LINKS[@]}"; do
    [[ -L "$path" ]] || die "legacy Agent link changed before deletion: $path"
    raw_target=$(readlink "$path")
    is_legacy_agent_target "$raw_target" "$legacy_root" \
      || die "legacy Agent link changed before deletion: $path"
    rm -- "$path"
  done

  if [[ -n "$LEGACY_DOT_LINK" ]]; then
    [[ -L "$LEGACY_DOT_LINK" ]] || die "dot link changed before deletion: $LEGACY_DOT_LINK"
    raw_target=$(readlink "$LEGACY_DOT_LINK")
    is_legacy_dot_target "$raw_target" "$legacy_root" \
      || die "dot link changed before deletion: $LEGACY_DOT_LINK"
    rm -- "$LEGACY_DOT_LINK"
  fi

  if [[ -n "$LEGACY_STATE" ]]; then
    validate_owned_directory "$home_directory/.local" "$expected_uid" true
    validate_owned_directory "$home_directory/.local/state" "$expected_uid" true
    validate_owned_directory "$LEGACY_STATE" "$expected_uid" true
    [[ "$LEGACY_STATE" == "$legacy_root" ]] \
      || die "refusing unexpected legacy state path: $LEGACY_STATE"
    rm -rf -- "$LEGACY_STATE"
  fi
}

main() {
  local assume_yes=false
  case $# in
    0) ;;
    1)
      [[ "$1" == --yes ]] || die "usage: cleanup-legacy.sh [--yes]"
      assume_yes=true
      ;;
    *) die "usage: cleanup-legacy.sh [--yes]" ;;
  esac

  discover_account
  preflight_legacy_cleanup "$DISCOVERED_HOME" "$DISCOVERED_UID"
  print_cleanup_plan || return 0
  if [[ "$assume_yes" == false ]] && ! confirm_cleanup; then
    echo "Legacy cleanup cancelled."
    return 0
  fi
  execute_legacy_cleanup "$DISCOVERED_HOME" "$DISCOVERED_UID"
  echo "Legacy dotfiles state removed."
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
