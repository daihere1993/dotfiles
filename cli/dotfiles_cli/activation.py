from __future__ import annotations

import os
import re
import shutil
import stat
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .adapters import get_adapter
from .conflict import classify_manifests, resource_conforms
from .doctor import diagnose_manifest, diagnostics_healthy
from .errors import ActivationError, ConflictError, DotfilesError, ValidationError
from .hashing import directory_sha256, file_sha256
from .jsonutil import canonical_json, load_json
from .manifest import assert_identity, read_manifest
from .models import (
    PLATFORMS,
    ActivationPlan,
    ActivationReceipt,
    ConflictStatus,
    DeploymentManifest,
    DeploymentState,
    DomainResult,
    MachineIdentity,
    ReceiptResource,
    ReceiptResourceState,
    ResourceAction,
    ResourceDecision,
)
from .apply_events import ActivationMilestone
from .nix import CommandRunner
from .state import (
    atomic_write,
    backup_root,
    read_receipt,
    receipt_path,
    validate_backup_ref,
    write_receipt,
)


def profile_path(identity: MachineIdentity, platform: str) -> Path:
    return identity.home / ".local/state/dotfiles/platforms" / platform / "profile"


def platform_manifest_path(profile: Path) -> Path:
    return profile / "share/dotfiles/manifest.json"


def other_active_manifests(identity: MachineIdentity, excluded: str) -> list[DeploymentManifest]:
    manifests: list[DeploymentManifest] = []
    if excluded != "system":
        current_link = Path("/run/current-system")
        if not current_link.exists() and not current_link.is_symlink():
            current = None
        else:
            current = current_system_store()
        try:
            path = system_manifest_path(current) if current is not None else None
            if path is not None and path.is_file():
                manifest = read_manifest(path)
                assert_identity(identity, manifest)
                manifests.append(manifest)
        except DotfilesError:
            raise
        except OSError:
            pass
    for platform in PLATFORMS:
        if platform == excluded:
            continue
        _, _, manifest = current_platform(identity, platform)
        if manifest is not None:
            receipt = read_receipt(identity, platform)
            allowed = (
                {
                    item.id
                    for item in receipt.resources
                    if item.state == ReceiptResourceState.DEPLOYED
                }
                if receipt
                else {resource.id for resource in manifest.resources}
            )
            owned = tuple(
                resource
                for resource in manifest.resources
                if resource.id in allowed and resource_conforms(resource)
            )
            if owned:
                manifests.append(
                    DeploymentManifest(
                        manifest.identity,
                        manifest.deployment_domain,
                        owned,
                        manifest.skills,
                    )
                )
    return manifests


def effective_active_manifest(
    manifest: DeploymentManifest | None, receipt: ActivationReceipt | None
) -> DeploymentManifest | None:
    if manifest is None or receipt is None:
        return manifest
    deployed_ids = {
        item.id for item in receipt.resources if item.state == ReceiptResourceState.DEPLOYED
    }
    return DeploymentManifest(
        manifest.identity,
        manifest.deployment_domain,
        tuple(resource for resource in manifest.resources if resource.id in deployed_ids),
        manifest.skills,
    )


def current_platform(
    identity: MachineIdentity, platform: str
) -> tuple[DeploymentState, Path | None, DeploymentManifest | None]:
    profile = profile_path(identity, platform)
    if not profile.exists() and not profile.is_symlink():
        return DeploymentState.NOT_DEPLOYED, None, None
    try:
        store = profile.resolve(strict=True)
        manifest = read_manifest(platform_manifest_path(profile))
        assert_identity(identity, manifest)
    except (OSError, RuntimeError) as error:
        raise ValidationError(
            f"cannot resolve active {platform} profile: {profile}: {error}"
        ) from error
    managed = [resource for resource in manifest.resources if resource.managed]
    receipt = read_receipt(identity, platform)
    if receipt is not None and Path(receipt.bundle_store_path).resolve(strict=True) != store:
        raise ValidationError(f"activation receipt does not match {platform} profile")
    receipt_by_id = {item.id: item for item in receipt.resources} if receipt else {}
    deployed = [
        resource
        for resource in managed
        if (
            receipt is None
            or receipt_by_id.get(resource.id) is not None
            and receipt_by_id[resource.id].state == ReceiptResourceState.DEPLOYED
        )
        and resource_conforms(resource)
    ]
    if not deployed:
        state = DeploymentState.STAGED_NOT_DEPLOYED
    elif len(deployed) == len(managed) and (
        receipt is None
        or all(
            receipt_by_id.get(resource.id) is not None
            and receipt_by_id[resource.id].state == ReceiptResourceState.DEPLOYED
            for resource in managed
        )
    ):
        state = DeploymentState.DEPLOYED
    else:
        state = DeploymentState.PARTIALLY_DEPLOYED
    return state, store, manifest


