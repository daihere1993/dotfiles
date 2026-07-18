{ username, homeDirectory, ... }:
{
  imports = [
    ../ai-agent
    ./git.nix
    ./ssh.nix
    ./development.nix
    ./neovim.nix
  ];

  home = {
    inherit username homeDirectory;
    stateVersion = "26.05";
  };

  programs.home-manager.enable = true;
}
