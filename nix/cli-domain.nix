{ repository, identityJson, platform }:
let
  flake = builtins.getFlake ("path:" + repository);
in
if platform == "system" then
  (flake.lib.mkDarwinConfiguration { inherit identityJson; }).system
else
  flake.lib.mkAgentBundle { inherit identityJson platform; }