def preflight_platform(
    desired: DeploymentManifest,
    active: DeploymentManifest | None,
    other_active: list[DeploymentManifest] | None = None,
    *,
    resource_level: bool = False,
) -> list:
    from .conflict import ownership_overlaps

    skills_root = None
    if resource_level:
        adapter = get_adapter(desired.deployment_domain)
        skills_root = desired.identity.home / adapter.skills_target
    results = classify_manifests(desired, active, overwritable_skills_root=skills_root)
    conflicts = [item for item in results if item.status == ConflictStatus.CONFLICT]
    overlaps = ownership_overlaps([desired, *(other_active or [])])
    if overlaps or (conflicts and not resource_level):
        details = [f"{item.resource.target}: {item.reason}" for item in conflicts] + overlaps
        raise ConflictError(
            "platform preflight found conflicts:\n" + "\n".join(details),
            next_step=(
                "Back up or migrate the conflicting paths manually, then run "
                "dot apply --check again."
            ),
        )
    return results


def make_resource_actions(
    results: list,
    desired: DeploymentManifest,
    old_receipt: ActivationReceipt | None,
    overwrite_ids: set[str] | None = None,
) -> tuple[ResourceAction, ...]:
    overwrite_ids = overwrite_ids or set()
    desired_ids = {resource.id for resource in desired.resources}
    old_by_id = {item.id: item for item in old_receipt.resources} if old_receipt else {}
    actions: list[ResourceAction] = []
    for result in results:
        old = old_by_id.get(result.resource.id)
        backup_ref = old.backup_ref if old else None
        if result.status == ConflictStatus.OVERWRITABLE_CONFLICT:
            decision = (
                ResourceDecision.OVERWRITE
                if result.resource.id in overwrite_ids
                else ResourceDecision.SKIP
            )
        elif result.status == ConflictStatus.CONFLICT:
            decision = ResourceDecision.SKIP
        elif result.resource.id not in desired_ids:
            decision = (
                ResourceDecision.RESTORE_BACKUP
                if backup_ref is not None
                else ResourceDecision.RETIRE
            )
        else:
            decision = ResourceDecision.APPLY
        actions.append(
            ResourceAction(
                result.resource,
                decision,
                result.status,
                result.reason,
                backup_ref,
            )
        )
    return tuple(actions)


def _safe_parent(target: Path, identity: MachineIdentity) -> None:
    try:
        target.relative_to(identity.home)
    except ValueError as error:
        raise ActivationError(f"refusing to create target outside home: {target}") from error
    parent = target.parent
    missing: list[Path] = []
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ActivationError(f"target parent is not a real directory: {parent}")
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)


def _set_profile(runner: CommandRunner, profile: Path, store: Path) -> None:
    profile.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    runner.run(["nix-env", "--profile", str(profile), "--set", str(store)])
    try:
        actual = profile.resolve(strict=True)
    except OSError as error:
        raise ActivationError(
            f"profile switch did not create a valid profile: {profile}"
        ) from error
    if actual != store.resolve(strict=True):
        raise ActivationError(f"profile resolved to {actual}, expected {store}")


def _target_token(path: Path) -> tuple:
    if not path.exists() and not path.is_symlink():
        return ("absent",)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return ("symlink", info.st_ino, info.st_mtime_ns, os.readlink(path))
    return ("entry", info.st_ino, info.st_mtime_ns, info.st_size, stat.S_IMODE(info.st_mode))


