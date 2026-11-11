#!/bin/bash
set -euo pipefail

repository=${DOTFILES_REPOSITORY:-$(CDPATH='' cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)}

# Skill loaders (pi, ZCode, Claude Code) reject or silently drop skills whose
# frontmatter description exceeds 1024 characters; the description is the part
# injected into every session, so keep every skill under the shared limit.
python3 - "$repository/ai-agent/skills" <<'PYTHON'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
skills = sorted(path for path in root.iterdir() if (path / "SKILL.md").is_file())
assert skills, "no skills found under ai-agent/skills"

for skill in skills:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, f"{skill.name}: missing frontmatter"
    frontmatter = match.group(1)

    name = re.search(r"^name: (.+?)\s*$", frontmatter, re.M)
    assert name, f"{skill.name}: missing name"
    assert name.group(1) == skill.name, f"{skill.name}: name is {name.group(1)!r}, expected {skill.name!r}"

    description = re.search(r"^description: '(.*)'\s*$", frontmatter, re.M) \
        or re.search(r"^description: (.+?)\s*$", frontmatter, re.M)
    assert description, f"{skill.name}: missing description"
    value = description.group(1).replace("''", "'")
    if value in {">", ">-", "|", "|-"}:
        # Block scalar: the value is the indented lines below the marker,
        # folded with spaces (or newlines) in place of the line breaks.
        lines = []
        for line in frontmatter[description.end():].splitlines():
            if line and not line[0].isspace():
                break
            if line.strip():
                lines.append(line.strip())
        assert lines, f"{skill.name}: empty block-scalar description"
        joiner = "\n" if value.startswith("|") else " "
        value = joiner.join(lines)
    limit = 1024
    assert len(value) <= limit, (
        f"{skill.name}: description is {len(value)} characters, exceeds the {limit} limit"
    )
    print(f"ok {skill.name}: description {len(value)}/{limit} characters")
PYTHON
