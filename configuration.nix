{ config, pkgs, username, homeDirectory, ... }:
let
  homebrewSource = config.nix-homebrew.package;
in
{
  # Configure the shared nix-darwin platform and Nix daemon behavior.
  nixpkgs.hostPlatform = "aarch64-darwin";

  nix = {
    enable = true;
    package = pkgs.nix;
    settings.experimental-features = [ "nix-command" "flakes" ];
    optimise.automatic = true;
  };

  # Bind the evaluated machine identity to the macOS system and local account.
  system = {
    primaryUser = username;
    stateVersion = 6;
  };

  users.users.${username}.home = homeDirectory;

  # Pin the native Homebrew installation and migrate an existing standard prefix.
  nix-homebrew = {
    enable = true;
    enableRosetta = false;
    user = username;
    autoMigrate = true;
    mutableTaps = true;
  };

  # Install macOS applications without removing manually managed Homebrew packages.
  homebrew = {
    enable = true;
    brews = [
      "herdr"
    ];
    casks = [ "wezterm" ];
    onActivation.cleanup = "none";
  };

  system.activationScripts.postActivation.text = ''
    # A migrated prefix can retain relative links to Homebrew's top-level
    # completions, docs, and manpages. nix-homebrew keeps those assets in the
    # Nix store, so refresh the otherwise-dangling links from its pinned source.
    link_homebrew_asset() {
      local homebrew_asset_source=$1
      local homebrew_asset_link=$2

      mkdir -p "''${homebrew_asset_link%/*}"
      if [[ -e "$homebrew_asset_link" && ! -L "$homebrew_asset_link" ]]; then
        echo "error: refusing to replace non-symlink $homebrew_asset_link" >&2
        exit 1
      fi
      ln -sfn "$homebrew_asset_source" "$homebrew_asset_link"
    }

    link_homebrew_asset ${homebrewSource}/completions/bash/brew \
      /opt/homebrew/etc/bash_completion.d/brew
    link_homebrew_asset ${homebrewSource}/completions/fish/brew.fish \
      /opt/homebrew/share/fish/vendor_completions.d/brew.fish
    link_homebrew_asset ${homebrewSource}/completions/zsh/_brew \
      /opt/homebrew/share/zsh/site-functions/_brew
    link_homebrew_asset ${homebrewSource}/docs \
      /opt/homebrew/share/doc/homebrew
    link_homebrew_asset ${homebrewSource}/manpages/README.md \
      /opt/homebrew/share/man/man1/README.md
    link_homebrew_asset ${homebrewSource}/manpages/brew.1 \
      /opt/homebrew/share/man/man1/brew.1
    unset -f link_homebrew_asset
  '';
}
