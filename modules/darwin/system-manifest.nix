{ config, pkgs, username, homeDirectory, nixSystem, ... }:
let
  homeConfig = config.home-manager.users.${username};
  homeGeneration = homeConfig.home.activationPackage;
  gitSource = homeConfig.xdg.configFile."git/config".source;
  sshSource = homeConfig.home.file.".ssh/config".source;
  manifest = {
    schemaVersion = 1;
    inherit username homeDirectory nixSystem;
    deploymentDomain = "system";
    resources = [
      {
        id = "home.git.config";
        owner = "home-manager";
        kind = "file-link";
        target = "${homeDirectory}/.config/git/config";
        linkTarget = "${homeGeneration}/home-files/.config/git/config";
        storePath = toString gitSource;
        sha256 = builtins.hashFile "sha256" gitSource;
        sources = [ "modules/home/git.nix" ];
      }
      {
        id = "home.ssh.config";
        owner = "home-manager";
        kind = "file-link";
        target = "${homeDirectory}/.ssh/config";
        linkTarget = "${homeGeneration}/home-files/.ssh/config";
        storePath = toString sshSource;
        sha256 = builtins.hashFile "sha256" sshSource;
        sources = [ "modules/home/ssh.nix" ];
      }
      {
        id = "home.git.local";
        owner = "local-user";
        kind = "local-prerequisite";
        target = "${homeDirectory}/.config/git/local.inc";
        managed = false;
        optional = true;
        sources = [ "modules/home/git.nix" ];
      }
      {
        id = "home.ssh.local";
        owner = "local-user";
        kind = "local-prerequisite";
        target = "${homeDirectory}/.ssh/config.local";
        managed = false;
        optional = true;
        sources = [ "modules/home/ssh.nix" ];
      }
    ];
    skills = [ ];
  };
  manifestPackage = pkgs.writeTextFile {
    name = "dotfiles-system-manifest";
    destination = "/share/dotfiles/system-manifest.json";
    text = builtins.toJSON manifest;
  };
in
{
  assertions = [
    {
      assertion = homeConfig.xdg.configFile ? "git/config";
      message = "Git target must be present in the system manifest";
    }
    {
      assertion = homeConfig.home.file ? ".ssh/config";
      message = "SSH target must be present in the system manifest";
    }
  ];
  environment.systemPackages = [ manifestPackage ];
  environment.pathsToLink = [ "/share/dotfiles" ];
}