def _backup_metadata(plan: ActivationPlan, action: ResourceAction) -> tuple[dict, str]:
    target = Path(action.resource.target)
    info = target.lstat()
    if stat.S_ISLNK(info.st_mode):
        kind = "symlink"
        digest = os.readlink(target)
    elif stat.S_ISDIR(info.st_mode):
        kind = "directory"
        digest = directory_sha256(target)
    elif stat.S_ISREG(info.st_mode):
        kind = "file"
        digest = file_sha256(target)
    else:
        raise ActivationError(f"refusing to back up special file: {target}")
    reference = f"{plan.platform}/{action.resource.id}/{uuid.uuid4()}"
    return (
        {
            "schemaVersion": 1,
            "platform": plan.platform,
            "username": plan.identity.username,
            "homeDirectory": plan.identity.home_directory,
            "nixSystem": plan.identity.nix_system,
            "resourceId": action.resource.id,
            "target": action.resource.target,
            "kind": kind,
            "mode": stat.S_IMODE(info.st_mode),
            "ownerUid": info.st_uid,
            "digest": digest,
        },
        reference,
    )


def _create_backup(plan: ActivationPlan, action: ResourceAction) -> str:
    metadata, reference = _backup_metadata(plan, action)
    directory = validate_backup_ref(plan.identity, reference)
    directory.mkdir(mode=0o700, parents=True)
    root = backup_root(plan.identity)
    for candidate in (root, *directory.relative_to(root).parents[::-1], directory):
        path = (
            candidate
            if isinstance(candidate, Path) and candidate.is_absolute()
            else root / candidate
        )
        if not path.exists():
            continue
        info = path.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.getuid()
        ):
            raise ActivationError(f"unsafe backup directory: {path}")
        os.chmod(path, 0o700)
    atomic_write(directory / "metadata.json", canonical_json(metadata))
    os.replace(action.resource.target, directory / "payload")
    return reference


def _validated_backup(
    identity: MachineIdentity, platform: str, resource_id: str, target: str, reference: str
) -> tuple[Path, dict]:
    directory = validate_backup_ref(identity, reference)
    metadata_path = directory / "metadata.json"
    payload = directory / "payload"
    if (
        not metadata_path.is_file()
        or metadata_path.is_symlink()
        or (not payload.exists() and not payload.is_symlink())
    ):
        raise ActivationError(f"backup is missing for {resource_id}: {reference}")
    metadata = load_json(metadata_path)
    expected = (platform, identity.username, identity.home_directory, resource_id, target)
    actual = (
        metadata.get("platform"),
        metadata.get("username"),
        metadata.get("homeDirectory"),
        metadata.get("resourceId"),
        metadata.get("target"),
    )
    if metadata.get("schemaVersion") != 1 or actual != expected:
        raise ActivationError(f"backup metadata mismatch for {resource_id}")
    info = payload.lstat()
    kind = metadata.get("kind")
    if kind == "symlink" and stat.S_ISLNK(info.st_mode):
        digest = os.readlink(payload)
    elif kind == "directory" and stat.S_ISDIR(info.st_mode):
        digest = directory_sha256(payload)
    elif kind == "file" and stat.S_ISREG(info.st_mode):
        digest = file_sha256(payload)
    else:
        raise ActivationError(f"backup payload type mismatch for {resource_id}")
    if digest != metadata.get("digest") or info.st_uid != os.getuid():
        raise ActivationError(f"backup payload integrity mismatch for {resource_id}")
    return payload, metadata


def _receipt_for_plan(plan: ActivationPlan, backup_refs: dict[str, str]) -> ActivationReceipt:
    desired_ids = {resource.id for resource in plan.desired_manifest.resources}
    resources = []
    for action in sorted(plan.actions, key=lambda item: item.resource.id):
        if action.resource.id not in desired_ids:
            continue
        skipped = action.decision == ResourceDecision.SKIP
        resources.append(
            ReceiptResource(
                action.resource.id,
                action.resource.target,
                ReceiptResourceState.SKIPPED_CONFLICT if skipped else ReceiptResourceState.DEPLOYED,
                backup_refs.get(action.resource.id, action.backup_ref),
            )
        )
    return ActivationReceipt(
        plan.platform,
        plan.identity,
        str(Path(plan.new_store_path).resolve(strict=True)),
        tuple(resources),
    )


ActivationMilestoneCallback = Callable[[str, ActivationMilestone], None]


def _emit_milestone(
    callback: ActivationMilestoneCallback | None, domain: str, milestone: ActivationMilestone
) -> None:
    if callback is not None:
        callback(domain, milestone)


