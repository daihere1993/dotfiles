{ username, homeDirectory, ... }:
{
  imports = [
    ./git.nix
    ./ssh.nix
    ./development.nix
  ];

  home = {
    inherit username homeDirectory;
    stateVersion = "26.05";
  };

  programs.home-manager.enable = true;
}

