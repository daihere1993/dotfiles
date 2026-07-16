from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotfiles_cli.apply_flow import resolve_platform_actions
from dotfiles_cli.cli import main
from dotfiles_cli.errors import ValidationError
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
                partial = resolve_platform_actions(plans, interactive=True)
            self.assertFalse(partial)
            self.assertEqual(prompt.call_count, 1)
            for _, plan in plans.values():
                self.assertEqual(plan.actions[0].decision, ResourceDecision.OVERWRITE)

    def test_noninteractive_conflicts_default_to_skip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plans = {"codex": self._entry(Path(temporary), "codex")}
            partial = resolve_platform_actions(plans, interactive=False)
            self.assertTrue(partial)
            self.assertEqual(
                plans["codex"][1].actions[0].decision,
                ResourceDecision.SKIP,
            )


class ErrorRenderingTests(unittest.TestCase):
    def test_main_renders_dotfiles_error_without_traceback(self) -> None:
        error = ValidationError("unsafe state", next_step="Fix its permissions.")
        with (
            patch("dotfiles_cli.cli._cmd_init", side_effect=error),
            patch("dotfiles_cli.cli.stderr_enabled", return_value=False),
            patch("sys.stderr") as stderr,
        ):
            self.assertEqual(main(["init"]), error.exit_code)
        output = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("unsafe state", output)
        self.assertIn("Fix its permissions.", output)


if __name__ == "__main__":
    unittest.main()
