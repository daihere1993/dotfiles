# dotfiles

This repository is the source of truth for one Apple Silicon macOS system and
for shared Codex, Claude Code, and Cursor skills. nix-darwin manages the system,
Home Manager manages user configuration, and Git records content history.

The repository does not manage credentials, private keys, sessions, vendor
databases, project-level Agent files, or Cursor User Rules.

## First installation

Clone the repository, then run:

```sh
./scripts/bootstrap.sh
```

Bootstrap verifies Apple Silicon macOS and Xcode Command Line Tools, installs
multi-user Nix when needed, links the checkout at `~/.dotfiles`, writes the
machine-local identity, activates nix-darwin, and removes legacy deployment
state after a successful switch.

`~/.dotfiles` must either be absent or already resolve to this checkout.
Bootstrap refuses regular files, directories, broken links, and links to other
locations. Agent vendor and GitHub authentication remain manual.

## Daily use

Apply tracked configuration with:

```sh
~/.dotfiles/scripts/rebuild.sh
```

Run validation or formatting directly:

```sh
nix flake check
nix fmt
```

Nix generations provide system rollback. Git provides content history. The old
`dot` CLI, doctor, per-platform apply, dry-run planner, conflict backups, event
stream, and custom rollback are no longer available.

## Zsh

Home Manager is the only source of zsh configuration. The declarations live in
`zsh/default.nix`, and the version-controlled proxy functions live in
`zsh/proxy.zsh`. Do not edit the generated `~/.zshrc`, `~/.zprofile`, or
`~/.zshenv` files. Change the tracked sources, validate them, then rebuild:

```sh
nix flake check
~/.dotfiles/scripts/rebuild.sh
```

Open a new terminal or run `exec zsh` after a successful rebuild. Home Manager
enables completion, autosuggestions, syntax highlighting, shared deduplicated
history, and the Starship prompt. Oh My Zsh, Powerlevel10k, NVM, pyenv, and
hand-written tool paths are intentionally not loaded.

Add executables needed by every project to `home.packages`. Put project-only
tools in that project's flake or development shell. Use `home.sessionPath` only
for a stable external path that Nix cannot provide. Put shell initialization in
`zsh/default.nix` or a focused managed script instead of editing generated
files.

The following proxy commands are available but are never run during shell
startup:

```text
haitunwan_proxy_on
clash_proxy_on
disable_socks_proxy
proxy_off
```

They modify the current shell and may also modify macOS network, Git, npm,
pnpm, VS Code, and Cursor settings. Confirm those side effects before using
them.

Store the Cursor API key in the login keychain as an application password with
service `nok-cursor-api-key` and account equal to the macOS username. Create or
update it through Keychain Access so the value never appears in a command-line
argument, Git, the Nix store, or logs. A shell preserves an inherited non-empty
`CURSOR_API_KEY`; otherwise it silently queries that keychain item.

Home Manager force-replaces existing `~/.zshrc`, `~/.zprofile`, and `~/.zshenv`
files during activation. Rebuild does not back them up. Copy any content you
still need before the first rebuild. After activation, a Nix rollback restores
an earlier managed generation, not the hand-written files that preceded Home
Manager ownership.

## Neovim

Home Manager installs Neovim and its base command-line dependencies. It links
`~/.config/nvim` to the writable configuration at `~/.dotfiles/nvim`, so
editing either path changes the repository working tree immediately.

Edits to tracked files under `nvim/` do not require a rebuild. Add, remove, or
rename files in Git before rebuilding so the flake can see them. Changes to the
Neovim package, dependencies, or Home Manager declarations require:

```sh
~/.dotfiles/scripts/rebuild.sh
```

Plugins, Mason tools, Treesitter parsers, caches, and state remain under the
standard XDG data, cache, and state directories. They are not part of the
dotfiles repository. Nix generations roll back packages and link declarations;
use Git to restore Neovim configuration content.

The initial migration preserves the existing Neovim configuration and plugin
lock file without cleaning up or upgrading them.

## Homebrew and WezTerm

nix-homebrew pins the native Apple Silicon Homebrew installation at
`/opt/homebrew`. The first rebuild migrates an existing standard installation
into nix-homebrew management. nix-darwin then installs WezTerm from the
`wezterm` cask.

Homebrew uses an incremental policy: each rebuild installs missing declared
packages but keeps formulae, casks, and taps installed manually. Apply changes
with the standard rebuild command:

```sh
~/.dotfiles/scripts/rebuild.sh
```

## Machine identity

Bootstrap writes `.machine.nix` in the checkout:

```nix
{
  username = "example";
  homeDirectory = "/Users/example";
  nixSystem = "aarch64-darwin";
}
```

The file is ignored by Git and must not be copied between machines. Bootstrap
derives its values from the macOS account database instead of `USER` or `HOME`.
Rebuild passes its absolute path to Nix through `DOTFILES_MACHINE` and evaluates
the local configuration with `--impure`.

## Agent rules and skills

Shared rules live at `ai-agent/AGENTS.md`. Home Manager creates
out-of-store links for Codex and Claude:

```text
~/.codex/AGENTS.md   -> ~/.dotfiles/ai-agent/AGENTS.md
~/.claude/CLAUDE.md  -> ~/.dotfiles/ai-agent/AGENTS.md
```

Cursor global User Rules remain a product setting and have no managed file.

Every direct child of `ai-agent/skills/` is a managed local skill. A
skill ID may contain lowercase ASCII letters, digits, and hyphens, and the
directory must contain `SKILL.md`. Each skill is linked individually:

```text
~/.agents/skills/<skill-id>  -> ~/.dotfiles/ai-agent/skills/<skill-id>
~/.claude/skills/<skill-id>  -> ~/.dotfiles/ai-agent/skills/<skill-id>
~/.cursor/skills/<skill-id>  -> ~/.dotfiles/ai-agent/skills/<skill-id>
```

Editing an existing rule or skill takes effect immediately. Adding, removing,
or renaming a skill requires tracking the change before rebuilding:

```sh
git add ai-agent/skills/<skill-id>
~/.dotfiles/scripts/rebuild.sh
```

Dotfiles owns only skill IDs present in this repository. A rebuild replaces a
same-name file, link, or directory without backup; unrelated local skills stay
untouched. External skills and per-platform skill profiles are not supported.

## Git and SSH

Home Manager continues to generate the main Git and SSH configuration. These
optional includes remain user-owned and are never read, replaced, backed up, or
deleted:

```text
~/.config/git/local.inc
~/.ssh/config.local
```

## Legacy cleanup

Successful bootstrap and rebuild runs call cleanup automatically. To migrate an
additional existing machine independently, run:

```sh
~/.dotfiles/scripts/cleanup-legacy.sh
```

The script prints its deletion plan and asks for confirmation. It removes only
Agent links into `~/.local/state/dotfiles/platforms/`, a legacy-managed
`~/.local/bin/dot`, and the old state directory. It refuses an unrelated `dot`
entry and leaves ordinary files, directories, new Agent links, and unrelated
skills unchanged. Deleting the old state and its backups is irreversible; the
script does not run Nix garbage collection.
