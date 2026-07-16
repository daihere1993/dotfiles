{ pkgs, ... }:
{
  home.packages = with pkgs; [
    nodejs
    python3
    pnpm
  ];
}

