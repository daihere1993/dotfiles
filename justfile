set shell := ["zsh", "-cu"]

test:
    PYTHONPATH=cli python3 -m unittest discover -s tests -v

validate:
    PYTHONPATH=cli python3 -m dotfiles_cli validate

check:
    nix flake check

format:
    nix fmt

