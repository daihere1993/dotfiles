{ pkgs, username, homeDirectory, ... }:
{
  nixpkgs.hostPlatform = "aarch64-darwin";

  nix = {
    enable = true;
    package = pkgs.nix;
    settings.experimental-features = [ "nix-command" "flakes" ];
    optimise.automatic = true;
  };

  system = {
    primaryUser = username;
    stateVersion = 6;
  };

  users.users.${username}.home = homeDirectory;
}
