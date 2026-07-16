{ inputs }:
{
  sources.superpowers = {
    inputName = "superpowers";
  };

  skills."superpowers/brainstorming" = {
    sourceId = "superpowers";
    skillId = "brainstorming";
    path = "skills/brainstorming";
  };
}
