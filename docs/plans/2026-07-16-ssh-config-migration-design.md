# SSH Config Migration Design

## Goal

Let `dot apply` adopt an existing user-owned `~/.ssh/config` without losing
machine-specific settings. Dotfiles will own the generated main config, which
includes the user-owned `~/.ssh/config.local`.

## Behavior

- `dot apply --check` reports an eligible SSH config as migratable but does not
  modify it.
- `dot apply` moves an existing regular `~/.ssh/config` to
  `~/.ssh/config.local` when the local file is absent.
- If both files exist, it appends the old main config to `config.local` with a
  separator comment.
- Migration accepts only regular, non-symlink files owned by the current user.
  Unsafe or unsupported paths remain blocking conflicts.
- If system activation fails, migration restores both files to their original
  contents and locations.
- Repeated applies are idempotent because the generated main config conforms to
  the active or desired manifest after the first successful activation.

## Verification

Unit tests cover move, append, unsafe paths, check-mode classification,
idempotency, and rollback. The full test suite and a Nix build verify the
generated SSH config still includes `~/.ssh/config.local`.
