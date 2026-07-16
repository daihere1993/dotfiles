from __future__ import annotations

import json
import unittest
from pathlib import Path

from dotfiles_cli.errors import ConflictError
from dotfiles_cli.models import (
    ConflictResult,
    ConflictStatus,
    DeploymentManifest,
    Diagnostic,
    DiagnosticStatus,
    MachineIdentity,
    Resource,
)
from dotfiles_cli.present import (
    DomainPreflight,
    Style,
    apply_check_has_conflicts,
    humanize_reason,
    parse_preflight_conflicts,
    render_apply_check_json,
    render_apply_check_text,
    render_doctor_text,
    render_validate_text,
    shorten_store_path,
    shorten_user_path,
)


class PresentTests(unittest.TestCase):
    def test_shorten_user_path(self) -> None:
        home = Path("/Users/alice")
        self.assertEqual(
            shorten_user_path("/Users/alice/.codex/AGENTS.md", home),
            "~/.codex/AGENTS.md",
        )

    def test_shorten_store_path(self) -> None:
        store = "/nix/store/abc123-darwin-system-25.05.20250101"
        self.assertEqual(shorten_store_path(store), "darwin-system-25.05.20250101")

    def test_parse_preflight_conflicts(self) -> None:
        message = (
            "platform preflight found conflicts:\n"
            "/Users/alice/.ssh/config: existing target cannot be proven to belong "
            "to the active or desired generation"
        )
        conflicts = parse_preflight_conflicts(message)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].target, "/Users/alice/.ssh/config")
        self.assertEqual(conflicts[0].reason, "not managed by dotfiles")

    def test_render_apply_check_text_hides_quiet_resources(self) -> None:
        identity = MachineIdentity("alice", "/Users/alice")
        resource = Resource(
            "ai-agent.codex.skill.demo",
            "ai-agent.codex",
            "directory-link",
            "/Users/alice/.agents/skills/demo",
            ("demo",),
            link_target="/Users/alice/profile/codex/skills/demo",
            store_path="/nix/store/demo",
            directory_sha256="digest",
        )
        manifest = DeploymentManifest(identity, "codex", (resource,), ())
        domains = [
            DomainPreflight(
                domain="codex",
                store=Path("/nix/store/abc123-agent-codex"),
                resource_count=1,
                results=(
                    ConflictResult(
                        ConflictStatus.REPLACEABLE_MANAGED,
                        resource,
                        "target matches the active generation",
                    ),
                ),
            )
        ]
        output = render_apply_check_text(domains, identity=identity, style=Style(enabled=False))
        self.assertIn("Ready", output)
        self.assertIn("codex", output)
        self.assertNotIn("REPLACEABLE_MANAGED", output)
        self.assertNotIn("/Users/alice/.agents/skills/demo", output)

    def test_render_apply_check_text_shows_blocked_domain(self) -> None:
        identity = MachineIdentity("alice", "/Users/alice")
        manifest = DeploymentManifest(identity, "system", (), ())
        error = ConflictError(
            "platform preflight found conflicts:\n"
            "/Users/alice/.ssh/config: existing target cannot be proven to belong "
            "to the active or desired generation"
        )
        domains = [
            DomainPreflight(
                domain="system",
                store=Path("/nix/store/abc123-darwin-system"),
                resource_count=2,
                results=(),
                error=error,
            )
        ]
        output = render_apply_check_text(domains, identity=identity, style=Style(enabled=False))
        self.assertIn("Blocked", output)
        self.assertIn("~/.ssh/config", output)
        self.assertIn("not managed by dotfiles", output)
        self.assertTrue(apply_check_has_conflicts(domains))

    def test_render_apply_check_json(self) -> None:
        identity = MachineIdentity("alice", "/Users/alice")
        resource = Resource(
            "ai-agent.codex.skill.demo",
            "ai-agent.codex",
            "directory-link",
            "/Users/alice/.agents/skills/demo",
            ("demo",),
            link_target="/Users/alice/profile/codex/skills/demo",
            store_path="/nix/store/demo",
            directory_sha256="digest",
        )
        domains = [
            DomainPreflight(
                domain="codex",
                store=Path("/nix/store/abc123-agent-codex"),
                resource_count=1,
                results=(
                    ConflictResult(
                        ConflictStatus.OVERWRITABLE_CONFLICT,
                        resource,
                        "existing user-owned skill can be backed up and overwritten",
                    ),
                ),
            )
        ]
        payload = json.loads(render_apply_check_json(domains, identity=identity))
        self.assertEqual(payload["summary"]["blocked"], ["codex"])
        self.assertEqual(payload["summary"]["exitCode"], 3)
        self.assertEqual(
            payload["blocked"]["codex"]["conflicts"][0]["reason"],
            "user-owned skill (can overwrite)",
        )

    def test_render_doctor_text_groups_issues_and_info(self) -> None:
        identity = MachineIdentity("alice", "/Users/alice")
        diagnostics = [
            Diagnostic(
                "cursor",
                DiagnosticStatus.HEALTHY,
                "managed target matches the active manifest",
                target="/Users/alice/.cursor/skills/demo",
            ),
            Diagnostic(
                "cursor",
                DiagnosticStatus.UNSUPPORTED_OPTIONAL,
                "Cursor global rules have no supported filesystem interface",
            ),
        ]
        output = render_doctor_text(diagnostics, identity=identity, style=Style(enabled=False))
        self.assertIn("Info", output)
        self.assertIn("global rules not supported via filesystem", output)
        self.assertNotIn("HEALTHY", output)
        self.assertIn("Result: healthy (exit 0)", output)

    def test_render_validate_text(self) -> None:
        identity = MachineIdentity("alice", "/Users/alice")
        output = render_validate_text(
            identity=identity,
            local_skill_count=1,
            external_skill_count=1,
            skill_affects=[("external:demo", ["codex", "claude"])],
            style=Style(enabled=False),
        )
        self.assertIn("Checks", output)
        self.assertIn("external:demo → codex, claude", output)
        self.assertIn("Result: validation passed (exit 0)", output)

    def test_shorten_user_path_home(self) -> None:
        home = Path("/Users/alice")
        self.assertEqual(shorten_user_path("/Users/alice", home), "~")

    def test_humanize_reason_passthrough(self) -> None:
        self.assertEqual(humanize_reason("custom reason"), "custom reason")


if __name__ == "__main__":
    unittest.main()
