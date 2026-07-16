from __future__ import annotations

from dataclasses import dataclass

from ..errors import ValidationError


@dataclass(frozen=True)
class AdapterContract:
    platform: str
    rules_filename: str | None
    rules_target: str | None
    skills_target: str


CONTRACTS = {
    "codex": AdapterContract("codex", "AGENTS.md", ".codex/AGENTS.md", ".agents/skills"),
    "claude": AdapterContract("claude", "CLAUDE.md", ".claude/CLAUDE.md", ".claude/skills"),
    "cursor": AdapterContract("cursor", None, None, ".cursor/skills"),
}


def get_adapter(platform: str) -> AdapterContract:
    try:
        return CONTRACTS[platform]
    except KeyError as error:
        raise ValidationError(f"unknown Agent platform: {platform}") from error
