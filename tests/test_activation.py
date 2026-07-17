from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from dotfiles_cli.activation import (
    activate_platform,
    activate_system_store,
    current_platform,
    effective_active_manifest,
    make_resource_actions,
    preflight_platform,
    profile_path,
    reconcile_platform,
    select_previous_system_generation,
)
from dotfiles_cli.compiler import SkillSource, compile_platform
from dotfiles_cli.doctor import diagnose_manifest, diagnostics_healthy
from dotfiles_cli.errors import ActivationError
from dotfiles_cli.hashing import file_sha256
from dotfiles_cli.manifest import dump_manifest
from dotfiles_cli.models import (
    ActivationPlan,
    ConflictStatus,
    DeploymentManifest,
    DeploymentState,
    DiagnosticStatus,
    MachineIdentity,
    Resource,
    ResourceDecision,
)
from dotfiles_cli.nix import CommandResult
from dotfiles_cli.state import backup_is_valid, read_receipt


class ProfileRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, command, *, check=True):
        self.commands.append(list(command))
        if command[0] == "nix-env" and "--set" in command:
            profile = Path(command[command.index("--profile") + 1])
            store = Path(command[command.index("--set") + 1])
            profile.parent.mkdir(parents=True, exist_ok=True)
            temporary = profile.with_name(profile.name + ".tmp")
            temporary.unlink(missing_ok=True)
            temporary.symlink_to(store)
            os.replace(temporary, profile)
        return CommandResult(0, "", "")


class SystemRunner:
    def __init__(
        self, current_link: Path, fail_target: Path | None = None, fail_after_switch: bool = False
    ):
        self.current_link = current_link
        self.fail_target = fail_target
        self.fail_after_switch = fail_after_switch
        self.generations = {1}
        self.pending: Path | None = None
        self.deleted: list[int] = []
        self.commands: list[list[str]] = []

    def run(self, command, *, check=True):
        self.commands.append(list(command))
        if "--list-generations" in command:
            output = "".join(
                f"{number} 2026-01-01 00:00:00\n" for number in sorted(self.generations)
            )
            return CommandResult(0, output, "")
        if "--set" in command:
            self.pending = Path(command[command.index("--set") + 1])
            self.generations.add(max(self.generations) + 1)
            return CommandResult(0, "", "")
        if "--delete-generations" in command:
            number = int(command[-1])
            self.generations.discard(number)
            self.deleted.append(number)
            return CommandResult(0, "", "")
        if command[0] == "sudo" and command[1].endswith("/activate"):
            target = Path(command[1]).parent
            if target == self.fail_target and not self.fail_after_switch:
                raise ActivationError("injected failure before current-system switch")
            temporary = self.current_link.with_name("current-system.tmp")
            temporary.unlink(missing_ok=True)
            temporary.symlink_to(target)
            os.replace(temporary, self.current_link)
            if target == self.fail_target and self.fail_after_switch:
                raise ActivationError("injected failure after current-system switch")
        return CommandResult(0, "", "")


class SshSystemRunner(SystemRunner):
    def __init__(self, current_link: Path, system: Path, config: Path, generated: Path):
        super().__init__(current_link)
        self.system = system
        self.config = config
        self.generated = generated

    def run(self, command, *, check=True):
        result = super().run(command, check=check)
        if (
            command[0] == "sudo"
            and command[1] == str(self.system / "activate")
            and not self.config.exists()
            and not self.config.is_symlink()
        ):
            self.config.symlink_to(self.generated)
        return result


class FailingProfileSetRunner(SystemRunner):
    def run(self, command, *, check=True):
        if command[:2] == ["sudo", "nix-env"] and "--set" in command:
            raise ActivationError("injected profile set failure")
        return super().run(command, check=check)


class NoNewGenerationRunner(SystemRunner):
    def run(self, command, *, check=True):
        if "--set" in command:
            self.commands.append(list(command))
            self.pending = Path(command[command.index("--set") + 1])
            return CommandResult(0, "", "")
        return super().run(command, check=check)


class ActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.other_manifests = patch(
            "dotfiles_cli.activation.other_active_manifests", return_value=[]
        )
        self.other_manifests.start()

    def tearDown(self) -> None:
        self.other_manifests.stop()

    def _system_store(self, root: Path, name: str, identity: MachineIdentity) -> Path:
        store = root / name
        (store / "sw/share/dotfiles").mkdir(parents=True)
        (store / "activate").write_text("test")
        dump_manifest(
            DeploymentManifest(identity, "system", ()),
            store / "sw/share/dotfiles/system-manifest.json",
        )
        return store

    def _add_ssh_resource(
        self, store: Path, identity: MachineIdentity
    ) -> tuple[Path, Resource]:
        generated = store / "ssh-config"
        generated.write_text("Include ~/.ssh/config.local\n")
        resource = Resource(
            "home.ssh.config",
            "home-manager",
            "file-link",
            str(identity.home / ".ssh/config"),
            ("modules/home/ssh.nix",),
            link_target=str(generated),
            store_path=str(generated),
            sha256=file_sha256(generated),
        )
        dump_manifest(
            DeploymentManifest(identity, "system", (resource,)),
            store / "sw/share/dotfiles/system-manifest.json",
        )
        return generated, resource

    def test_initial_platform_activation_and_update_keep_stable_entry(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = MachineIdentity("alice", str(root / "home"))
            identity.home.mkdir()
            bundle = root / "bundle-one"
            manifest = compile_platform(
                repository=repository,
                platform="codex",
                identity=identity,
                output_root=bundle,
                artifact_root=str(bundle),
                skills=[],
            )
            profile = profile_path(identity, "codex")
            plan = ActivationPlan("codex", identity, str(profile), str(bundle), manifest)
            result = activate_platform(ProfileRunner(), plan)
            self.assertEqual(result.status, "UPDATED")
            rules_target = identity.home / ".codex/AGENTS.md"
            raw_target = os.readlink(rules_target)
            self.assertEqual(raw_target, str(profile / "AGENTS.md"))

            bundle_two = root / "bundle-two"
            manifest_two = compile_platform(
                repository=repository,
                platform="codex",
                identity=identity,
                output_root=bundle_two,
                artifact_root=str(bundle_two),
                skills=[],
            )
            update = ActivationPlan(
                "codex",
                identity,
                str(profile),
                str(bundle_two),
                manifest_two,
                str(bundle),
                manifest,
            )
            activate_platform(ProfileRunner(), update)
            self.assertEqual(os.readlink(rules_target), raw_target)
            self.assertEqual(profile.resolve(), bundle_two.resolve())

    def test_platform_reconcile_repairs_entry_without_switching_profile(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = MachineIdentity("alice", str(root / "home"))
            identity.home.mkdir()
            bundle = root / "bundle"
            manifest = compile_platform(
                repository=repository,
                platform="codex",
                identity=identity,
                output_root=bundle,
                artifact_root=str(bundle),
                skills=[],
            )
            profile = profile_path(identity, "codex")
            activate_platform(
                ProfileRunner(),
                ActivationPlan("codex", identity, str(profile), str(bundle), manifest),
            )
            rules = identity.home / ".codex/AGENTS.md"
            rules.unlink()
            runner = ProfileRunner()
            plan = ActivationPlan(
                "codex",
                identity,
                str(profile),
                str(root / "unused-new-bundle"),
                manifest,
                str(bundle),
                manifest,
                old_receipt=read_receipt(identity, "codex"),
            )

            result = reconcile_platform(runner, plan)

            self.assertEqual(result.status, "UPDATED")
            self.assertTrue(rules.is_symlink())
            self.assertEqual(runner.commands, [])

    def test_platform_adopts_empty_rules_file_and_preserves_skills_root(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = MachineIdentity("alice", str(root / "home"))
            skills_root = identity.home / ".agents/skills"
            skills_root.mkdir(parents=True)
            manual_skill = skills_root / "manual"
            manual_skill.mkdir()
            rules = identity.home / ".codex/AGENTS.md"
            rules.parent.mkdir()
            rules.touch(mode=0o644)
            bundle = root / "bundle"
            manifest = compile_platform(
                repository=repository,
                platform="codex",
                identity=identity,
                output_root=bundle,
                artifact_root=str(bundle),
                skills=[],
            )
            plan = ActivationPlan(
                "codex", identity, str(profile_path(identity, "codex")), str(bundle), manifest
            )
            activate_platform(ProfileRunner(), plan)
            self.assertTrue(rules.is_symlink())
            self.assertTrue(skills_root.is_dir())
            self.assertFalse(skills_root.is_symlink())
            self.assertTrue(manual_skill.is_dir())

    def test_failed_initial_activation_restores_adopted_empty_file(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = MachineIdentity("alice", str(root / "home"))
            rules = identity.home / ".codex/AGENTS.md"
            rules.parent.mkdir(parents=True)
            rules.touch(mode=0o640)
            bundle = root / "bundle"
            manifest = compile_platform(
                repository=repository,
                platform="codex",
                identity=identity,
                output_root=bundle,
                artifact_root=str(bundle),
                skills=[],
            )
            rules_resource = manifest.resources[0]
            broken = replace(
                manifest,
                resources=(replace(rules_resource, sha256="0" * 64),),
            )
            plan = ActivationPlan(
                "codex", identity, str(profile_path(identity, "codex")), str(bundle), broken
            )
            with self.assertRaises(ActivationError):
                activate_platform(ProfileRunner(), plan)
            self.assertTrue(rules.is_file())
            self.assertFalse(rules.is_symlink())
            self.assertEqual(rules.stat().st_size, 0)
            self.assertEqual(rules.stat().st_mode & 0o777, 0o640)

    def test_skip_conflicting_skill_still_deploys_rules_and_can_repeat(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        source = repository / "ai-agent/skills/commit-skill"
        skill = SkillSource(
            "local:commit-skill",
            "commit-skill",
            source,
            "local",
            "ai-agent/skills/commit-skill",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = MachineIdentity("alice", str(root / "home"))
            conflict = identity.home / ".agents/skills/commit-skill"
            conflict.mkdir(parents=True)
            marker = conflict / "manual"
            marker.write_text("keep")
            rules = identity.home / ".codex/AGENTS.md"
            rules.parent.mkdir()
            rules.touch()
            profile = profile_path(identity, "codex")

            first = root / "bundle-one"
            manifest = compile_platform(
                repository=repository,
                platform="codex",
                identity=identity,
                output_root=first,
                artifact_root=str(first),
                skills=[skill],
            )
            results = preflight_platform(manifest, None, resource_level=True)
            self.assertIn(
                ConflictStatus.OVERWRITABLE_CONFLICT,
                {result.status for result in results},
            )
            actions = make_resource_actions(results, manifest, None)
            self.assertIn(ResourceDecision.SKIP, {action.decision for action in actions})
            outcome = activate_platform(
                ProfileRunner(),
                ActivationPlan(
                    "codex",
                    identity,
                    str(profile),
                    str(first),
                    manifest,
                    actions=actions,
                ),
            )
            self.assertEqual(outcome.status, "PARTIAL_UPDATED")
            self.assertTrue(rules.is_symlink())
            self.assertEqual(marker.read_text(), "keep")
            receipt = read_receipt(identity, "codex")
            self.assertIsNotNone(receipt)
            state, old_store, active = current_platform(identity, "codex")
            self.assertEqual(state, DeploymentState.PARTIALLY_DEPLOYED)
            diagnostics = diagnose_manifest(identity, manifest, receipt)
            self.assertIn(
                DiagnosticStatus.SKIPPED_CONFLICT,
                {item.status for item in diagnostics},
            )
            self.assertFalse(diagnostics_healthy(diagnostics))

            second = root / "bundle-two"
            desired = compile_platform(
                repository=repository,
                platform="codex",
                identity=identity,
                output_root=second,
                artifact_root=str(second),
                skills=[skill],
            )
            effective = effective_active_manifest(active, receipt)
            next_results = preflight_platform(desired, effective, resource_level=True)
            self.assertIn(
                ConflictStatus.OVERWRITABLE_CONFLICT,
                {result.status for result in next_results},
            )
            next_actions = make_resource_actions(next_results, desired, receipt)
            activate_platform(
                ProfileRunner(),
                ActivationPlan(
                    "codex",
                    identity,
                    str(profile),
                    str(second),
                    desired,
                    str(old_store),
                    effective,
                    next_actions,
                    receipt,
                ),
            )
            self.assertEqual(marker.read_text(), "keep")
            self.assertEqual(profile.resolve(), second.resolve())

    def test_overwrite_conflicting_skill_creates_backup(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        source = repository / "ai-agent/skills/commit-skill"
        skill = SkillSource(
            "local:commit-skill",
            "commit-skill",
            source,
            "local",
            "ai-agent/skills/commit-skill",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = MachineIdentity("alice", str(root / "home"))
            target = identity.home / ".agents/skills/commit-skill"
            target.mkdir(parents=True)
            (target / "manual").write_text("preserved")
            bundle = root / "bundle"
            manifest = compile_platform(
                repository=repository,
                platform="codex",
                identity=identity,
                output_root=bundle,
                artifact_root=str(bundle),
                skills=[skill],
            )
            results = preflight_platform(manifest, None, resource_level=True)
            skill_result = next(
                result for result in results if result.resource.id.endswith("commit-skill")
            )
            actions = make_resource_actions(results, manifest, None, {skill_result.resource.id})
            activate_platform(
                ProfileRunner(),
                ActivationPlan(
                    "codex",
                    identity,
                    str(profile_path(identity, "codex")),
                    str(bundle),
                    manifest,
                    actions=actions,
                ),
            )
            self.assertTrue(target.is_symlink())
            receipt = read_receipt(identity, "codex")
            entry = next(item for item in receipt.resources if item.id == skill_result.resource.id)
            self.assertIsNotNone(entry.backup_ref)
            backup = identity.home / ".local/state/dotfiles/backups" / entry.backup_ref
            self.assertEqual((backup / "payload/manual").read_text(), "preserved")
            self.assertTrue(
                backup_is_valid(
                    identity,
                    "codex",
                    skill_result.resource.id,
                    skill_result.resource.target,
                    entry.backup_ref,
                )
            )

            without_skill = root / "bundle-without-skill"
            desired = compile_platform(
                repository=repository,
                platform="codex",
                identity=identity,
                output_root=without_skill,
                artifact_root=str(without_skill),
                skills=[],
            )
            old_store = profile_path(identity, "codex").resolve()
            results = preflight_platform(desired, manifest, resource_level=True)
            actions = make_resource_actions(results, desired, receipt)
            self.assertIn(
                ResourceDecision.RESTORE_BACKUP,
                {action.decision for action in actions},
            )
            activate_platform(
                ProfileRunner(),
                ActivationPlan(
                    "codex",
                    identity,
                    str(profile_path(identity, "codex")),
                    str(without_skill),
                    desired,
                    str(old_store),
                    manifest,
                    actions,
                    receipt,
                ),
            )
            self.assertFalse(target.is_symlink())
            self.assertEqual((target / "manual").read_text(), "preserved")

    def test_failed_overwrite_restores_user_skill_and_old_state(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        source = repository / "ai-agent/skills/commit-skill"
        skill = SkillSource(
            "local:commit-skill",
            "commit-skill",
            source,
            "local",
            "ai-agent/skills/commit-skill",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = MachineIdentity("alice", str(root / "home"))
            target = identity.home / ".agents/skills/commit-skill"
            target.mkdir(parents=True)
            marker = target / "manual"
            marker.write_text("restore-me")
            bundle = root / "bundle"
            manifest = compile_platform(
                repository=repository,
                platform="codex",
                identity=identity,
                output_root=bundle,
                artifact_root=str(bundle),
                skills=[skill],
            )
            broken_rules = replace(manifest.resources[0], sha256="0" * 64)
            broken = replace(
                manifest,
                resources=(broken_rules, *manifest.resources[1:]),
            )
            results = preflight_platform(broken, None, resource_level=True)
            skill_result = next(
                result for result in results if result.resource.id.endswith("commit-skill")
            )
            actions = make_resource_actions(results, broken, None, {skill_result.resource.id})
            with self.assertRaises(ActivationError) as caught:
                activate_platform(
                    ProfileRunner(),
                    ActivationPlan(
                        "codex",
                        identity,
                        str(profile_path(identity, "codex")),
                        str(bundle),
                        broken,
                        actions=actions,
                    ),
                )
            self.assertIn("ROLLED_BACK", str(caught.exception))
            self.assertFalse(target.is_symlink())
            self.assertEqual(marker.read_text(), "restore-me")
            self.assertIsNone(read_receipt(identity, "codex"))

    def test_previous_generation_skips_duplicate_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = root / "store-current"
            old = root / "store-old"
            current.mkdir()
            old.mkdir()
            (root / "system-1-link").symlink_to(old)
            (root / "system-2-link").symlink_to(current)
            (root / "system-3-link").symlink_to(current)
            self.assertEqual(
                select_previous_system_generation(current, profile_directory=root),
                (1, old.resolve()),
            )

    def test_system_activation_failure_restores_old_store_and_deletes_failed_generation(
        self,
    ) -> None:
        for fail_after_switch in (False, True):
            with (
                self.subTest(fail_after_switch=fail_after_switch),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                identity = MachineIdentity("alice", str(root / "home"))
                old = self._system_store(root, "old-system", identity)
                target = self._system_store(root, "new-system", identity)
                current = root / "current-system"
                current.symlink_to(old)
                runner = SystemRunner(
                    current, fail_target=target, fail_after_switch=fail_after_switch
                )
                with self.assertRaises(ActivationError) as caught:
                    activate_system_store(
                        runner,
                        target,
                        identity,
                        current_link=current,
                        profile=root / "system-profile",
                    )
                self.assertIn("ROLLED_BACK", str(caught.exception))
                self.assertEqual(current.resolve(), old.resolve())
                self.assertEqual(runner.deleted, [2])

    def test_system_activation_migrates_and_appends_existing_ssh_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = MachineIdentity("alice", str(root / "home"))
            ssh = identity.home / ".ssh"
            ssh.mkdir(parents=True, mode=0o700)
            config = ssh / "config"
            config.write_text("Host work\n  User alice\n")
            config.chmod(0o600)
            local = ssh / "config.local"
            local.write_text("Host local\n  User local\n")
            local.chmod(0o600)
            old = self._system_store(root, "old-system", identity)
            target = self._system_store(root, "new-system", identity)
            generated, _ = self._add_ssh_resource(target, identity)
            current = root / "current-system"
            current.symlink_to(old)
            runner = SshSystemRunner(current, target, config, generated)

            result = activate_system_store(
                runner,
                target,
                identity,
                current_link=current,
                profile=root / "system-profile",
            )

            self.assertEqual(result.status, "UPDATED")
            self.assertEqual(config.resolve(), generated.resolve())
            self.assertEqual(
                local.read_text(),
                "Host local\n  User local\n"
                "\n# Migrated from ~/.ssh/config by dot apply\n"
                "Host work\n  User alice\n",
            )
            activate_system_store(
                runner,
                target,
                identity,
                current_link=current,
                profile=root / "system-profile",
            )
            self.assertEqual(local.read_text().count("# Migrated from"), 1)

    def test_failed_system_activation_restores_ssh_migration(self) -> None:
        for existing_local in (False, True):
            with (
                self.subTest(existing_local=existing_local),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                identity = MachineIdentity("alice", str(root / "home"))
                ssh = identity.home / ".ssh"
                ssh.mkdir(parents=True, mode=0o700)
                config = ssh / "config"
                config.write_text("Host work\n  User alice\n")
                config.chmod(0o600)
                local = ssh / "config.local"
                if existing_local:
                    local.write_text("Host local\n  User local\n")
                    local.chmod(0o600)
                old = self._system_store(root, "old-system", identity)
                target = self._system_store(root, "new-system", identity)
                self._add_ssh_resource(target, identity)
                current = root / "current-system"
                current.symlink_to(old)
                runner = SystemRunner(current, fail_target=target)

                with self.assertRaises(ActivationError):
                    activate_system_store(
                        runner,
                        target,
                        identity,
                        current_link=current,
                        profile=root / "system-profile",
                    )

                self.assertEqual(config.read_text(), "Host work\n  User alice\n")
                if existing_local:
                    self.assertEqual(local.read_text(), "Host local\n  User local\n")
                else:
                    self.assertFalse(local.exists())
                self.assertEqual(list(ssh.glob(".config.dotfiles-migration-*")), [])

    def test_failed_initial_profile_set_reports_ssh_migration_rolled_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = MachineIdentity("alice", str(root / "home"))
            ssh = identity.home / ".ssh"
            ssh.mkdir(parents=True, mode=0o700)
            config = ssh / "config"
            config.write_text("Host work\n  User alice\n")
            config.chmod(0o600)
            target = self._system_store(root, "new-system", identity)
            self._add_ssh_resource(target, identity)
            current = root / "current-system"
            runner = FailingProfileSetRunner(current)

            with self.assertRaises(ActivationError) as caught:
                activate_system_store(
                    runner,
                    target,
                    identity,
                    current_link=current,
                    profile=root / "system-profile",
                )

            self.assertIn("ROLLED_BACK", str(caught.exception))
            self.assertNotIn("RECOVERY_REQUIRED", str(caught.exception))
            self.assertFalse(caught.exception.modified_state)
            self.assertEqual(config.read_text(), "Host work\n  User alice\n")
            self.assertFalse((ssh / "config.local").exists())

    def test_failed_initial_activation_keeps_current_profile_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = MachineIdentity("alice", str(root / "home"))
            identity.home.mkdir()
            target = self._system_store(root, "new-system", identity)
            current = root / "current-system"
            runner = SystemRunner(current, fail_target=target)

            with self.assertRaises(ActivationError) as caught:
                activate_system_store(
                    runner,
                    target,
                    identity,
                    current_link=current,
                    profile=root / "system-profile",
                )

            self.assertIn("RECOVERY_REQUIRED", str(caught.exception))
            self.assertEqual(runner.deleted, [])

    def test_system_activation_accepts_unchanged_profile_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = MachineIdentity("alice", str(root / "home"))
            identity.home.mkdir()
            target = self._system_store(root, "system", identity)
            current = root / "current-system"
            runner = NoNewGenerationRunner(current)

            result = activate_system_store(
                runner,
                target,
                identity,
                current_link=current,
                profile=root / "system-profile",
            )

            self.assertEqual(result.status, "UPDATED")
            self.assertEqual(current.resolve(), target.resolve())
            self.assertEqual(runner.generations, {1})

    def test_initial_system_activation_without_old_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = MachineIdentity("alice", str(root / "home"))
            target = self._system_store(root, "new-system", identity)
            current = root / "current-system"
            runner = SystemRunner(current)
            result = activate_system_store(
                runner,
                target,
                identity,
                current_link=current,
                profile=root / "system-profile",
            )
            self.assertEqual(result.status, "UPDATED")
            self.assertEqual(current.resolve(), target.resolve())
            generation_queries = [
                command for command in runner.commands if "--list-generations" in command
            ]
            self.assertEqual(len(generation_queries), 2)
            self.assertTrue(
                all(command[:2] == ["sudo", "nix-env"] for command in generation_queries)
            )


if __name__ == "__main__":
    unittest.main()
