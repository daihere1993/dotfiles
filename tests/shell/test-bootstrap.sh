#!/bin/bash
set -euo pipefail

repository=${DOTFILES_REPOSITORY:-$(CDPATH='' cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)}
# shellcheck disable=SC1091
source "$repository/scripts/bootstrap.sh"

temporary=$(mktemp -d -t dotfiles-bootstrap-test.XXXXXX)
trap 'rm -rf "$temporary"' EXIT
fixture_repository="$temporary/repository"
fixture_home="$temporary/home"
mkdir -p "$fixture_repository" "$fixture_home"

ensure_dotfiles_link "$fixture_home" "$fixture_repository"
[[ -L "$fixture_home/.dotfiles" ]]
[[ "$(canonical_directory "$fixture_home/.dotfiles")" == "$(canonical_directory "$fixture_repository")" ]]
ensure_dotfiles_link "$fixture_home" "$fixture_repository"

write_machine_file "$fixture_repository" "alice" "$fixture_home"
machine_file="$fixture_repository/.machine.nix"
[[ -f "$machine_file" && ! -L "$machine_file" ]]
[[ "$(/usr/bin/stat -f '%Lp' "$machine_file")" == 600 ]]
grep -F 'username = "alice";' "$machine_file" >/dev/null
grep -F "homeDirectory = \"$fixture_home\";" "$machine_file" >/dev/null
grep -F 'nixSystem = "aarch64-darwin";' "$machine_file" >/dev/null
nix-instantiate --eval --strict "$machine_file" >/dev/null
write_machine_file "$fixture_repository" "bob" "$fixture_home"
grep -F 'username = "bob";' "$machine_file" >/dev/null

conflict_home="$temporary/conflict-file"
mkdir -p "$conflict_home"
touch "$conflict_home/.dotfiles"
if (ensure_dotfiles_link "$conflict_home" "$fixture_repository") 2>/dev/null; then
  echo "regular ~/.dotfiles file was accepted" >&2
  exit 1
fi

directory_home="$temporary/conflict-directory"
mkdir -p "$directory_home/.dotfiles"
if (ensure_dotfiles_link "$directory_home" "$fixture_repository") 2>/dev/null; then
  echo ".dotfiles directory was accepted" >&2
  exit 1
fi

broken_home="$temporary/broken"
mkdir -p "$broken_home"
ln -s "$temporary/missing" "$broken_home/.dotfiles"
if (ensure_dotfiles_link "$broken_home" "$fixture_repository") 2>/dev/null; then
  echo "broken ~/.dotfiles link was accepted" >&2
  exit 1
fi

wrong_home="$temporary/wrong"
wrong_repository="$temporary/wrong-repository"
mkdir -p "$wrong_home" "$wrong_repository"
ln -s "$wrong_repository" "$wrong_home/.dotfiles"
if (ensure_dotfiles_link "$wrong_home" "$fixture_repository") 2>/dev/null; then
  echo "unrelated ~/.dotfiles link was accepted" >&2
  exit 1
fi

echo "bootstrap filesystem tests passed"
