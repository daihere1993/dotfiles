# Simple dotfiles architecture design

- Status: approved
- Date: 2026-07-18

## 1. Goal

Refactor the repository from a custom deployment platform into a small personal
dotfiles repository built on nix-darwin and Home Manager.

The repository remains the source of truth for shared macOS configuration and
for Codex, Claude Code, and Cursor skills. Agent rules and skills use direct
out-of-store symlinks, so editing their contents takes effect immediately.

The new design removes the `dot` CLI and its compiler, manifests, deployment
profiles, conflict backups, diagnostics, event stream, and custom rollback
workflow. Nix generations provide system rollback, and Git provides content
history.

## 2. Design principles

1. Use nix-darwin and Home Manager as the only deployment system.
2. Keep machine identity local to each checkout and out of Git.
3. Link canonical Agent content directly instead of compiling immutable bundles.
4. Manage only repository-owned skill names; leave unrelated local skills alone.
5. Prefer one daily command and fail with the underlying tool's error.
6. Remove all runtime state created by the old architecture after migration.

## 3. Repository structure

The target structure is:

```text
dotfiles/
├── AGENTS.md
├── README.md
├── bootstrap.sh
├── rebuild.sh
├── flake.nix
├── flake.lock
├── justfile
├── .machine.nix              # generated, gitignored
├── ai-agent/
│   └── skills/
│       └── <skill-id>/
│           ├── SKILL.md
│           └── ...
├── modules/
│   ├── ai-agent/
│   ├── darwin/
│   └── home/
└── tests/
    └── shell/
```

The exact module split may retain the existing focused files. The architecture
does not require consolidating all Nix configuration into one file.

The following old components are removed:

- `cli/` and `pyproject.toml`;
- the `dot` package, flake app, and CLI installation script;
- Agent compiler, adapters, manifests, receipts, platform profiles, doctor,
  event reporting, deployment planning, and custom rollback;
- `ai-agent/external-skills.nix` and the `superpowers` flake input;
- `ai-agent/profiles/`;
- Agent-specific rule files;
- the external `brainstorming` skill;
- Python tests and golden manifests that exercise the removed system.

The repository keeps the local `commit-code` skill.

## 4. Machine identity

`bootstrap.sh` generates a gitignored `.machine.nix` in the repository:

```nix
{
  username = "example";
  homeDirectory = "/Users/example";
  nixSystem = "aarch64-darwin";
}
```

Bootstrap discovers these values from macOS system information. It does not
trust caller-controlled `USER` or `HOME` values as the identity source.

A Git flake excludes untracked and ignored files. Therefore, `rebuild.sh`
passes the absolute `.machine.nix` path in `DOTFILES_MACHINE` and invokes Nix
with `--impure`. The privileged invocation sets this variable explicitly
instead of depending on `sudo` environment preservation. `flake.nix` reads only
that explicit file from the impure environment. It rejects a missing file,
missing fields, a non-absolute Home path, or a system other than
`aarch64-darwin`.

The core constructor remains pure:

```nix
mkDarwinConfiguration = machine: ...
```

`darwinConfigurations.mac` calls it with the local machine identity. Flake
checks call it with synthetic identities, so the reusable configuration can be
evaluated without machine-local state.

## 5. Bootstrap and rebuild workflow

### 5.1 Bootstrap

`bootstrap.sh` is the one-time entry point. It:

1. verifies Apple Silicon macOS and Xcode Command Line Tools;
2. loads an existing Nix daemon environment or installs multi-user Nix from the
   current official installer;
3. creates `~/.dotfiles` as a symlink to the current repository;
4. generates `.machine.nix` from macOS account information;
5. performs the first `darwin-rebuild switch` with the explicit impure identity;
6. cleans old architecture state only after the switch succeeds.

The `~/.dotfiles` rule is strict:

- create it when absent;
- accept it when it already resolves to the current repository;
- stop when it is a regular file, a directory, a broken link, or a link to a
  different location;
- never delete or replace a conflicting `~/.dotfiles` entry.

### 5.2 Rebuild

`rebuild.sh` is the only daily wrapper. It:

1. resolves its own repository directory;
2. confirms that `~/.dotfiles` resolves to that directory;
3. validates that `.machine.nix` exists;
4. passes its absolute path through `DOTFILES_MACHINE`;
5. executes `darwin-rebuild switch --impure --flake ~/.dotfiles#mac`;
6. runs idempotent legacy cleanup after a successful switch.

It does not implement `--check`, dry-run planning, doctor, JSON output, custom
rollback, or platform-specific apply modes. Users can run `nix flake check`
directly when they want a build-time validation command.

## 6. Configuration ownership

nix-darwin and Home Manager continue to manage:

- Nix settings and system configuration;
- packages;
- Git configuration;
- SSH configuration;
- `~/.config/git/local.inc` and `~/.ssh/config.local` integration.

The two local include files remain user-owned. The repository does not read,
overwrite, back up, or delete their contents.

Git and SSH stay expressed through their Home Manager program options. They are
not converted into hand-written out-of-store files.

## 7. Agent rules

The current shared `ai-agent/rules/common.md` becomes the repository-root
`AGENTS.md`. The Codex- and Claude-specific rule fragments are removed, along
with rule compilation and generated provenance headers.

Home Manager creates these out-of-store links:

```text
~/.codex/AGENTS.md   -> ~/.dotfiles/AGENTS.md
~/.claude/CLAUDE.md  -> ~/.dotfiles/AGENTS.md
```

