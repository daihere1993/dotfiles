# Neovim Nix Diagnostics Design

## Goal

Show Nix syntax errors in Neovim through the existing LSP diagnostic UI.

## Design

Add `nixd` to the `servers` table in `nvim/init.lua`. The existing Mason setup will install the server, and the existing LSP loop will configure and enable it. Keep the default `nixd` settings for this first step so syntax diagnostics do not depend on project-specific flake evaluation.

Leave `zsh/default.nix` unchanged. Its missing semicolon provides a known syntax error for verification.

## Verification

1. Parse the changed Lua configuration.
2. Start Neovim headlessly and allow Mason to install `nixd`.
3. Open `zsh/default.nix` and confirm that `nixd` publishes a syntax diagnostic near `programs.starship = {`.
