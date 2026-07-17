{
  description = "Shared declarative macOS configuration and Agent configuration compiler";

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

    superpowers = {
      url = "github:obra/superpowers";
      flake = false;
    };
  };

  outputs = inputs@{ self, nixpkgs, nix-darwin, home-manager, ... }:
    let
      system = "aarch64-darwin";
      pkgs = import nixpkgs { inherit system; };
      profiles = import ./ai-agent/profiles/default.nix;
      external = import ./ai-agent/external-skills.nix { inherit inputs; };
      externalSkillSpecs = builtins.mapAttrs
        (key: entry:
          let
            source = external.sources.${entry.sourceId} or (throw "unknown source ${entry.sourceId}");
            input = inputs.${source.inputName} or (throw "missing flake input ${source.inputName}");
          in
          assert key == "${entry.sourceId}/${entry.skillId}";
          assert source.inputName == entry.sourceId;
          assert input ? narHash;
          {
            canonicalId = "external:${key}";
            targetId = entry.skillId;
            path = "${input.outPath}/${entry.path}";
            sourceKind = "external";
            sourcePath = entry.path;
            sourceId = entry.sourceId;
            narHash = input.narHash or (throw "external input ${entry.sourceId} lacks narHash");
            rev = input.rev or null;
          })
        external.skills;
      dotSrc = builtins.path {
        path = ./.;
        name = "dotfiles-cli-src";
        filter = path: type:
          let
            root = toString ./.;
            rel = if path == root then "" else pkgs.lib.removePrefix (root + "/") path;
          in
          rel == ""
          || rel == "pyproject.toml"
          || rel == "cli"
          || pkgs.lib.hasPrefix "cli/" rel;
      };
      dot = pkgs.python3Packages.buildPythonApplication {
        pname = "dotfiles-cli";
        version = "0.1.0";
        pyproject = true;
        src = dotSrc;
        build-system = [ pkgs.python3Packages.setuptools ];
        makeWrapperArgs = [ "--prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.nix ]}" ];
      };
      parseIdentity = identityJson:
        let identity = builtins.fromJSON identityJson;
        in assert identity.schemaVersion == 1;
        assert identity.nixSystem == system;
        identity;
      mkDarwinConfiguration = { identityJson }:
        let identity = parseIdentity identityJson;
        in nix-darwin.lib.darwinSystem {
          inherit system;
          specialArgs = {
            inherit inputs dot;
            username = identity.username;
            homeDirectory = identity.homeDirectory;
            nixSystem = identity.nixSystem;
          };
          modules = [
            ./modules/darwin/common.nix
            ./modules/darwin/system-manifest.nix
            home-manager.darwinModules.home-manager
            {
              home-manager = {
                useGlobalPkgs = true;
                useUserPackages = true;
                extraSpecialArgs = {
                  username = identity.username;
                  homeDirectory = identity.homeDirectory;
                };
                users.${identity.username} = import ./modules/home/common.nix;
              };
            }
          ];
        };
      mkAgentBundle =
        { identityJson
        , platform
        , commonRule ? builtins.path {
            path = ./ai-agent/rules/common.md;
            name = "dotfiles-common-rules.md";
          }
        , platformRule ? builtins.path {
            path = ./. + "/ai-agent/rules/agents/${platform}.md";
            name = "dotfiles-${platform}-rules.md";
          }
        }:
        let
          identity = parseIdentity identityJson;
          selected = profiles.${platform} or (throw "unknown platform ${platform}");
          localSkillSpec = canonicalId:
            let
              targetId = pkgs.lib.removePrefix "local:" canonicalId;
              sourcePath = "ai-agent/skills/${targetId}";
            in
            {
              inherit targetId sourcePath;
              canonicalId = canonicalId;
              path = toString (builtins.path {
                path = ./. + "/${sourcePath}";
                name = "dotfiles-skill-${targetId}";
              });
              sourceKind = "local";
            };
          skillArgument = canonicalId:
            if pkgs.lib.hasPrefix "local:" canonicalId then
              "--skill-spec ${pkgs.lib.escapeShellArg (builtins.toJSON (localSkillSpec canonicalId))}"
            else if pkgs.lib.hasPrefix "external:" canonicalId then
              let
                key = pkgs.lib.removePrefix "external:" canonicalId;
                spec = externalSkillSpecs.${key} or (throw "unknown external skill ${canonicalId}");
              in
              "--skill-spec ${pkgs.lib.escapeShellArg (builtins.toJSON spec)}"
            else throw "invalid canonical skill ID ${canonicalId}";
          ruleSpecs = if platform == "cursor" then [ ] else [
            {
              sourcePath = "ai-agent/rules/common.md";
              path = toString commonRule;
            }
            {
              sourcePath = "ai-agent/rules/agents/${platform}.md";
              path = toString platformRule;
            }
          ];
          ruleArgument = spec:
            "--rule-spec ${pkgs.lib.escapeShellArg (builtins.toJSON spec)}";
        in
        pkgs.runCommand "dotfiles-${platform}-bundle"
          {
            nativeBuildInputs = [ dot ];
            preferLocalBuild = true;
          } ''
          dot internal-compile \
            --platform ${platform} \
            --identity-json '${builtins.toJSON identity}' \
            --artifact-root "$out" \
            --output "$out" \
            ${builtins.concatStringsSep " " (map ruleArgument ruleSpecs)} \
            ${builtins.concatStringsSep " " (map skillArgument selected)}
        '';
      testIdentity = builtins.toJSON {
        schemaVersion = 1;
        username = "testuser";
        homeDirectory = "/Users/testuser";
        nixSystem = system;
      };
      secondTestIdentity = builtins.toJSON {
        schemaVersion = 1;
        username = "otheruser";
        homeDirectory = "/Users/otheruser";
        nixSystem = system;
      };
      testDarwin = (mkDarwinConfiguration { identityJson = testIdentity; }).system;
      secondTestDarwin = (mkDarwinConfiguration { identityJson = secondTestIdentity; }).system;
    in
    {
      lib = {
        inherit mkDarwinConfiguration mkAgentBundle;
        agentConfig = {
          inherit profiles;
          externalSkills = externalSkillSpecs;
        };
      };

      packages.${system} = {
        inherit dot;
        default = dot;
      };

      apps.${system}.dot = {
        type = "app";
        program = "${dot}/bin/dot";
        meta.description = "Validate and deploy this dotfiles repository";
      };

      formatter.${system} = pkgs.nixpkgs-fmt;

      checks.${system} = {
        dot = dot;
        darwin-testuser = testDarwin;
        darwin-otheruser = secondTestDarwin;
        system-manifest-present = pkgs.runCommand "dotfiles-system-manifest-present" { } ''
          test -f ${testDarwin}/sw/share/dotfiles/system-manifest.json
          touch $out
        '';
        codex-bundle = mkAgentBundle { identityJson = testIdentity; platform = "codex"; };
        claude-bundle = mkAgentBundle { identityJson = testIdentity; platform = "claude"; };
        cursor-bundle = mkAgentBundle { identityJson = testIdentity; platform = "cursor"; };
        agent-input-isolation =
          let
            alternateCommon = builtins.toFile "alternate-common-rules.md" "alternate\n";
            defaultCursor = (mkAgentBundle {
              identityJson = testIdentity;
              platform = "cursor";
            }).drvPath;
            alternateCursor = (mkAgentBundle {
              identityJson = testIdentity;
              platform = "cursor";
              commonRule = alternateCommon;
            }).drvPath;
            defaultCodex = (mkAgentBundle {
              identityJson = testIdentity;
              platform = "codex";
            }).drvPath;
            alternateCodex = (mkAgentBundle {
              identityJson = testIdentity;
              platform = "codex";
              commonRule = alternateCommon;
            }).drvPath;
          in
          assert defaultCursor == alternateCursor;
          assert defaultCodex != alternateCodex;
          pkgs.runCommand "dotfiles-agent-input-isolation" { } ''
            touch $out
          '';
        python-tests = pkgs.runCommand "dotfiles-python-tests"
          {
            nativeBuildInputs = [ pkgs.python3 ];
          } ''
          cd ${self}
          PYTHONPATH=cli python -m unittest discover -s tests -v
          touch $out
        '';
        lint = pkgs.runCommand "dotfiles-lint"
          {
            nativeBuildInputs = [ pkgs.ruff pkgs.shellcheck pkgs.nixpkgs-fmt ];
          } ''
          RUFF_NO_CACHE=true ruff check ${self}/cli ${self}/tests
          shellcheck ${self}/bootstrap/install ${self}/bootstrap/install-dot
          nixpkgs-fmt --check ${self}/flake.nix ${self}/modules ${self}/ai-agent
          touch $out
        '';
      };
    };
}