Cursor receives no global rule link. Cursor's stable file contract supports
project rules and global skills, while its global User Rules remain a product
setting rather than a stable dotfiles target.

Editing `AGENTS.md` changes the live Codex and Claude rule immediately. A
rebuild is needed only when the link declaration changes.

## 8. Agent skills

The direct children of `ai-agent/skills/` are the canonical local skill set.
For every `<skill-id>`, Home Manager creates:

```text
~/.agents/skills/<skill-id>  -> ~/.dotfiles/ai-agent/skills/<skill-id>
~/.claude/skills/<skill-id>  -> ~/.dotfiles/ai-agent/skills/<skill-id>
~/.cursor/skills/<skill-id>  -> ~/.dotfiles/ai-agent/skills/<skill-id>
```

The three skill roots remain ordinary directories. Dotfiles owns only the
individual names present in the repository, so unrelated machine-local skills
remain available.

Nix validates that every direct child:

- is a directory;
- has an ID containing only lowercase ASCII letters, digits, and hyphens;
- contains `SKILL.md`.

It does not parse YAML frontmatter or compile skill contents.

The Git flake discovers only tracked directory entries. The workflow for a new,
removed, or renamed skill is therefore:

```text
git add/rm <skill path>
~/.dotfiles/rebuild.sh
```

Editing files inside an already linked skill takes effect immediately without
a rebuild.

## 9. Skill conflict handling

Repository-owned skill names overwrite same-name entries without backup:

- an absent target is created;
- an existing symlink is replaced;
- an existing regular file is replaced;
- an existing ordinary directory is recursively deleted, then replaced with
  the managed symlink.

Home Manager's `force` option does not replace ordinary directories. A small
activation entry therefore removes only exact same-name directories before
`linkGeneration`.

The activation entry derives its targets from the validated repository skill
IDs and the three fixed roots. It refuses paths outside those roots and never
iterates over unrelated entries. It does not create backups.

This overwrite behavior applies only to Agent rules and declared skill names.
Git, SSH, `~/.dotfiles`, and unrelated files retain their own safer conflict
behavior.

## 10. Migration and legacy cleanup

The first successful switch replaces old Agent links with Home Manager-owned
out-of-store links. After that switch succeeds, bootstrap or rebuild removes
these targets in order:

```text
~/.local/bin/dot
~/.local/state/dotfiles/
```

The state directory is removed recursively, including the old machine identity,
CLI and platform profiles, manifests, receipts, and conflict backups. This
deletion is intentional and irreversible.

`~/.local/bin/dot` is removed only when it is a symlink into the old dotfiles
state or profile tree. A regular file or an unrelated symlink is not deleted;
cleanup reports the conflict and returns failure.

Cleanup is idempotent. If the Nix switch fails, cleanup does not run and all old
runtime state remains. If cleanup fails after a successful switch, the new
configuration remains active and the wrapper reports the precise residual
path.

The migration does not run global Nix garbage collection. Old Store objects and
system generations remain under Nix ownership and become collectible when no
generation references them.

## 11. Failure behavior

The wrappers add only errors needed to establish their prerequisites:

- unsupported operating system or architecture;
- missing Xcode Command Line Tools;
- unsafe or conflicting `~/.dotfiles`;
- missing or invalid `.machine.nix`;
- unsafe legacy cleanup target.

Nix evaluation, build, and activation errors pass through unchanged. A failed
switch leaves the previous generation active. The repository adds no custom
transaction, rollback, diagnostic status model, or recovery protocol.

## 12. Validation and tests

`nix flake check` verifies:

- pure configuration evaluation with two synthetic usernames and Home paths;
- nix-darwin and Home Manager builds;
- Codex and Claude rule mappings;
- three target mappings for every local skill;
- skill ID, directory, and `SKILL.md` assertions;
- absence of the external skill input and `brainstorming` deployment;
- Nix formatting.

Shell validation verifies:

- `bootstrap.sh` and `rebuild.sh` with ShellCheck;
- identity generation against a controlled fixture;
- `~/.dotfiles` creation, idempotence, and conflict refusal in a temporary Home;
- exact legacy cleanup behavior;
- refusal to delete an unrelated `~/.local/bin/dot`;
- exact same-name skill replacement without affecting unrelated skills.

Tests factor filesystem operations into small shell functions and use temporary
directories. They do not install Nix, call `sudo`, activate nix-darwin, or
modify the developer's real Home.

The supported commands are:

```text
./bootstrap.sh
./rebuild.sh
nix flake check
nix fmt
```

## 13. Success criteria

The refactor is complete when:

1. a fresh Apple Silicon Mac can bootstrap from a clone;
2. the same tracked repository works for different macOS usernames through
   separate `.machine.nix` files;
3. Codex and Claude read the same root `AGENTS.md`;
4. Codex, Claude, and Cursor receive every repository skill as an individual
   direct symlink;
5. unrelated local skills remain untouched;
6. same-name skill conflicts are overwritten without backup;
7. editing an existing rule or skill changes the live file immediately;
8. Git, SSH, packages, and system configuration still build through Home
   Manager and nix-darwin;
9. no `dot` executable, Python CLI, external skill, Agent bundle, or old runtime
   state remains after successful migration;
10. flake checks, shell tests, ShellCheck, and formatting pass.

## 14. Non-goals

This design does not add:

- third-party skill installation or version pinning;
- per-platform skill profiles;
- Cursor global User Rules automation;
- secrets management;
- Linux support;
- multiple host profiles;
- custom drift detection, conflict previews, backups, receipts, or rollback;
- background synchronization or file watching;
- a compatibility shim for the removed `dot` commands.
