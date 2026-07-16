from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from dotfiles_cli.compiler import (
    SkillSource,
    compile_platform,
    validate_external_locks,
    validate_skill,
)
from dotfiles_cli.conflict import classify_manifests, classify_resource, resource_conforms
from dotfiles_cli.doctor import diagnose_manifest, diagnostics_healthy
from dotfiles_cli.errors import ValidationError
from dotfiles_cli.hashing import directory_entries, directory_sha256, file_sha256
from dotfiles_cli.jsonutil import canonical_json
from dotfiles_cli.machine import read_identity, write_identity
from dotfiles_cli.manifest import dump_manifest, read_manifest
from dotfiles_cli.models import (
    ActivationReceipt,
    ConflictStatus,
    DeploymentManifest,
    DiagnosticStatus,
    MachineIdentity,
    Resource,
)
from dotfiles_cli.state import read_receipt, validate_backup_ref, write_receipt


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.identity = MachineIdentity("alice", str(self.root / "home"))
        self.identity.home.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_canonical_json_is_stable_utf8_with_newline(self) -> None:
        self.assertEqual(
            canonical_json({"z": 1, "a": "中文"}), b'{"a":"\xe4\xb8\xad\xe6\x96\x87","z":1}\n'
        )

    def test_machine_state_round_trip_and_idempotence(self) -> None:
        path = self.root / "state" / "machine.json"
        self.assertTrue(write_identity(self.identity, path))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(read_identity(path), self.identity)
        self.assertFalse(write_identity(self.identity, path))

    def test_machine_state_rejects_symlink(self) -> None:
        state = self.root / "state"
        state.mkdir(mode=0o700)
        real = state / "real"
        real.write_text("{}")
        os.chmod(real, 0o600)
        link = state / "machine.json"
        link.symlink_to(real)
        with self.assertRaises(ValidationError):
            read_identity(link)

    def test_machine_state_rejects_group_readable_directory(self) -> None:
        state = self.root / "state"
        state.mkdir(mode=0o700)
        path = state / "machine.json"
        self.assertTrue(write_identity(self.identity, path))
        state.chmod(0o755)
        with self.assertRaisesRegex(ValidationError, "mode 0700"):
            read_identity(path)

    def test_directory_hash_includes_empty_directory_and_executable(self) -> None:
        skill = self.root / "skill"
        (skill / "empty").mkdir(parents=True)
        script = skill / "run.sh"
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
        entries = directory_entries(skill)
        self.assertIn({"path": "empty", "type": "directory"}, entries)
        self.assertTrue(next(item for item in entries if item["path"] == "run.sh")["executable"])
        self.assertEqual(directory_sha256(skill), directory_sha256(skill))

    def test_directory_hash_rejects_escaping_symlink(self) -> None:
        skill = self.root / "skill"
        skill.mkdir()
        (skill / "escape").symlink_to("../outside")
        with self.assertRaises(ValidationError):
            directory_sha256(skill)

    def test_skill_validation(self) -> None:
        skill = self.root / "demo"
        skill.mkdir()
        (skill / "SKILL.md").write_text("---\nname: demo\ndescription: Test skill\n---\n")
        validate_skill(SkillSource("local:demo", "demo", skill, "local", "ai-agent/skills/demo"))
        (skill / "SKILL.md").write_text("---\nname: wrong\ndescription: Test skill\n---\n")
        with self.assertRaises(ValidationError):
            validate_skill(
                SkillSource("local:demo", "demo", skill, "local", "ai-agent/skills/demo")
            )

    def test_external_lock_must_be_direct_and_have_nar_hash(self) -> None:
        lock = {
            "root": "root",
            "nodes": {
                "root": {"inputs": {"source": "source-node", "followed": ["other"]}},
                "source-node": {"locked": {"narHash": "sha256-test"}},
            },
        }
        (self.root / "flake.lock").write_text(json.dumps(lock))
        validate_external_locks(self.root, {"source"})
        with self.assertRaises(ValidationError):
            validate_external_locks(self.root, {"followed"})
        lock["nodes"]["source-node"]["locked"] = {}
        (self.root / "flake.lock").write_text(json.dumps(lock))
        with self.assertRaises(ValidationError):
            validate_external_locks(self.root, {"source"})

    def test_manifest_round_trip(self) -> None:
        store = self.root / "store-file"
        store.write_text("content")
        resource = Resource(
            "rules",
            "owner",
            "file-link",
            str(self.identity.home / ".tool/rules"),
            ("rules.md",),
            link_target=str(self.identity.home / ".state/profile/rules"),
            store_path=str(store),
            sha256=file_sha256(store),
        )
        manifest = DeploymentManifest(self.identity, "codex", (resource,))
        path = self.root / "manifest.json"
        dump_manifest(manifest, path)
        self.assertEqual(read_manifest(path), manifest)
        self.assertEqual(path.read_bytes(), canonical_json(manifest.to_dict()))

    def test_activation_receipt_round_trip_and_backup_path_validation(self) -> None:
        receipt = ActivationReceipt("codex", self.identity, "/nix/store/test", ())
        write_receipt(receipt)
        path = self.identity.home / ".local/state/dotfiles/platforms/codex/activation.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(read_receipt(self.identity, "codex"), receipt)
        self.assertEqual(
            validate_backup_ref(self.identity, "codex/resource/id"),
            self.identity.home / ".local/state/dotfiles/backups/codex/resource/id",
        )
        with self.assertRaises(ValidationError):
            validate_backup_ref(self.identity, "../escape")

    def test_conflict_classification(self) -> None:
        target = self.identity.home / "rules"
        store = self.root / "store"
        store.write_text("one")
        resource = Resource(
            "rules",
            "owner",
            "file-link",
            str(target),
            link_target=str(store),
            store_path=str(store),
            sha256=file_sha256(store),
        )
        self.assertEqual(classify_resource(resource, None).status, ConflictStatus.ABSENT)
        target.symlink_to(store)
        self.assertTrue(resource_conforms(resource))
        self.assertEqual(classify_resource(resource, None).status, ConflictStatus.CURRENTLY_MANAGED)
        target.unlink()
        target.write_text("user data")
        self.assertEqual(classify_resource(resource, None).status, ConflictStatus.CONFLICT)

    def test_empty_rules_file_is_adoptable_but_other_files_are_not(self) -> None:
        target = self.identity.home / "rules"
        store = self.root / "store"
        store.write_text("managed rules")
        resource = Resource(
            "rules",
            "owner",
            "file-link",
            str(target),
            ("rules.md",),
            link_target=str(store),
            store_path=str(store),
            sha256=file_sha256(store),
        )
        target.touch(mode=0o644)
        self.assertEqual(
            classify_resource(resource, None).status,
            ConflictStatus.ADOPTABLE_EMPTY,
        )
        target.write_text("user rules")
        self.assertEqual(classify_resource(resource, None).status, ConflictStatus.CONFLICT)
        target.write_text("")
        target.chmod(0o666)
        self.assertEqual(classify_resource(resource, None).status, ConflictStatus.CONFLICT)

    def test_safe_existing_ssh_config_is_migratable(self) -> None:
        ssh = self.identity.home / ".ssh"
        ssh.mkdir(mode=0o700)
        target = ssh / "config"
        target.write_text("Host example\n  User alice\n")
        target.chmod(0o600)
        store = self.root / "ssh-config"
        store.write_text("Include ~/.ssh/config.local\n")
        resource = Resource(
            "home.ssh.config",
            "home-manager",
            "file-link",
            str(target),
            link_target=str(store),
            store_path=str(store),
            sha256=file_sha256(store),
        )
        manifest = DeploymentManifest(self.identity, "system", (resource,))
        self.assertEqual(
            classify_manifests(manifest, None)[0].status,
            ConflictStatus.MIGRATABLE,
        )
        target.chmod(0o666)
        self.assertEqual(
            classify_manifests(manifest, None)[0].status,
            ConflictStatus.CONFLICT,
        )

    def test_home_manager_resource_accepts_equivalent_store_link(self) -> None:
        source = self.root / "hm-source"
        source.write_text("managed content")
        generation_link = self.root / "generation-link"
        generation_link.symlink_to(source)
        installed_link = self.root / "home-manager-files-link"
        installed_link.symlink_to(source)
        target = self.identity.home / "managed"
        target.symlink_to(installed_link)
        resource = Resource(
            "home.managed",
            "home-manager",
            "file-link",
            str(target),
            ("modules/home/test.nix",),
            link_target=str(generation_link),
            store_path=str(source),
            sha256=file_sha256(source),
        )

        self.assertTrue(resource_conforms(resource))

    def test_compiler_owns_individual_skills_not_the_skills_root(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        skill = self.root / "demo"
        skill.mkdir()
        (skill / "SKILL.md").write_text("---\nname: demo\ndescription: Demo skill\n---\n")
        output = self.root / "bundle"
        manifest = compile_platform(
            repository=repository,
            platform="codex",
            identity=self.identity,
            output_root=output,
            artifact_root=str(output),
            skills=[SkillSource("local:demo", "demo", skill, "local", "demo")],
        )
        skill_resource = next(
            resource for resource in manifest.resources if resource.id.endswith(".skill.demo")
        )
        self.assertEqual(skill_resource.target, str(self.identity.home / ".agents/skills/demo"))
        self.assertEqual(
            skill_resource.link_target,
            str(self.identity.home / ".local/state/dotfiles/platforms/codex/profile/skills/demo"),
        )
        self.assertNotIn(
            str(self.identity.home / ".agents/skills"),
            {resource.target for resource in manifest.resources},
        )

    def test_doctor_checks_local_prerequisite_without_reading_content(self) -> None:
        local = self.identity.home / "local.inc"
        prerequisite = Resource(
            "local",
            "user",
            "local-prerequisite",
            str(local),
            managed=False,
            optional=True,
        )
        manifest = DeploymentManifest(self.identity, "system", (prerequisite,))
        result = diagnose_manifest(self.identity, manifest)
        self.assertEqual(result[0].status, DiagnosticStatus.LOCAL_ABSENT_OPTIONAL)
        self.assertTrue(diagnostics_healthy(result))
        local.write_text("secret")
        local.chmod(0o666)
        result = diagnose_manifest(self.identity, manifest)
        self.assertEqual(result[0].status, DiagnosticStatus.LOCAL_UNSAFE_PERMISSIONS)
        self.assertNotIn("secret", result[0].reason)


class CompilerGoldenTests(unittest.TestCase):
    def _snapshot(self, root: Path) -> list[dict]:
        entries = []
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            relative = path.relative_to(root).as_posix()
            if path.is_dir():
                entries.append({"path": relative, "type": "directory"})
            else:
                entries.append({"path": relative, "sha256": file_sha256(path), "type": "file"})
        return entries

    def test_platform_output_contracts(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = MachineIdentity("testuser", "/Users/testuser")
            for platform, rules_name in (
                ("codex", "AGENTS.md"),
                ("claude", "CLAUDE.md"),
                ("cursor", None),
            ):
                output = root / platform
                manifest = compile_platform(
                    repository=repository,
                    platform=platform,
                    identity=identity,
                    output_root=output,
                    artifact_root=f"/nix/store/test-{platform}",
                    skills=[],
                )
                self.assertEqual((output / "skills").is_dir(), True)
                self.assertEqual((output / "share/dotfiles/manifest.json").is_file(), True)
                self.assertEqual(
                    (output / rules_name).is_file() if rules_name else False, bool(rules_name)
                )
                self.assertEqual(manifest.deployment_domain, platform)
                expected = json.loads(
                    (repository / "tests/golden" / f"{platform}.json").read_text()
                )
                self.assertEqual(self._snapshot(output), expected)


if __name__ == "__main__":
    unittest.main()
