{
  description = "Shared declarative Apple Silicon macOS configuration";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-26.05-darwin";

    nix-darwin = {
      url = "github:nix-darwin/nix-darwin/nix-darwin-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    home-manager = {
      url = "github:nix-community/home-manager/release-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nix-homebrew.url = "github:zhaofengli/nix-homebrew";
  };

  outputs = inputs@{ self, nixpkgs, nix-darwin, home-manager, nix-homebrew, ... }:
    let
      system = "aarch64-darwin";
      pkgs = import nixpkgs { inherit system; };

      validateMachine = machine:
        if !builtins.isAttrs machine then
          throw "machine identity must be an attribute set"
        else if !(machine ? username) || !builtins.isString machine.username || machine.username == "" then
          throw "machine identity requires a non-empty username string"
        else if !(machine ? homeDirectory) || !builtins.isString machine.homeDirectory || machine.homeDirectory == "" then
          throw "machine identity requires a non-empty homeDirectory string"
        else if builtins.substring 0 1 machine.homeDirectory != "/" then
          throw "machine homeDirectory must be absolute"
        else if !(machine ? nixSystem) || !builtins.isString machine.nixSystem then
          throw "machine identity requires a nixSystem string"
        else if machine.nixSystem != system then
          throw "machine nixSystem must be ${system}"
        else
          machine;

      loadMachine = path:
        if path == "" then
          throw "DOTFILES_MACHINE is required; run scripts/bootstrap.sh or scripts/rebuild.sh"
        else if builtins.substring 0 1 path != "/" then
          throw "DOTFILES_MACHINE must be an absolute path"
        else if !builtins.pathExists path then
          throw "DOTFILES_MACHINE does not exist: ${path}"
        else
          validateMachine (import path);

      mkDarwinConfiguration = machine:
        let
          identity = validateMachine machine;
        in
        nix-darwin.lib.darwinSystem {
          system = identity.nixSystem;
          specialArgs = {
            inherit inputs;
            inherit (identity) username homeDirectory nixSystem;
          };
          modules = [
            ./configuration.nix
            home-manager.darwinModules.home-manager
            nix-homebrew.darwinModules.nix-homebrew
            {
              home-manager = {
                useGlobalPkgs = true;
                useUserPackages = true;
                extraSpecialArgs = {
                  inherit (identity) username homeDirectory;
                };
                users.${identity.username} = import ./home.nix;
              };
            }
          ];
        };

      testMachine = {
        username = "testuser";
        homeDirectory = "/Users/testuser";
        nixSystem = system;
      };
      otherTestMachine = {
        username = "otheruser";
        homeDirectory = "/Users/otheruser";
        nixSystem = system;
      };
      testConfiguration = mkDarwinConfiguration testMachine;
      otherTestConfiguration = mkDarwinConfiguration otherTestMachine;
      testHome = testConfiguration.config.home-manager.users.${testMachine.username};
      otherTestHome = otherTestConfiguration.config.home-manager.users.${otherTestMachine.username};
      testZshrc = testHome.home.file."./.zshrc".source;
      testZprofile = testHome.home.file."./.zprofile".source;
      testZshenv = testHome.home.file."./.zshenv".source;
      otherTestZshrc = otherTestHome.home.file."./.zshrc".source;
      otherTestZprofile = otherTestHome.home.file."./.zprofile".source;
      otherTestZshenv = otherTestHome.home.file."./.zshenv".source;
      testStarship = testHome.home.file.${testHome.programs.starship.configPath}.source;
      otherTestStarship = otherTestHome.home.file.${otherTestHome.programs.starship.configPath}.source;

      skillEntries = builtins.readDir ./ai-agent/skills;
      skillIds = builtins.attrNames skillEntries;
      skillRoots = [
        ".agents/skills"
        ".claude/skills"
        ".cursor/skills"
      ];
      expectedAgentLinks = [
        {
          target = ".codex/AGENTS.md";
          source = "${testMachine.homeDirectory}/.dotfiles/ai-agent/AGENTS.md";
        }
        {
          target = ".claude/CLAUDE.md";
          source = "${testMachine.homeDirectory}/.dotfiles/ai-agent/AGENTS.md";
        }
      ] ++ builtins.concatMap
        (skillId: map
          (root: {
            target = "${root}/${skillId}";
            source = "${testMachine.homeDirectory}/.dotfiles/ai-agent/skills/${skillId}";
          })
          skillRoots)
        skillIds;
      checkedAgentLinks = map
        (expected:
          let
            file = testHome.home.file.${expected.target}
              or (throw "missing Agent mapping: ${expected.target}");
          in
          assert file.force;
          expected // { actualSource = file.source; })
        expectedAgentLinks;
    in
    {
      lib = {
        inherit mkDarwinConfiguration;
      };

      darwinConfigurations.mac =
        mkDarwinConfiguration (loadMachine (builtins.getEnv "DOTFILES_MACHINE"));

      formatter.${system} = pkgs.nixpkgs-fmt;

      checks.${system} = {
        darwin-testuser = testConfiguration.system;
        darwin-otheruser = otherTestConfiguration.system;

        agent-links = pkgs.runCommand "dotfiles-agent-links" { } ''
          ${builtins.concatStringsSep "\n" (map
            (link: ''
              test "$(readlink ${pkgs.lib.escapeShellArg (toString link.actualSource)})" = \
                ${pkgs.lib.escapeShellArg link.source}
            '')
            checkedAgentLinks)}
          touch "$out"
        '';

        no-external-skills =
          assert !(inputs ? superpowers);
          pkgs.runCommand "dotfiles-no-external-skills" { } ''
            touch "$out"
          '';

        homebrew-configuration =
          assert testConfiguration.config.nix-homebrew.enable;
          assert testConfiguration.config.nix-homebrew.user == testMachine.username;
          assert testConfiguration.config.nix-homebrew.autoMigrate;
          assert !testConfiguration.config.nix-homebrew.enableRosetta;
          assert testConfiguration.config.nix-homebrew.mutableTaps;
          assert testConfiguration.config.homebrew.enable;
          assert testConfiguration.config.homebrew.onActivation.cleanup == "none";
          assert builtins.elem "wezterm" (map (cask: cask.name) testConfiguration.config.homebrew.casks);
          assert otherTestConfiguration.config.nix-homebrew.user == otherTestMachine.username;
          pkgs.runCommand "dotfiles-homebrew-configuration" { } ''
            touch "$out"
          '';

        zsh-configuration =
          let
            validateZsh = home:
              assert home.programs.zsh.enable;
              assert home.programs.zsh.enableCompletion;
              assert home.programs.zsh.autosuggestion.enable;
              assert home.programs.zsh.syntaxHighlighting.enable;
              assert !home.programs.zsh.oh-my-zsh.enable;
              assert home.programs.zsh.history.size == 50000;
              assert home.programs.zsh.history.save == 50000;
              assert home.programs.zsh.history.append;
              assert home.programs.zsh.history.share;
              assert home.programs.zsh.history.ignoreDups;
              assert home.programs.zsh.history.ignoreAllDups;
              assert home.programs.zsh.history.saveNoDups;
              assert home.programs.zsh.history.findNoDups;
              assert home.programs.zsh.history.ignoreSpace;
              assert home.programs.zsh.history.expireDuplicatesFirst;
              assert home.home.sessionPath == [ "$HOME/.local/bin" ];
              assert builtins.hasAttr "./.zshrc" home.home.file;
              assert builtins.hasAttr "./.zprofile" home.home.file;
              assert builtins.hasAttr "./.zshenv" home.home.file;
              assert builtins.hasAttr home.programs.starship.configPath home.home.file;
              assert home.programs.starship.enable;
              assert home.programs.starship.enableZshIntegration;
              assert home.programs.starship.settings.git_branch.symbol == "";
              assert pkgs.lib.hasInfix "nok-cursor-api-key" home.programs.zsh.initContent;
              assert pkgs.lib.hasInfix ''-a "$USER"'' home.programs.zsh.initContent;
              true;
          in
          assert validateZsh testHome;
          assert validateZsh otherTestHome;
          assert pkgs.lib.all
            (name: pkgs.lib.hasInfix "${name}()" (builtins.readFile ./zsh/proxy.zsh))
            [
              "haitunwan_proxy_on"
              "clash_proxy_on"
              "disable_socks_proxy"
              "proxy_off"
            ];
          pkgs.runCommand "dotfiles-zsh-configuration" { } ''
            touch "$out"
          '';

        zsh-generated-content = pkgs.runCommand "dotfiles-zsh-generated-content"
          {
            nativeBuildInputs = [ pkgs.zsh ];
          } ''
          test_zshrc=${pkgs.lib.escapeShellArg (toString testZshrc)}
          test_zprofile=${pkgs.lib.escapeShellArg (toString testZprofile)}
          test_zshenv=${pkgs.lib.escapeShellArg (toString testZshenv)}
          other_zshrc=${pkgs.lib.escapeShellArg (toString otherTestZshrc)}
          other_zprofile=${pkgs.lib.escapeShellArg (toString otherTestZprofile)}
          other_zshenv=${pkgs.lib.escapeShellArg (toString otherTestZshenv)}
          test_starship=${pkgs.lib.escapeShellArg (toString testStarship)}
          other_starship=${pkgs.lib.escapeShellArg (toString otherTestStarship)}
          proxy_source=${pkgs.lib.escapeShellArg (toString ./zsh/proxy.zsh)}
          zsh_module=${pkgs.lib.escapeShellArg (toString ./zsh/default.nix)}

          for generated in \
            "$test_zshrc" "$test_zprofile" "$test_zshenv" "$test_starship" \
            "$other_zshrc" "$other_zprofile" "$other_zshenv" "$other_starship"; do
            test -f "$generated"
          done

          ! grep -F 'lukewu' "$test_zshrc" "$test_zprofile" "$test_zshenv" \
            "$other_zshrc" "$other_zprofile" "$other_zshenv"
          ! grep -F '/Users/lukewu' "$test_zshrc" "$test_zprofile" "$test_zshenv" \
            "$other_zshrc" "$other_zprofile" "$other_zshenv"
          ! grep -F 'otheruser' "$test_zshrc" "$test_zprofile" "$test_zshenv"
          ! grep -F 'testuser' "$other_zshrc" "$other_zprofile" "$other_zshenv"
          ! grep -F '/Users/' "$proxy_source" "$zsh_module"

          grep -F -- '-a "$USER" -s nok-cursor-api-key -w' "$test_zshrc"
          grep -E '^source /nix/store/.+-proxy\.zsh$' "$test_zshrc"
          grep -F 'starship init zsh' "$test_zshrc"
          grep -F 'format = ' "$test_starship"

          for function_name in \
            haitunwan_proxy_on clash_proxy_on \
            disable_socks_proxy proxy_off; do
            grep -F "$function_name()" "$proxy_source"
          done

          ! grep -E '^[[:space:]]*(haitunwan_proxy_on|clash_proxy_on|disable_socks_proxy|proxy_off)([[:space:]]|$)' \
            "$test_zshrc" "$other_zshrc"
          ! grep -E 'oh-my-zsh\.sh|ZSH_THEME=|powerlevel10k|\.p10k\.zsh|NVM_DIR|pyenv|PNPM_HOME|\.yarn/|flutter/bin|depot_tools|windsurf/bin|Python\.framework|brew shellenv|alias (python|ninja|gn)=' \
            "$test_zshrc" "$test_zprofile" "$test_zshenv" \
            "$other_zshrc" "$other_zprofile" "$other_zshenv"

          zsh -n "$test_zshrc" "$test_zprofile" "$test_zshenv"
          zsh -n "$other_zshrc" "$other_zprofile" "$other_zshenv"

          touch "$out"
        '';

        machine-validation =
          assert !(builtins.tryEval (validateMachine null)).success;
          assert !(builtins.tryEval (validateMachine {
            username = "testuser";
            homeDirectory = "relative/home";
            nixSystem = system;
          })).success;
          assert !(builtins.tryEval (validateMachine {
            username = "testuser";
            homeDirectory = "/Users/testuser";
            nixSystem = "x86_64-darwin";
          })).success;
          pkgs.runCommand "dotfiles-machine-validation" { } ''
            touch "$out"
          '';

        shell-tests = pkgs.runCommand "dotfiles-shell-tests"
          {
            nativeBuildInputs = [ pkgs.bash pkgs.nix ];
          } ''
          DOTFILES_REPOSITORY=${pkgs.lib.escapeShellArg (toString self)} \
            bash ${self}/tests/shell/run.sh
          touch "$out"
        '';

        lint = pkgs.runCommand "dotfiles-lint"
          {
            nativeBuildInputs = [ pkgs.nixpkgs-fmt pkgs.shellcheck pkgs.zsh ];
          } ''
          shellcheck \
            ${self}/scripts/*.sh \
            ${self}/tests/shell/*.sh \
            ${self}/ai-agent/remove-conflicting-skill-directory.sh
          nixpkgs-fmt --check ${self}/flake.nix ${self}/configuration.nix \
            ${self}/home.nix ${self}/ai-agent/default.nix ${self}/zsh/default.nix
          zsh -n ${self}/zsh/proxy.zsh
          touch "$out"
        '';
      };
    };
}
