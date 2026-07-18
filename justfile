set shell := ["zsh", "-cu"]

test:
    bash tests/shell/run.sh

check:
    nix flake check

format:
    nix fmt
