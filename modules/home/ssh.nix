{ ... }:
{
  programs.ssh = {
    enable = true;
    enableDefaultConfig = false;
    includes = [ "~/.ssh/config.local" ];
    settings."*" = {
      AddKeysToAgent = "yes";
      Compression = true;
      ControlMaster = "auto";
      ControlPersist = "10m";
      ServerAliveInterval = 60;
      ServerAliveCountMax = 3;
    };
  };
}
