{ config, homeDirectory, lib, pkgs, ... }:
let
  repositoryRoot = "${homeDirectory}/.dotfiles";
in
{
  assertions = [
    {
      assertion = lib.versionAtLeast pkgs.neovim-unwrapped.version "0.12";
      message = "Neovim 0.12 or newer is required by the vim.pack configuration";
    }
  ];

  programs.neovim = {
    enable = true;
    package = pkgs.neovim-unwrapped;
    sideloadInitLua = true;
  };

  home.packages = with pkgs; [
    ripgrep
    fd
    tree-sitter
    gnumake
    unzip
  ];

  home.file.".config/nvim".source =
    config.lib.file.mkOutOfStoreSymlink "${repositoryRoot}/nvim";
}