def activate_platform(
    runner: CommandRunner,
    plan: ActivationPlan,
    *,
    on_milestone: ActivationMilestoneCallback | None = None,
) -> DomainResult:
    desired = plan.desired_manifest
    assert_identity(plan.identity, desired)
    if desired.deployment_domain != plan.platform:
        raise ActivationError("activation plan platform does not match desired manifest")
    profile = Path(plan.profile_path)
    expected_profile = profile_path(plan.identity, plan.platform)
    if profile != expected_profile:
        raise ActivationError(f"unexpected profile path in activation plan: {profile}")
    new_store = Path(plan.new_store_path).resolve(strict=True)
    for resource in desired.resources:
        if not resource.managed:
            continue
        try:
            relative = Path(resource.store_path).resolve(strict=True).relative_to(new_store)
        except (OSError, TypeError, ValueError) as error:
            raise ActivationError(
                f"resource Store path is outside planned bundle: {resource.id}"
            ) from error
        if Path(resource.link_target) != profile / relative:
            raise ActivationError(f"resource link target violates platform contract: {resource.id}")
    results = preflight_platform(
        desired,
        plan.active_manifest,
        other_active_manifests(plan.identity, plan.platform),
        resource_level=True,
    )
    actions = (
        plan.actions
        if plan.actions is not None
        else make_resource_actions(results, desired, plan.old_receipt)
    )
    result_by_id = {result.resource.id: result for result in results}
    if {action.resource.id for action in actions} != set(result_by_id):
        raise ActivationError("activation plan resource set does not match preflight")
    for action in actions:
        current = result_by_id[action.resource.id]
        if action.resource != current.resource:
            raise ActivationError(f"activation action differs from preflight: {action.resource.id}")
        if current.status != action.conflict_status:
            raise ActivationError(f"resource changed after preflight: {action.resource.target}")
        if (
            action.decision == ResourceDecision.OVERWRITE
            and current.status != ConflictStatus.OVERWRITABLE_CONFLICT
        ):
            raise ActivationError(f"overwrite is not allowed for {action.resource.target}")
    plan = ActivationPlan(
        plan.platform,
        plan.identity,
        plan.profile_path,
        plan.new_store_path,
        plan.desired_manifest,
        plan.old_store_path,
        plan.active_manifest,
        tuple(actions),
        plan.old_receipt,
        plan.schema_version,
    )
    created: list[Path] = []
    adopted: dict[Path, int] = {}
    retired: list = []
    restored: list[tuple[ResourceAction, str]] = []
    backup_refs: dict[str, str] = {}
    skipped_tokens = {
        action.resource.id: _target_token(Path(action.resource.target))
        for action in actions
        if action.decision == ResourceDecision.SKIP
    }
    old_store = Path(plan.old_store_path) if plan.old_store_path else None
    new_store = Path(plan.new_store_path)
    new_store_resolved = new_store.resolve(strict=True)
    old_store_resolved = old_store.resolve(strict=True) if old_store else None
    try:
        for action in actions:
            if action.decision == ResourceDecision.OVERWRITE:
                _emit_milestone(on_milestone, plan.platform, ActivationMilestone.BACKUP_OVERWRITES)
                backup_refs[action.resource.id] = _create_backup(plan, action)
        _emit_milestone(on_milestone, plan.platform, ActivationMilestone.SWITCH_PROFILE)
        _set_profile(runner, profile, new_store)
        if profile.resolve(strict=True) not in {new_store_resolved, old_store_resolved} - {None}:
            raise ActivationError("profile resolved to neither the old nor new bundle")
        _emit_milestone(on_milestone, plan.platform, ActivationMilestone.INSTALL_SYMLINKS)
        for action in actions:
            resource = action.resource
            target = Path(resource.target)
            if action.decision == ResourceDecision.OVERWRITE:
                _safe_parent(target, plan.identity)
                target.symlink_to(resource.link_target)
                created.append(target)
            elif action.decision == ResourceDecision.APPLY and action.conflict_status in {
                ConflictStatus.ABSENT,
                ConflictStatus.ADOPTABLE_EMPTY,
            }:
                _safe_parent(target, plan.identity)
                if action.conflict_status == ConflictStatus.ADOPTABLE_EMPTY:
                    adopted[target] = target.stat().st_mode & 0o777
                    target.unlink()
                target.symlink_to(resource.link_target)
                created.append(target)
            elif action.decision == ResourceDecision.RETIRE:
                if target.is_symlink() and os.readlink(target) == resource.link_target:
                    target.unlink()
                    retired.append(resource)
                elif target.exists() or target.is_symlink():
                    raise ActivationError(f"retired target changed after preflight: {target}")
            elif action.decision == ResourceDecision.RESTORE_BACKUP:
                payload, _ = _validated_backup(
                    plan.identity,
                    plan.platform,
                    resource.id,
                    resource.target,
                    action.backup_ref or "",
                )
                if target.is_symlink() and os.readlink(target) == resource.link_target:
                    target.unlink()
                elif target.exists() or target.is_symlink():
                    raise ActivationError(f"retired target is no longer managed: {target}")
                os.replace(payload, target)
                restored.append((action, action.backup_ref or ""))
        _emit_milestone(on_milestone, plan.platform, ActivationMilestone.VERIFY_RESOURCES)
        failures = [
            action.resource.target
            for action in actions
            if action.resource in desired.resources
            and action.decision in {ResourceDecision.APPLY, ResourceDecision.OVERWRITE}
            and not resource_conforms(action.resource)
        ]
        if failures:
            raise ActivationError("post-activation verification failed: " + ", ".join(failures))
        for action in actions:
            if (
                action.decision == ResourceDecision.SKIP
                and _target_token(Path(action.resource.target))
                != skipped_tokens[action.resource.id]
            ):
                raise ActivationError(
                    f"skipped target changed during activation: {action.resource.target}"
                )
        receipt = _receipt_for_plan(plan, backup_refs)
        _emit_milestone(on_milestone, plan.platform, ActivationMilestone.WRITE_RECEIPT)
        write_receipt(receipt)
        skipped = sum(action.decision == ResourceDecision.SKIP for action in actions)
        status = "PARTIAL_UPDATED" if skipped else "UPDATED"
        return DomainResult(
            plan.platform,
            status,
            f"activated {new_store}; {skipped} resource(s) skipped",
        )
    except Exception as original:
        cleanup_errors: list[str] = []
        for target in reversed(created):
            desired_resource = next(r for r in desired.resources if r.target == str(target))
            if target.is_symlink() and os.readlink(target) == desired_resource.link_target:
                target.unlink(missing_ok=True)
            else:
                cleanup_errors.append(f"refused to remove changed target {target}")
        for target, mode in adopted.items():
            if target.exists() or target.is_symlink():
                cleanup_errors.append(f"refused to restore empty file over changed target {target}")
                continue
            try:
                target.touch(mode=mode, exist_ok=False)
                target.chmod(mode)
            except OSError as error:
                cleanup_errors.append(f"could not restore empty file {target}: {error}")
        for action, reference in reversed(restored):
            target = Path(action.resource.target)
            directory = validate_backup_ref(plan.identity, reference)
            payload = directory / "payload"
            if payload.exists() or payload.is_symlink():
                cleanup_errors.append(f"backup payload unexpectedly exists: {payload}")
            elif target.exists() or target.is_symlink():
                os.replace(target, payload)
            else:
                cleanup_errors.append(f"restored target disappeared: {target}")
        if old_store is not None:
            try:
                _set_profile(runner, profile, old_store)
                for resource in retired:
                    target = Path(resource.target)
                    if not target.exists() and not target.is_symlink():
                        _safe_parent(target, plan.identity)
                        target.symlink_to(resource.link_target)
                for action, _ in restored:
                    target = Path(action.resource.target)
                    if not target.exists() and not target.is_symlink():
                        _safe_parent(target, plan.identity)
                        target.symlink_to(action.resource.link_target)
                if plan.active_manifest:
                    failures = [
                        resource.target
                        for resource in plan.active_manifest.resources
                        if resource.managed
                        and (
                            plan.old_receipt is None
                            or any(
                                item.id == resource.id
                                and item.state == ReceiptResourceState.DEPLOYED
                                for item in plan.old_receipt.resources
                            )
                        )
                        and not resource_conforms(resource)
                    ]
                    if failures:
                        raise ActivationError(
                            "old platform verification failed: " + ", ".join(failures)
                        )
            except Exception as error:
                cleanup_errors.append(f"could not restore old profile: {error}")
        for action in actions:
            reference = backup_refs.get(action.resource.id)
            if reference is None:
                continue
            target = Path(action.resource.target)
            directory = validate_backup_ref(plan.identity, reference)
            payload = directory / "payload"
            if target.exists() or target.is_symlink():
                cleanup_errors.append(f"refused to restore backup over changed target {target}")
                continue
            if payload.exists() or payload.is_symlink():
                os.replace(payload, target)
                shutil.rmtree(directory, ignore_errors=True)
            else:
                cleanup_errors.append(f"backup payload is missing: {payload}")
        try:
            if plan.old_receipt is not None:
                write_receipt(plan.old_receipt)
            else:
                receipt_path(plan.identity, plan.platform).unlink(missing_ok=True)
        except Exception as error:
            cleanup_errors.append(f"could not restore old receipt: {error}")
        message = f"{plan.platform} activation failed: {original}"
        if cleanup_errors:
            message += "; " + "; ".join(cleanup_errors)
        if cleanup_errors:
            message += "; RECOVERY_REQUIRED"
        else:
            message += "; ROLLED_BACK"
        raise ActivationError(
            message, next_step=f"Run dot doctor --platform {plan.platform}."
        ) from original


