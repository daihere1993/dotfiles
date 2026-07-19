{ pkgs, username, homeDirectory, ... }:
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
    casks = [ "wezterm" ];
    onActivation.cleanup = "none";
  };
}
