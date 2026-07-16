{ repository, identityJson }:
let
  flake = builtins.getFlake ("path:" + repository);
in
(flake.lib.mkDarwinConfiguration { inherit identityJson; }).system.drvPath

