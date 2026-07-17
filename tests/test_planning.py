from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dotfiles_cli.conflict import classify_manifests
from dotfiles_cli.hashing import directory_sha256, file_sha256
from dotfiles_cli.models import DeploymentManifest, MachineIdentity, Resource, SkillInventoryEntry
from dotfiles_cli.planning import (
    DomainAction,
    ResourceDelta,
    build_deployment_plan,
    build_plan_changes,
    plan_domain,
)


class DeploymentPlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.identity = MachineIdentity("alice", str(self.root / "home"))
        self.identity.home.mkdir()

    def _manifest(
        self,
        store: Path,
        *,
        content: str = "same",
        sources: tuple[str, ...] = ("skill",),
        skills: tuple[SkillInventoryEntry, ...] = (),
        domain: str = "codex",
    ) -> DeploymentManifest:
        artifact = store / "skills/demo"
        artifact.mkdir(parents=True, exist_ok=True)
        (artifact / "SKILL.md").write_text(content)
        resource = Resource(
            f"ai-agent.{domain}.skill.demo",
            f"ai-agent.{domain}",
            "directory-link",
            str(self.identity.home / f".{domain}/skills/demo"),
            sources,
            link_target=str(self.identity.home / f"profiles/{domain}/skills/demo"),
            store_path=str(artifact),
            directory_sha256=directory_sha256(artifact),
        )
        return DeploymentManifest(self.identity, domain, (resource,), skills)

    def _install_active(self, manifest: DeploymentManifest) -> None:
        resource = manifest.resources[0]
        profile_artifact = Path(resource.link_target)
        profile_artifact.parent.mkdir(parents=True)
        profile_artifact.symlink_to(resource.store_path)
        target = Path(resource.target)
        target.parent.mkdir(parents=True)
        target.symlink_to(resource.link_target)

    def test_store_prefix_only_is_unchanged_and_noop(self) -> None:
        old_store = self.root / "old"
        new_store = self.root / "new"
        active = self._manifest(old_store)
        desired = self._manifest(new_store)
        self._install_active(active)

        plan = plan_domain(
            "codex",
            desired_store=new_store,
            desired=desired,
            active_store=old_store,
            active=active,
            safety=classify_manifests(desired, active),
        )

        self.assertEqual(plan.action, DomainAction.NOOP)
        self.assertEqual(plan.resources[0].delta, ResourceDelta.UNCHANGED)

    def test_provenance_only_switches_metadata(self) -> None:
        old_store = self.root / "old"
        new_store = self.root / "new"
        active = self._manifest(old_store, sources=("old",))
        desired = self._manifest(new_store, sources=("new",))
        self._install_active(active)

        plan = plan_domain(
            "codex",
            desired_store=new_store,
            desired=desired,
            active_store=old_store,
            active=active,
            safety=classify_manifests(desired, active),
        )

        self.assertEqual(plan.action, DomainAction.SWITCH_METADATA)
        self.assertEqual(plan.resources[0].delta, ResourceDelta.METADATA_UPDATE)

    def test_content_change_updates_only_changed_resource(self) -> None:
        old_store = self.root / "old"
        new_store = self.root / "new"
        active = self._manifest(old_store, content="old")
        desired = self._manifest(new_store, content="new")
        self._install_active(active)

        plan = plan_domain(
            "codex",
            desired_store=new_store,
            desired=desired,
            active_store=old_store,
            active=active,
            safety=classify_manifests(desired, active),
        )

        self.assertEqual(plan.action, DomainAction.SWITCH_CONTENT)
        self.assertEqual(plan.resources[0].delta, ResourceDelta.CONTENT_UPDATE)

    def test_missing_unchanged_entry_is_reconciled_without_switch(self) -> None:
        old_store = self.root / "old"
        new_store = self.root / "new"
        active = self._manifest(old_store)
        desired = self._manifest(new_store)

        plan = plan_domain(
            "codex",
            desired_store=new_store,
            desired=desired,
            active_store=old_store,
            active=active,
            safety=classify_manifests(desired, active),
        )

        self.assertEqual(plan.action, DomainAction.RECONCILE)
        self.assertEqual(plan.resources[0].delta, ResourceDelta.UNCHANGED)

    def test_system_store_identity_controls_generation_switch(self) -> None:
        store = self.root / "system"
        active = self._manifest(store, domain="system")
        desired = self._manifest(store, domain="system")
        self._install_active(active)

        same = plan_domain(
            "system",
            desired_store=store,
            desired=desired,
            active_store=store,
            active=active,
            safety=classify_manifests(desired, active),
        )
        changed = plan_domain(
            "system",
            desired_store=self.root / "other-system",
            desired=desired,
            active_store=store,
            active=active,
            safety=classify_manifests(desired, active),
        )

        self.assertEqual(same.action, DomainAction.NOOP)
        self.assertEqual(changed.action, DomainAction.SWITCH_CONTENT)

    def test_common_rule_change_updates_only_codex_and_claude_rules(self) -> None:
        domain_plans = []
        activation_plans = {}
        for domain in ("codex", "claude", "cursor"):
            old_store = self.root / f"old-{domain}"
            new_store = self.root / f"new-{domain}"
            resources_by_generation = []
            for store, rule_content in ((old_store, "old"), (new_store, "new")):
                resources = []
                if domain != "cursor":
                    rule = store / "rules"
                    rule.parent.mkdir(parents=True, exist_ok=True)
                    rule.write_text(rule_content)
                    resources.append(
                        Resource(
                            f"ai-agent.{domain}.global-rules",
                            f"ai-agent.{domain}",
                            "file-link",
                            str(self.identity.home / f".{domain}/rules"),
                            ("ai-agent/rules/common.md",),
                            link_target=str(self.identity.home / f"profiles/{domain}/rules"),
                            store_path=str(rule),
                            sha256=file_sha256(rule),
                        )
                    )
                for skill_name in ("brainstorming", "commit-code"):
                    skill = store / f"skills/{skill_name}"
                    skill.mkdir(parents=True)
                    (skill / "SKILL.md").write_text(skill_name)
                    resources.append(
                        Resource(
                            f"ai-agent.{domain}.skill.{skill_name}",
                            f"ai-agent.{domain}",
                            "directory-link",
                            str(self.identity.home / f".{domain}/skills/{skill_name}"),
                            (f"skills/{skill_name}",),
                            link_target=str(
                                self.identity.home / f"profiles/{domain}/skills/{skill_name}"
                            ),
                            store_path=str(skill),
                            directory_sha256=directory_sha256(skill),
                        )
                    )
                resources_by_generation.append(
                    DeploymentManifest(self.identity, domain, tuple(resources))
                )
            active, desired = resources_by_generation
            for resource in active.resources:
                link = Path(resource.link_target)
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(resource.store_path)
                target = Path(resource.target)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(resource.link_target)
            safety = classify_manifests(desired, active)
            domain_plans.append(
                plan_domain(
                    domain,
                    desired_store=new_store,
                    desired=desired,
                    active_store=old_store,
                    active=active,
                    safety=safety,
                )
            )
            activation_plans[domain] = (safety, None)

        deployment = build_deployment_plan(domain_plans)
        changes = build_plan_changes(deployment, activation_plans)

        self.assertEqual(
            [plan.action for plan in deployment.domains],
            [DomainAction.SWITCH_CONTENT, DomainAction.SWITCH_CONTENT, DomainAction.NOOP],
        )
        self.assertEqual(
            [entry.resource_id for entry in changes],
            ["ai-agent.codex.global-rules", "ai-agent.claude.global-rules"],
        )


if __name__ == "__main__":
    unittest.main()
