#!/bin/bash
set -euo pipefail

die() {
  echo "$*" >&2
  exit 1
}

discover_account() {
  local uid username record home_directory

  uid=$(/usr/bin/id -u)
  [[ "$uid" != 0 ]] || die "bootstrap must run as the login user, not root"
  username=$(/usr/bin/id -un)
  [[ "$username" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] \
    || die "unsupported macOS account name: $username"
  record=$(/usr/bin/dscl . -read "/Users/$username" NFSHomeDirectory) \
    || die "could not read the Home directory for $username"
  home_directory=${record#NFSHomeDirectory: }
  [[ "$home_directory" == /* && "$home_directory" != *$'\n'* ]] \
    || die "Directory Services returned an invalid Home directory: $home_directory"

  DISCOVERED_USERNAME=$username
  DISCOVERED_HOME=$home_directory
}

canonical_directory() {
  local directory=$1
  (CDPATH='' cd -P -- "$directory" && pwd -P)
}

ensure_dotfiles_link() {
  local home_directory=$1 repository=$2 link resolved_repository resolved_link
  link="$home_directory/.dotfiles"
  resolved_repository=$(canonical_directory "$repository")

  if [[ ! -e "$link" && ! -L "$link" ]]; then
    ln -s "$resolved_repository" "$link"
    return
  fi
  [[ -L "$link" ]] || die "refusing conflicting ~/.dotfiles entry: $link"
  [[ -e "$link" ]] || die "refusing broken ~/.dotfiles link: $link"
  resolved_link=$(canonical_directory "$link") \
    || die ".dotfiles does not resolve to a directory: $link"
  [[ "$resolved_link" == "$resolved_repository" ]] \
    || die ".dotfiles points elsewhere: $link -> $(readlink "$link")"
}

nix_escape() {
  printf '%s' "$1" \
    | /usr/bin/sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\${/\\${/g'
}

write_machine_file() {
  local repository=$1 username=$2 home_directory=$3
  local machine_file temporary escaped_username escaped_home
  machine_file="$repository/.machine.nix"

  if [[ -L "$machine_file" || ( -e "$machine_file" && ! -f "$machine_file" ) ]]; then
    die "machine identity must be a regular file: $machine_file"
  fi
  if [[ -e "$machine_file" ]]; then
    [[ "$(/usr/bin/stat -f '%u' "$machine_file")" == "$(/usr/bin/id -u)" ]] \
      || die "machine identity is not owned by the current user: $machine_file"
  fi

  escaped_username=$(nix_escape "$username")
  escaped_home=$(nix_escape "$home_directory")
  temporary=$(mktemp "$repository/.machine.nix.tmp.XXXXXX")
  trap 'rm -f "$temporary"' RETURN
  chmod 0600 "$temporary"
  {
    printf '{\n'
    printf '  username = "%s";\n' "$escaped_username"
    printf '  homeDirectory = "%s";\n' "$escaped_home"
    printf '  nixSystem = "aarch64-darwin";\n'
    printf '}\n'
  } > "$temporary"
  mv -f -- "$temporary" "$machine_file"
  trap - RETURN
}

enable_flakes() {
  if [[ -n "${NIX_CONFIG:-}" ]]; then
    NIX_CONFIG="$NIX_CONFIG
experimental-features = nix-command flakes"
  else
    NIX_CONFIG='experimental-features = nix-command flakes'
  fi
  export NIX_CONFIG
}

ensure_nix() {
  local installer

  if ! command -v nix >/dev/null 2>&1 \
    && [[ -e /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh ]]; then
    # shellcheck disable=SC1091
    source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
  fi
  if command -v nix >/dev/null 2>&1; then
    enable_flakes
    return
  fi

  echo "Nix is not installed; installing the official multi-user distribution." >&2
  installer=$(mktemp -t dotfiles-nix-install.XXXXXX)
  trap 'rm -f "$installer"' EXIT HUP INT TERM
  /usr/bin/curl --fail --location --proto '=https' --tlsv1.2 \
    --output "$installer" https://nixos.org/nix/install
  /bin/sh "$installer" --daemon --yes
  rm -f "$installer"
  trap - EXIT HUP INT TERM
  # shellcheck disable=SC1091
  source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
  command -v nix >/dev/null 2>&1 || die "Nix installation finished, but nix is unavailable"
  enable_flakes
}

switch_configuration() {
  local repository=$1 home_directory=$2 machine_file=$3 nix_bin
  local flake="$home_directory/.dotfiles#mac"

  if [[ -x /run/current-system/sw/bin/darwin-rebuild ]]; then
    sudo /usr/bin/env DOTFILES_MACHINE="$machine_file" \
      /run/current-system/sw/bin/darwin-rebuild switch --impure --flake "$flake"
    return
  fi

  nix_bin=$(command -v nix)
  sudo /usr/bin/env DOTFILES_MACHINE="$machine_file" "$nix_bin" \
    --extra-experimental-features 'nix-command flakes' \
    run --inputs-from "$repository" nix-darwin#darwin-rebuild -- \
    switch --impure --flake "$flake"
}

main() {
  local script_directory repository machine_file

  [[ "$(/usr/bin/uname -s)" == Darwin && "$(/usr/bin/uname -m)" == arm64 ]] \
    || die "bootstrap requires Apple Silicon macOS"
  /usr/bin/xcode-select -p >/dev/null 2>&1 \
    || die "Xcode Command Line Tools are required; run: xcode-select --install"

  script_directory=$(CDPATH='' cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
  repository=$(canonical_directory "$script_directory/..")
  discover_account
  ensure_nix
  ensure_dotfiles_link "$DISCOVERED_HOME" "$repository"
  write_machine_file "$repository" "$DISCOVERED_USERNAME" "$DISCOVERED_HOME"
  machine_file="$repository/.machine.nix"
  switch_configuration "$repository" "$DISCOVERED_HOME" "$machine_file"
  "$repository/scripts/cleanup-legacy.sh" --yes
  echo "Bootstrap complete. Agent vendor and GitHub authentication remain manual."
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
