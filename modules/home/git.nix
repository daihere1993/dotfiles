{ ... }:
{
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
}
