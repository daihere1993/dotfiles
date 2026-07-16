# Bootstrap recovery design

## Goal

Make `./bootstrap/install` either complete a healthy deployment or stop with a
useful error. A fresh installation must not fail because bootstrap created its
own state directory with permissions that `dot init` rejects.

## Design

- `bootstrap/install-dot` owns the shared `~/.local/state/dotfiles` root. It
  rejects symlinks and foreign ownership, then enforces mode `0700` before
  creating the CLI profile below it.
- CLI error rendering uses stderr TTY detection through the existing
  `stderr_enabled` function. Rendering an expected `DotfilesError` must never
  raise another exception.
- The official Nix installer runs with `--yes`; administrator authentication
  remains interactive.
- Bootstrap loads an existing daemon profile before deciding Nix is absent and
  enables `nix-command` and `flakes` in its process environment. This closes the
  gap before the first system activation persists those settings.
- The packaged `dot` executable prefixes its runtime PATH with the pinned Nix
  package and passes the required experimental feature flags explicitly. It
  therefore works from shells that have not loaded the daemon profile.
- Bootstrap continues past `dot apply --check` only on exit `0`. Conflicts,
  partial activation, and unhealthy doctor results remain nonzero and prevent
  the final completion message.

## Verification

Add regression tests for error rendering and machine-state permissions. Run
the Python suite, Ruff, ShellCheck, and the Nix flake checks.
