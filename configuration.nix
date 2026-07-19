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
}
