# dotfiles

This repository is the single source of truth for shared Apple Silicon macOS configuration. Nix builds immutable artifacts, Home Manager owns Git and SSH configuration, and `dot` deploys allowlisted global configuration for Codex, Claude Code, and Cursor.

The repository never manages credentials, sessions, private keys, vendor databases, shell configuration, or project-level Agent files. Cursor global rules have no supported filesystem interface and are reported as `UNSUPPORTED_OPTIONAL`.

## First installation

Clone the repository and run:

```sh
./bootstrap/install
```

The script checks macOS and Xcode Command Line Tools, installs Nix when needed, installs the `dot` CLI in an independent user profile, initializes machine identity, validates the repository, applies the deployment domains, and runs doctor. GitHub and Agent vendor authentication remain manual.

The CLI profile lives at `~/.local/state/dotfiles/cli/profile`, with a stable entry at `~/.local/bin/dot`. It is installed and upgraded independently of the System domain, so Git or SSH conflicts cannot prevent `dot` from being available. `~/.local/bin` must be on `PATH`; bootstrap reports a warning if it is not. Before bootstrap, the CLI can still be run through `nix run .#dot -- …`.

## Daily commands

```sh
dot --version
dot validate
dot apply --check
dot apply
dot apply --platform codex
dot doctor
dot doctor --json
dot rollback
```

`dot apply --platform <platform>` builds and switches only that Agent profile. Agent resources are applied independently, so a conflicting skill does not block rules or other skills. A full apply resolves every conflict before making the first change, then continues in system, Codex, Claude, and Cursor order.

`dot rollback` rolls back only the system domain to the previous distinct generation whose manifest matches the current machine identity. It never changes Agent profiles or Git state.

Do not run `dot apply` concurrently with `darwin-rebuild`, `home-manager`, or another apply. Direct deployment commands bypass `dot` conflict checks and post-activation verification.

## Machine-local files

Initialization records the system account in `~/.local/state/dotfiles/machine.json`. Do not edit or copy this file between machines.

These optional files remain user-owned and are never read or deployed by dotfiles:

```text
~/.config/git/local.inc
~/.ssh/config.local
```

Doctor checks only their file type, owner, and write permissions.

## Agent rules and skills

Edit shared rules in `ai-agent/rules/common.md` and platform additions in `ai-agent/rules/agents/`. Run `dot validate` and `dot apply` after every change; generated files are read-only Nix Store artifacts.

Dotfiles owns individual entries below each platform's skills directory, not the directory itself. Unrelated manual skills remain untouched. In an interactive terminal, an unmanaged skill with the same target ID can be backed up and overwritten or skipped. Non-interactive apply defaults to skip. Empty, safely permissioned rules files may be adopted automatically; non-empty rules files are skipped without being overwritten.

A local skill lives at `ai-agent/skills/<skill-id>/` and must include a `SKILL.md` whose frontmatter name equals the directory name. Select it explicitly in `ai-agent/profiles/default.nix` as `local:<skill-id>`.

Declare a third-party repository as a root-level `flake = false` input. Map the source and selected directory in `ai-agent/external-skills.nix`, then select `external:<source-id>/<skill-id>` in the profile. Update it explicitly:

```sh
nix flake update <source-id>
dot validate
dot apply --check
dot apply
```

Updating `flake.lock` never deploys automatically.

## Conflicts and diagnosis

`dot apply --check` reports conflicts without prompting or changing state. Interactive apply offers `overwrite`, `skip`, `overwrite all`, and `skip all` for eligible Agent skill conflicts. Overwrite moves the old entry into `~/.local/state/dotfiles/backups/` before installing the managed link. Backups are retained and restored if that skill later leaves the profile. Other conflicts are skipped and never overwritten.

Doctor reports:

- `NOT_DEPLOYED` or `STAGED_NOT_DEPLOYED` for inactive platform profiles;
- `MISSING` when a managed entry disappeared;
- `DRIFTED` when its symlink or content differs from the manifest;
- `SKIPPED_CONFLICT` when a desired resource remains user-owned;
- `BACKUP_MISSING` when a managed resource has lost its restoration backup;
- `LOCAL_ABSENT_OPTIONAL`, `LOCAL_PRESENT`, or `LOCAL_UNSAFE_PERMISSIONS` for local includes;
- `UNSUPPORTED_OPTIONAL` for Cursor global rules.

No command prints the contents of local includes, credentials, sessions, caches, or vendor state.