def system_manifest_path(store: Path) -> Path:
    return store / "sw/share/dotfiles/system-manifest.json"


def current_system_store(current_link: Path = Path("/run/current-system")) -> Path:
    try:
        return current_link.resolve(strict=True)
    except OSError as error:
        raise ActivationError(f"cannot resolve current system: {current_link}") from error


@dataclass
class _SshConfigMigration:
    source: Path
    local: Path
    temporary: Path | None = None
    original_local_size: int | None = None

    def commit(self) -> None:
        if self.temporary is not None:
            self.temporary.unlink(missing_ok=True)

    def rollback(self) -> None:
        if self.source.is_symlink():
            self.source.unlink()
        elif self.source.exists():
            raise ActivationError(
                f"refusing to restore SSH config over changed path: {self.source}"
            )
        if self.temporary is None:
            if not self.local.is_file() or self.local.is_symlink():
                raise ActivationError(f"migrated SSH config changed unexpectedly: {self.local}")
            os.replace(self.local, self.source)
            return
        if not self.local.is_file() or self.local.is_symlink():
            raise ActivationError(f"local SSH config changed unexpectedly: {self.local}")
        if self.original_local_size is None:
            raise ActivationError("SSH config migration is missing its original file size")
        with self.local.open("r+b") as stream:
            stream.truncate(self.original_local_size)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(self.temporary, self.source)


