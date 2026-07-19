{ config, lib, ... }:
{
  # Cursor Agent and other user-installed tools keep stable launchers here.
  home.sessionPath = [ "$HOME/.local/bin" ];

  programs.zsh = {
    enable = true;
    dotDir = config.home.homeDirectory;
    enableCompletion = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;
    oh-my-zsh.enable = false;

    history = {
      size = 50000;
      save = 50000;
      append = true;
      share = true;
      ignoreDups = true;
      ignoreAllDups = true;
      saveNoDups = true;
      findNoDups = true;
      ignoreSpace = true;
      expireDuplicatesFirst = true;
    };

    shellAliases = {
      ".." = "cd ..";
      add = "git add .";
      push = "git push";
      pull = "git pull";
    };

    # Keep a managed login file even though no login-only initialization is needed.
    profileExtra = ''
      # Login shell initialization is managed by Home Manager.
    '';

    initContent = ''
      () {
        [[ -n "''${CURSOR_API_KEY-}" ]] && return 0

        local cursor_api_key
        cursor_api_key=$(/usr/bin/security find-generic-password \
          -a "$USER" -s nok-cursor-api-key -w 2>/dev/null) || return 0
        [[ -n "$cursor_api_key" ]] && export CURSOR_API_KEY="$cursor_api_key"
      }

      source ${./proxy.zsh}
    '';
  };

  programs.starship = {
    enable = true;
    enableZshIntegration = true;
    settings = {
      add_newline = false;
      format = "$directory$git_branch$git_status$cmd_duration$line_break$character";
      character = {
        success_symbol = "[❯](purple)";
        error_symbol = "[❯](red)";
      };
      cmd_duration.format = "[$duration]($style) ";
      git_branch.symbol = "";
    };
  };
}
