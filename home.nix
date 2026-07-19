{ config, homeDirectory, lib, pkgs, username, ... }:
let
  # Mutable editor configuration stays in the checkout instead of the Nix store.
  repositoryRoot = "${homeDirectory}/.dotfiles";
in
{
  # Keep focused Home Manager concerns in their own modules.
  imports = [
    ./ai-agent
    ./zsh
  ];

  # Define the Home Manager account and keep its own CLI available.
  home = {
    inherit username homeDirectory;
    stateVersion = "26.05";

    # Shared development tools plus Neovim's direct command-line dependencies.
    packages = with pkgs; [
      nodejs
      python3
      pnpm
      curl
      jq
      ripgrep
      fd
      tree-sitter
      gnumake
      unzip
      # The font everything renders in
      nerd-fonts.hack
    ];
  };
  fonts.fontconfig.enable = true;
  home.sessionVariables.EDITOR = "nvim";

  programs.home-manager.enable = true;

  # Keep the portable Git configuration here; machine-local overrides stay untracked.
  programs.git = {
    enable = true;
    settings = {
      user = {
        name = "daihere1993";
        email = "daihere1993@gmail.com";
      };
      init.defaultBranch = "main";
      push.autoSetupRemote = true;
      pull.rebase = true;
    };
    includes = [{ path = "~/.config/git/local.inc"; }];
  };

  # Provide safe shared SSH defaults while allowing private hosts in an untracked file.
  programs.ssh = {
    enable = true;
    enableDefaultConfig = false;
    includes = [ "~/.ssh/config.local" ];
    settings = {
      "*" = {
        AddKeysToAgent = "yes";
        Compression = true;
        ControlMaster = "auto";
        ControlPersist = "10m";
        ServerAliveInterval = 60;
        ServerAliveCountMax = 3;
      };
      "github.com" = {
        HostName = "ssh.github.com";
        Port = 443;
        User = "git";
        IdentityFile = "~/.ssh/id_rsa";
      };
    };
  };

  # Neovim 0.12 supplies vim.pack, which the tracked Lua configuration requires.
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

  # Use an out-of-store link so tracked Lua edits take effect without rebuilding.
  home.file.".config/nvim".source =
    config.lib.file.mkOutOfStoreSymlink "${repositoryRoot}/nvim";
  home.file.".config/wezterm" = {
    # This exact path is declarative and may replace an unmanaged target.
    # The out-of-store link keeps tracked Lua edits live without rebuilding.
    force = true;
    source = config.lib.file.mkOutOfStoreSymlink "${repositoryRoot}/wezterm";
  };
}
