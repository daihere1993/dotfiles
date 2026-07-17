from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from dotfiles_cli.apply_events import ApplyPhase, ChangeEntry, ChangeVerb
from dotfiles_cli.apply_flow import ApplyOptions, ApplySession, resolve_platform_actions
from dotfiles_cli.apply_reporter import CollectingReporter, TextApplyReporter
from dotfiles_cli.compiler import compile_platform
from dotfiles_cli.errors import ValidationError
from dotfiles_cli.models import DeploymentState, MachineIdentity
from dotfiles_cli.present import (
    render_changes_plan,
    render_changes_summary,
)


class ApplyFlowTests(unittest.TestCase):
    def test_collecting_reporter_records_plan_and_build(self) -> None:
        reporter = CollectingReporter()
        reporter.emit(
            __import__("dotfiles_cli.apply_events", fromlist=["ApplyEvent"]).ApplyEvent(
                phase=ApplyPhase.PLAN,
                kind="plan_header",
                payload={"scope": "full apply", "identity": "alice"},
            )
        )
        self.assertEqual(reporter.events[0].phase, ApplyPhase.PLAN)

    def test_resolve_platform_actions_defaults_to_skip(self) -> None:
        from dotfiles_cli.models import (
            ActivationPlan,
            ConflictResult,
            ConflictStatus,
            DeploymentManifest,
            Resource,
            ResourceDecision,
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = MachineIdentity("alice", str(root / "home"))
            target = identity.home / ".codex/skills/demo"
            resource = Resource(
                "ai-agent.codex.skill.demo",
                "ai-agent.codex",
                "directory-link",
                str(target),
                ("demo",),
                link_target=str(identity.home / "profile/codex/skills/demo"),
                store_path=str(root / "store/skills/demo"),
                directory_sha256="digest",
            )
            manifest = DeploymentManifest(identity, "codex", (resource,), ())
            result = ConflictResult(
                ConflictStatus.OVERWRITABLE_CONFLICT,
                resource,
                "eligible",
            )
            plan = ActivationPlan(
                "codex",
                identity,
                str(identity.home / "profile/codex"),
                str(root / "store"),
                manifest,
            )
            plans = {"codex": ([result], plan)}
            partial = resolve_platform_actions(plans, interactive=False)
            self.assertTrue(partial)
            self.assertEqual(
                plans["codex"][1].actions[0].decision,
                ResourceDecision.SKIP,
            )

    def test_render_changes_plan_shows_migrate(self) -> None:
        identity = MachineIdentity("alice", "/Users/alice")
        entries = [
            ChangeEntry(
                domain="system",
                verb=ChangeVerb.MIGRATE,
                target="/Users/alice/.ssh/config",
                reason="will migrate to ~/.ssh/config.local",
            )
        ]
        output = render_changes_plan(
            entries,
            identity=identity,
            style=__import__("dotfiles_cli.present", fromlist=["Style"]).Style(
                enabled=False
            ),
        )
        self.assertIn("migrate", output)
        self.assertIn("~/.ssh/config", output)

    def test_render_changes_summary_blocked(self) -> None:
        entries = [
            ChangeEntry(
                domain="system",
                verb=ChangeVerb.BLOCKED,
                target="/Users/alice/.ssh/config",
                reason="not managed",
            )
        ]
        summary = render_changes_summary(
            entries,
            style=__import__("dotfiles_cli.present", fromlist=["Style"]).Style(enabled=False),
        )
        self.assertIn("Blocked", summary)


class ApplySessionCheckTests(unittest.TestCase):
    def test_noninteractive_apply_requires_yes(self) -> None:
        reporter = CollectingReporter()
        session = ApplySession(MagicMock(), reporter, ApplyOptions())
        with patch("sys.stdin.isatty", return_value=False):
            self.assertFalse(session._confirm_apply())

    def test_noninteractive_run_without_yes_stops_before_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = MachineIdentity("alice", str(root / "home"))
            identity.home.mkdir()
            bundle = root / "bundle"
            compile_platform(
                repository=Path(__file__).resolve().parents[1],
                platform="codex",
                identity=identity,
                output_root=bundle,
                artifact_root=str(bundle),
                skills=[],
            )
            reporter = CollectingReporter()
            session = ApplySession(MagicMock(), reporter, ApplyOptions(platform="codex"))
            with (
                patch("dotfiles_cli.apply_flow.reject_concurrent_apply"),
                patch("dotfiles_cli.apply_flow.archive_repository", return_value=root),
                patch("dotfiles_cli.apply_flow.read_identity", return_value=identity),
                patch("dotfiles_cli.apply_flow.build_domain", return_value=bundle),
                patch(
                    "dotfiles_cli.apply_flow.current_platform",
                    return_value=(DeploymentState.NOT_DEPLOYED, None, None),
                ),
                patch("dotfiles_cli.apply_flow.read_receipt", return_value=None),
                patch("dotfiles_cli.apply_flow.other_active_manifests", return_value=[]),
                patch("dotfiles_cli.apply_flow.activate_platform") as activate,
                patch("sys.stdin.isatty", return_value=False),
                self.assertRaisesRegex(ValidationError, "requires `--yes`"),
            ):
                session.run(root)
            activate.assert_not_called()
            self.assertEqual(
                sum(event.kind == "changes_rendered" for event in reporter.events),
                1,
            )

    def test_check_mode_does_not_emit_confirm(self) -> None:
        reporter = CollectingReporter()
        runner = MagicMock()
        options = ApplyOptions(check=True)
        session = ApplySession(runner, reporter, options)

        with (
            patch.object(session, "run", wraps=session.run),
            patch("dotfiles_cli.apply_flow.reject_concurrent_apply"),
            patch("dotfiles_cli.apply_flow.archive_repository", return_value=Path("/repo")),
            patch(
                "dotfiles_cli.apply_flow.read_identity",
                return_value=MachineIdentity("a", "/Users/a"),
            ),
            patch(
                "dotfiles_cli.apply_flow.build_domain",
                side_effect=AssertionError("build should not run"),
            ),
        ):
            pass

    def test_text_reporter_plan_section(self) -> None:
        identity = MachineIdentity("alice", "/Users/alice")
        stream = io.StringIO()
        reporter = TextApplyReporter(
            identity=identity,
            verbose=False,
            style=__import__("dotfiles_cli.present", fromlist=["Style"]).Style(enabled=False),
            stream=stream,
        )
        reporter.emit(
            __import__("dotfiles_cli.apply_events", fromlist=["ApplyEvent"]).ApplyEvent(
                phase=ApplyPhase.PLAN,
                kind="plan_header",
                payload={
                    "scope": "full apply (system → codex → claude → cursor)",
                    "identity": "alice",
                    "nixSystem": "aarch64-darwin",
                },
            )
        )
        output = stream.getvalue()
        self.assertIn("Plan", output)
        self.assertIn("full apply", output)


if __name__ == "__main__":
    unittest.main()
