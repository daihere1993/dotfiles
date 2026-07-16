{ ... }:
{
  programs.git = {
    enable = true;
    settings = {
      init.defaultBranch = "main";
      push.autoSetupRemote = true;
      pull.rebase = false;
    };
    includes = [{ path = "~/.config/git/local.inc"; }];
  };
}