def _migrate_ssh_config(
    identity: MachineIdentity, results: list
) -> _SshConfigMigration | None:
    candidates = [
        result
        for result in results
        if result.status == ConflictStatus.MIGRATABLE
        and result.resource.id == "home.ssh.config"
    ]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ActivationError("system manifest contains multiple SSH config migrations")
    source = Path(candidates[0].resource.target)
    local = identity.home / ".ssh/config.local"
    if not local.exists() and not local.is_symlink():
        try:
            os.replace(source, local)
        except OSError as error:
            raise ActivationError(f"could not migrate SSH config: {error}") from error
        return _SshConfigMigration(source, local)

    temporary = source.with_name(f".config.dotfiles-migration-{uuid.uuid4()}")
    try:
        original_size = local.stat().st_size
        os.replace(source, temporary)
    except OSError as error:
        raise ActivationError(f"could not prepare SSH config migration: {error}") from error
    migration = _SshConfigMigration(source, local, temporary, original_size)
    try:
        old_config = temporary.read_bytes()
        with local.open("ab") as stream:
            if original_size:
                with local.open("rb") as existing:
                    existing.seek(-1, os.SEEK_END)
                    if existing.read(1) != b"\n":
                        stream.write(b"\n")
            stream.write(b"\n# Migrated from ~/.ssh/config by dot apply\n")
            stream.write(old_config)
            if old_config and not old_config.endswith(b"\n"):
                stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception as error:
        try:
            migration.rollback()
        except Exception as rollback_error:
            raise ActivationError(
                f"could not migrate SSH config: {error}; recovery failed: {rollback_error}"
            ) from error
        raise ActivationError(f"could not migrate SSH config: {error}") from error
    return migration


def _generation_numbers(output: str) -> set[int]:
    return {
        int(match.group(1))
        for line in output.splitlines()
        if (match := re.match(r"\s*(\d+)\s", line))
    }


