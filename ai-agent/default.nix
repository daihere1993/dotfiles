{ config, homeDirectory, lib, pkgs, ... }:
let
  # Discover only well-formed direct child skill directories for deployment.
  skillsDirectory = ./skills;
  skillEntries = builtins.readDir skillsDirectory;
  allSkillIds = builtins.attrNames skillEntries;
  isValidSkillId = skillId:
    builtins.match "^[a-z0-9-]+$" skillId != null;
  hasSkillFile = skillId:
    builtins.pathExists (skillsDirectory + "/${skillId}/SKILL.md");
  skillIds = builtins.filter
    (skillId:
      skillEntries.${skillId} == "directory"
      && isValidSkillId skillId
      && hasSkillFile skillId)
    allSkillIds;
  invalidSkillKinds = builtins.filter
    (skillId: skillEntries.${skillId} != "directory")
    allSkillIds;
  invalidSkillIds = builtins.filter
    (skillId: !isValidSkillId skillId)
    allSkillIds;
  missingSkillFiles = builtins.filter
    (skillId: skillEntries.${skillId} == "directory" && !hasSkillFile skillId)
    allSkillIds;

  # Link to the mutable checkout so edits are visible without a Home Manager switch.
  repositoryRoot = "${homeDirectory}/.dotfiles";
  skillRoots = [
    ".agents/skills"
    ".claude/skills"
    ".cursor/skills"
  ];
  mkOutOfStoreFile = sourcePath: {
    source = config.lib.file.mkOutOfStoreSymlink "${repositoryRoot}/${sourcePath}";
    force = true;
  };
  ruleFiles = {
    ".codex/AGENTS.md" = mkOutOfStoreFile "ai-agent/AGENTS.md";
    ".claude/CLAUDE.md" = mkOutOfStoreFile "ai-agent/AGENTS.md";
  };
  skillFiles = lib.listToAttrs (lib.concatMap
    (skillId: map
      (root: {
        name = "${root}/${skillId}";
        value = mkOutOfStoreFile "ai-agent/skills/${skillId}";
      })
      skillRoots)
    skillIds);
  # Home Manager cannot replace real directories with links, so remove only managed
  # same-name skill directories immediately before link generation.
  removeConflictingSkillDirectories = lib.concatMapStringsSep "\n"
    (skillId: lib.concatMapStringsSep "\n"
      (root:
        let
          absoluteRoot = "${homeDirectory}/${root}";
          target = "${absoluteRoot}/${skillId}";
        in
        "${pkgs.bash}/bin/bash ${./remove-conflicting-skill-directory.sh} ${lib.escapeShellArgs [ target absoluteRoot skillId homeDirectory ]}")
      skillRoots)
    skillIds;
in
{
  assertions = [
    {
      assertion = invalidSkillKinds == [ ];
      message = "Agent skill entries must be directories: ${lib.concatStringsSep ", " invalidSkillKinds}";
    }
    {
      assertion = invalidSkillIds == [ ];
      message = "Agent skill IDs may contain only lowercase ASCII letters, digits, and hyphens: ${lib.concatStringsSep ", " invalidSkillIds}";
    }
    {
      assertion = missingSkillFiles == [ ];
      message = "Agent skill directories must contain SKILL.md: ${lib.concatStringsSep ", " missingSkillFiles}";
    }
  ];

  home.file = ruleFiles // skillFiles;

  home.activation.removeConflictingAgentSkillDirectories =
    lib.hm.dag.entryBetween [ "linkGeneration" ] [ "writeBoundary" ] ''
      ${removeConflictingSkillDirectories}
    '';
}
