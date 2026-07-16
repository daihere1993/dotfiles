from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotfiles_cli.cli import _resolve_platform_actions
from dotfiles_cli.models import (
    ActivationPlan,
    ConflictResult,
    ConflictStatus,
    DeploymentManifest,
    MachineIdentity,
    Resource,
    ResourceDecision,
    SkillInventoryEntry,
)


class ConflictPromptTests(unittest.TestCase):
    def _entry(self, root: Path, platform: str) -> tuple[list, ActivationPlan]:
        identity = MachineIdentity("alice", str(root / "home"))
        target = identity.home / f".{platform}/skills/demo"
        resource = Resource(
            f"ai-agent.{platform}.skill.demo",
            f"ai-agent.{platform}",
            "directory-link",
            str(target),
            ("demo",),
            link_target=str(identity.home / f"profile/{platform}/skills/demo"),
            store_path=str(root / f"store-{platform}/skills/demo"),
            directory_sha256="digest",
        )
        skill = SkillInventoryEntry("local:demo", "demo", "skills/demo", "digest", "local", "demo")
        manifest = DeploymentManifest(identity, platform, (resource,), (skill,))
        result = ConflictResult(
            ConflictStatus.OVERWRITABLE_CONFLICT,
            resource,
            "eligible",
        )
        plan = ActivationPlan(
            platform,
            identity,
            str(identity.home / f"profile/{platform}"),
            str(root / f"store-{platform}"),
            manifest,
        )
        return [result], plan

    def test_overwrite_all_applies_to_remaining_platforms(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plans = {platform: self._entry(root, platform) for platform in ("codex", "claude")}
            with patch("builtins.input", return_value="a") as prompt:
                partial = _resolve_platform_actions(plans, interactive=True)
            self.assertFalse(partial)
            self.assertEqual(prompt.call_count, 1)
            for _, plan in plans.values():
                self.assertEqual(plan.actions[0].decision, ResourceDecision.OVERWRITE)

    def test_noninteractive_conflicts_default_to_skip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plans = {"codex": self._entry(Path(temporary), "codex")}
            partial = _resolve_platform_actions(plans, interactive=False)
            self.assertTrue(partial)
            self.assertEqual(
                plans["codex"][1].actions[0].decision,
                ResourceDecision.SKIP,
            )


if __name__ == "__main__":
    unittest.main()