def activate_system_store(
    runner: CommandRunner,
    target: Path,
    identity: MachineIdentity,
    *,
    current_link: Path = Path("/run/current-system"),
    profile: Path = Path("/nix/var/nix/profiles/system"),
    on_milestone: ActivationMilestoneCallback | None = None,
) -> DomainResult:
    desired = read_manifest(system_manifest_path(target))
    assert_identity(identity, desired)
    old = current_system_store(current_link) if current_link.exists() else None
    active = (
        read_manifest(system_manifest_path(old))
        if old is not None and system_manifest_path(old).is_file()
        else None
    )
    if active is not None:
        assert_identity(identity, active)
    results = preflight_platform(desired, active)
    migration = _migrate_ssh_config(identity, results)
    if migration is not None:
        _emit_milestone(on_milestone, "system", ActivationMilestone.MIGRATE_SSH)
        try:
            preflight_platform(desired, active)
        except Exception:
            migration.rollback()
            raise
    before = _generation_numbers(
        runner.run(
            ["sudo", "nix-env", "--profile", str(profile), "--list-generations"],
            check=False,
        ).stdout
    )
    generation: int | None = None
    profile_changed = False
    try:
        _emit_milestone(on_milestone, "system", ActivationMilestone.SWITCH_PROFILE)
        runner.run(["sudo", "nix-env", "--profile", str(profile), "--set", str(target)])
        profile_changed = True
        after = _generation_numbers(
            runner.run(
                ["sudo", "nix-env", "--profile", str(profile), "--list-generations"]
            ).stdout
        )
        created = after - before
        if len(created) > 1:
            raise ActivationError(
                f"could not identify the new system generation: {sorted(created)}"
            )
        generation = created.pop() if created else None
        _emit_milestone(on_milestone, "system", ActivationMilestone.RUN_ACTIVATE_SCRIPT)
        runner.run(["sudo", str(target / "activate")])
        _emit_milestone(on_milestone, "system", ActivationMilestone.VERIFY_CURRENT_SYSTEM)
        if current_system_store(current_link) != target.resolve(strict=True):
            raise ActivationError("/run/current-system did not switch to the target closure")
        diagnostics = diagnose_manifest(identity, desired)
        if not diagnostics_healthy(diagnostics):
            raise ActivationError("system doctor found unhealthy resources after activation")
        if migration is not None:
            migration.commit()
        return DomainResult("system", "UPDATED", f"activated {target}")
    except Exception as original:
        recovery_errors: list[str] = []
        if old is not None:
            try:
                runner.run(["sudo", "nix-env", "--profile", str(profile), "--set", str(old)])
                runner.run(["sudo", str(old / "activate")])
                if current_system_store(current_link) != old:
                    raise ActivationError("old closure was not restored")
                if active is not None and not diagnostics_healthy(
                    diagnose_manifest(identity, active)
                ):
                    raise ActivationError("old system doctor found unhealthy resources")
            except Exception as error:
                recovery_errors.append(f"old closure recovery failed: {error}")
        elif profile_changed:
            recovery_errors.append("no previous system closure exists for recovery")
        if generation is not None and old is not None:
            try:
                runner.run(
                    [
                        "sudo",
                        "nix-env",
                        "--profile",
                        str(profile),
                        "--delete-generations",
                        str(generation),
                    ]
                )
            except Exception as error:
                recovery_errors.append(f"failed generation cleanup failed: {error}")
        if migration is not None:
            try:
                migration.rollback()
            except Exception as error:
                recovery_errors.append(f"SSH config migration recovery failed: {error}")
        suffix = (
            "; RECOVERY_REQUIRED: " + "; ".join(recovery_errors)
            if recovery_errors
            else "; ROLLED_BACK"
        )
        raise ActivationError(
            f"system activation failed: {original}{suffix}",
            modified_state=None if recovery_errors else False,
        ) from original


def select_previous_system_generation(
    current: Path,
    *,
    profile_directory: Path = Path("/nix/var/nix/profiles"),
) -> tuple[int, Path]:
    candidates: list[tuple[int, Path]] = []
    pattern = re.compile(r"^system-(\d+)-link$")
    for entry in profile_directory.glob("system-*-link"):
        match = pattern.fullmatch(entry.name)
        if not match:
            continue
        try:
            store = entry.resolve(strict=True)
        except OSError:
            continue
        candidates.append((int(match.group(1)), store))
    current_resolved = current.resolve(strict=True)
    current_generations = [number for number, store in candidates if store == current_resolved]
    if not current_generations:
        raise ActivationError(
            "current /run/current-system is not represented by a system profile generation"
        )
    current_number = max(current_generations)
    previous = [
        item for item in candidates if item[0] < current_number and item[1] != current_resolved
    ]
    if not previous:
        raise ActivationError("no previous system generation with a different Store path exists")
    return max(previous, key=lambda item: item[0])
