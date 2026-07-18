#!/bin/bash
set -euo pipefail

die() {
  echo "$*" >&2
  exit 1
}

discover_home() {
  local uid username record home_directory
  uid=$(/usr/bin/id -u)
  [[ "$uid" != 0 ]] || die "rebuild must run as the login user, not root"
  username=$(/usr/bin/id -un)
  record=$(/usr/bin/dscl . -read "/Users/$username" NFSHomeDirectory) \
    || die "could not read the Home directory for $username"
  home_directory=${record#NFSHomeDirectory: }
  [[ "$home_directory" == /* && "$home_directory" != *$'\n'* ]] \
    || die "Directory Services returned an invalid Home directory: $home_directory"
  DISCOVERED_HOME=$home_directory
}

canonical_directory() {
  local directory=$1
  (CDPATH='' cd -P -- "$directory" && pwd -P)
}

verify_dotfiles_link() {
  local home_directory=$1 repository=$2 link resolved_link
  link="$home_directory/.dotfiles"
  [[ -L "$link" && -e "$link" ]] \
    || die ".dotfiles must be a valid symlink; run scripts/bootstrap.sh"
  resolved_link=$(canonical_directory "$link") \
    || die ".dotfiles does not resolve to a directory: $link"
  [[ "$resolved_link" == "$repository" ]] \
    || die ".dotfiles does not point to this repository: $link"
}

main() {
  local script_directory repository machine_file darwin_rebuild

  script_directory=$(CDPATH='' cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
  repository=$(canonical_directory "$script_directory/..")
  discover_home
  verify_dotfiles_link "$DISCOVERED_HOME" "$repository"

  machine_file="$repository/.machine.nix"
  [[ -f "$machine_file" && ! -L "$machine_file" ]] \
    || die "missing machine identity: $machine_file; run scripts/bootstrap.sh"
  darwin_rebuild=$(command -v darwin-rebuild || true)
  [[ -n "$darwin_rebuild" && -x "$darwin_rebuild" ]] \
    || die "darwin-rebuild is unavailable; run scripts/bootstrap.sh"

  sudo /usr/bin/env DOTFILES_MACHINE="$machine_file" "$darwin_rebuild" \
    switch --impure --flake "$DISCOVERED_HOME/.dotfiles#mac"
  "$repository/scripts/cleanup-legacy.sh" --yes
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
