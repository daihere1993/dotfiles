from __future__ import annotations

import os
import stat
from pathlib import Path

from .hashing import directory_sha256, file_sha256
from .models import (
    ConflictResult,
    ConflictStatus,
    DeploymentManifest,
    MachineIdentity,
    Resource,
)
from .state import backup_root


def is_overwritable_skill(
    resource: Resource, identity: MachineIdentity, platform: str, skills_root: Path
) -> bool:
    target = Path(resource.target)
    expected_prefix = f"ai-agent.{platform}.skill."
    if (
        resource.kind != "directory-link"
        or not resource.id.startswith(expected_prefix)
        or target.parent != skills_root
    ):
        return False
    try:
        root_info = skills_root.lstat()
        info = target.lstat()
    except OSError:
        return False
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or root_info.st_uid != os.getuid()
        or info.st_uid != os.getuid()
        or os.path.ismount(target)
    ):
        return False
    allowed = stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
    if not allowed:
        return False
    existing = backup_root(identity)
    while not existing.exists():
        existing = existing.parent
    try:
        return target.parent.stat().st_dev == existing.stat().st_dev
    except OSError:
        return False


def is_migratable_ssh_config(resource: Resource, identity: MachineIdentity) -> bool:
    target = Path(resource.target)
    local = target.with_name("config.local")
    if (
        resource.id != "home.ssh.config"
        or resource.kind != "file-link"
        or target != identity.home / ".ssh/config"
    ):
        return False
    try:
        parent_info = target.parent.lstat()
        target_info = target.lstat()
    except OSError:
        return False
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or stat.S_ISLNK(parent_info.st_mode)
        or parent_info.st_uid != os.getuid()
        or not stat.S_ISREG(target_info.st_mode)
        or stat.S_ISLNK(target_info.st_mode)
        or target_info.st_uid != os.getuid()
        or target_info.st_mode & 0o022 != 0
    ):
        return False
    if not local.exists() and not local.is_symlink():
        return True
    try:
        local_info = local.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(local_info.st_mode)
        and not stat.S_ISLNK(local_info.st_mode)
        and local_info.st_uid == os.getuid()
        and local_info.st_mode & 0o022 == 0
    )


def _is_adoptable_empty_file(resource: Resource) -> bool:
    if resource.kind != "file-link":
        return False
    target = Path(resource.target)
    try:
        details = target.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(details.st_mode)
        and not target.is_symlink()
        and details.st_size == 0
        and details.st_uid == os.getuid()
        and details.st_mode & 0o022 == 0
    )


def resource_conforms(resource: Resource) -> bool:
    target = Path(resource.target)
    if resource.kind == "local-prerequisite":
        return target.is_file() and not target.is_symlink()
    if not target.is_symlink():
        return False
    try:
        if (
            resource.owner != "home-manager"
            and os.readlink(target) != resource.link_target
        ):
            return False
        resolved = target.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    expected_store = Path(resource.store_path)
    try:
        expected_store = expected_store.resolve(strict=True)
    except OSError:
        return False
    if resolved != expected_store:
        return False
    try:
        if resource.kind == "file-link":
            return resolved.is_file() and file_sha256(resolved) == resource.sha256
        if resource.kind == "directory-link":
            return resolved.is_dir() and directory_sha256(resolved) == resource.directory_sha256
    except (OSError, ValueError):
        return False
    return False


def classify_resource(
    desired: Resource | None,
    active: Resource | None,
) -> ConflictResult:
    resource = desired or active
    assert resource is not None
    target = Path(resource.target)
    exists = target.exists() or target.is_symlink()
    if desired is not None and not exists:
        return ConflictResult(ConflictStatus.ABSENT, desired, "desired target is absent")
    if desired is not None and active is None and _is_adoptable_empty_file(desired):
        return ConflictResult(
            ConflictStatus.ADOPTABLE_EMPTY,
            desired,
            "empty user-owned rules file can be safely adopted",
        )
    if desired is not None and resource_conforms(desired):
        return ConflictResult(
            ConflictStatus.CURRENTLY_MANAGED, desired, "target matches desired manifest"
        )
    if (
        desired is not None
        and active is not None
        and desired.id == active.id
        and desired.target == active.target
        and resource_conforms(active)
    ):
        return ConflictResult(
            ConflictStatus.REPLACEABLE_MANAGED, desired, "target matches the active generation"
        )
    if desired is None and not exists:
        return ConflictResult(
            ConflictStatus.RETIRED_ABSENT, active, "retired target is already absent"
        )
    if desired is None and active is not None and resource_conforms(active):
        return ConflictResult(
            ConflictStatus.RETIRABLE_MANAGED, active, "retired target matches the active generation"
        )
    return ConflictResult(
        ConflictStatus.CONFLICT,
        resource,
        "existing target cannot be proven to belong to the active or desired generation",
    )


def classify_manifests(
    desired: DeploymentManifest,
    active: DeploymentManifest | None,
    *,
    overwritable_skills_root: Path | None = None,
) -> list[ConflictResult]:
    desired_by_id = {resource.id: resource for resource in desired.resources if resource.managed}
    active_by_id = (
        {resource.id: resource for resource in active.resources if resource.managed}
        if active
        else {}
    )
    results: list[ConflictResult] = []
    for resource_id in sorted(set(desired_by_id) | set(active_by_id)):
        result = classify_resource(desired_by_id.get(resource_id), active_by_id.get(resource_id))
        if (
            result.status == ConflictStatus.CONFLICT
            and desired_by_id.get(resource_id) is not None
            and active_by_id.get(resource_id) is None
            and overwritable_skills_root is not None
            and is_overwritable_skill(
                result.resource,
                desired.identity,
                desired.deployment_domain,
                overwritable_skills_root,
            )
        ):
            result = ConflictResult(
                ConflictStatus.OVERWRITABLE_CONFLICT,
                result.resource,
                "existing user-owned skill can be backed up and overwritten",
            )
        elif (
            result.status == ConflictStatus.CONFLICT
            and desired_by_id.get(resource_id) is not None
            and is_migratable_ssh_config(result.resource, desired.identity)
        ):
            result = ConflictResult(
                ConflictStatus.MIGRATABLE,
                result.resource,
                "existing SSH config will migrate to config.local",
            )
        results.append(result)
    return results


def ownership_overlaps(manifests: list[DeploymentManifest]) -> list[str]:
    resources = [
        (manifest.deployment_domain, resource)
        for manifest in manifests
        for resource in manifest.resources
        if resource.managed
    ]
    problems: list[str] = []
    for index, (domain, resource) in enumerate(resources):
        path = Path(resource.target)
        for other_domain, other in resources[index + 1 :]:
            if domain == other_domain:
                continue
            other_path = Path(other.target)
            overlap = path == other_path
            if resource.kind == "directory-link":
                overlap = overlap or path in other_path.parents
            if other.kind == "directory-link":
                overlap = overlap or other_path in path.parents
            if overlap:
                problems.append(f"{domain}:{path} overlaps {other_domain}:{other_path}")
    return problems
