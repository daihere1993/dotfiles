{ config, homeDirectory, lib, pkgs, username, ... }:
let
  # Mutable editor configuration stays in the checkout instead of the Nix store.
  repositoryRoot = "${homeDirectory}/.dotfiles";

  # Discover only well-formed direct child skill directories for deployment.
  skillsDirectory = ./ai-agent/skills;
  skillEntries = builtins.readDir skillsDirectory;
  allSkillIds = builtins.attrNames skillEntries;
  isValidSkillId = skillId:
    builtins.match "^[a-z0-9-]+$" skillId != null;
  hasSkillFile = skillId:
    builtins.pathExists (skillsDirectory + "/${skillId}/SKILL.md");
  skillIds = builtins.filter
    (skillId:
      skillEntries.${skillId} == "directory"
      && isValidSkillId skillId
      && hasSkillFile skillId)
    allSkillIds;
  invalidSkillKinds = builtins.filter
    (skillId: skillEntries.${skillId} != "directory")
    allSkillIds;
  invalidSkillIds = builtins.filter
    (skillId: !isValidSkillId skillId)
    allSkillIds;
  missingSkillFiles = builtins.filter
    (skillId: skillEntries.${skillId} == "directory" && !hasSkillFile skillId)
    allSkillIds;

  skillRoots = [
    ".agents/skills"
    ".claude/skills"
    ".cursor/skills"
  ];
  mkOutOfStoreFile = sourcePath: {
    source = config.lib.file.mkOutOfStoreSymlink "${repositoryRoot}/${sourcePath}";
    force = true;
  };
  agentRuleFiles = {
    ".codex/AGENTS.md" = mkOutOfStoreFile "ai-agent/AGENTS.md";
    ".claude/CLAUDE.md" = mkOutOfStoreFile "ai-agent/AGENTS.md";
  };
  agentSkillFiles = lib.listToAttrs (lib.concatMap
    (skillId: map
      (root: {
        name = "${root}/${skillId}";
        value = mkOutOfStoreFile "ai-agent/skills/${skillId}";
      })
      skillRoots)
    skillIds);
in
{
  imports = [
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
    {
      assertion = invalidSkillKinds == [ ];
      message = "Agent skill entries must be directories: ${lib.concatStringsSep ", " invalidSkillKinds}";
    }
    {
      assertion = invalidSkillIds == [ ];
      message = "Agent skill IDs may contain only lowercase ASCII letters, digits, and hyphens: ${lib.concatStringsSep ", " invalidSkillIds}";
    }
    {
      assertion = missingSkillFiles == [ ];
      message = "Agent skill directories must contain SKILL.md: ${lib.concatStringsSep ", " missingSkillFiles}";
    }
  ];

  programs.neovim = {
    enable = true;
    package = pkgs.neovim-unwrapped;
    sideloadInitLua = true;
  };

  # Use out-of-store links so tracked edits take effect without rebuilding.
  home.file = agentRuleFiles // agentSkillFiles // {
    ".config/nvim".source =
      config.lib.file.mkOutOfStoreSymlink "${repositoryRoot}/nvim";
    ".config/wezterm" = {
      force = true;
      source = config.lib.file.mkOutOfStoreSymlink "${repositoryRoot}/wezterm";
    };
  };
}
