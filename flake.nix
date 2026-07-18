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
  };

  outputs = inputs@{ self, nixpkgs, nix-darwin, home-manager, ... }:
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
            ./modules/darwin/common.nix
            home-manager.darwinModules.home-manager
            {
              home-manager = {
                useGlobalPkgs = true;
                useUserPackages = true;
                extraSpecialArgs = {
                  inherit (identity) username homeDirectory;
                };
                users.${identity.username} = import ./modules/home/common.nix;
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

      skillEntries = builtins.readDir ./modules/ai-agent/skills;
      skillIds = builtins.attrNames skillEntries;
      skillRoots = [
        ".agents/skills"
        ".claude/skills"
        ".cursor/skills"
      ];
      expectedAgentLinks = [
        {
          target = ".codex/AGENTS.md";
          source = "${testMachine.homeDirectory}/.dotfiles/modules/ai-agent/AGENTS.md";
        }
        {
          target = ".claude/CLAUDE.md";
          source = "${testMachine.homeDirectory}/.dotfiles/modules/ai-agent/AGENTS.md";
        }
      ] ++ builtins.concatMap
        (skillId: map
          (root: {
            target = "${root}/${skillId}";
            source = "${testMachine.homeDirectory}/.dotfiles/modules/ai-agent/skills/${skillId}";
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
          assert !(builtins.elem "brainstorming" skillIds);
          pkgs.runCommand "dotfiles-no-external-skills" { } ''
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
            nativeBuildInputs = [ pkgs.nixpkgs-fmt pkgs.shellcheck ];
          } ''
          shellcheck \
            ${self}/scripts/*.sh \
            ${self}/tests/shell/*.sh \
            ${self}/modules/ai-agent/remove-conflicting-skill-directory.sh
          nixpkgs-fmt --check ${self}/flake.nix ${self}/modules
          touch "$out"
        '';
      };
    };
}
