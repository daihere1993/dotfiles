{ repository }:
let
  flake = builtins.getFlake ("path:" + repository);
in
flake.lib.agentConfig

