{
  lib,
  buildNpmPackage,
  fetchFromGitHub,
}:

buildNpmPackage rec {
  pname = "beautiful-mermaid-cli";
  version = "0.2.4";

  src = fetchFromGitHub {
    owner = "okooo5km";
    repo = "beautiful-mermaid-cli";
    tag = "v${version}";
    hash = "sha256-WnkNHIEdUnEMimvvx7uqFcbeW54ANj4WuVsLJ7P0DU0=";
  };

  npmDepsHash = "sha256-gvBSGKcRE1imAX7a46ELvgxel+Za67pc9flTwI4+9l4=";

  meta = {
    description = "Render Mermaid diagrams as SVG/PNG/ASCII from the command line";
    homepage = "https://github.com/okooo5km/beautiful-mermaid-cli";
    license = lib.licenses.mit;
    mainProgram = "bm";
  };
}
