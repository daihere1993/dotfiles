from __future__ import annotations

from pathlib import Path

from .errors import ValidationError
from .jsonutil import canonical_json, load_json
from .models import DOMAINS, DeploymentManifest, MachineIdentity


def validate_manifest(manifest: DeploymentManifest) -> None:
    if manifest.schema_version != 1:
        raise ValidationError(f"unsupported manifest schema: {manifest.schema_version}")
    if manifest.deployment_domain not in DOMAINS:
        raise ValidationError(f"invalid deployment domain: {manifest.deployment_domain}")
    home = manifest.identity.home
    resource_ids: set[str] = set()
    targets: set[str] = set()
    for resource in manifest.resources:
        if resource.id in resource_ids:
            raise ValidationError(f"duplicate resource id: {resource.id}")
        resource_ids.add(resource.id)
        target = Path(resource.target)
        if not target.is_absolute() or ".." in target.parts:
            raise ValidationError(f"resource target must be absolute: {resource.target}")
        try:
            target.relative_to(home)
        except ValueError as error:
            raise ValidationError(
                f"resource target is outside machine home: {resource.target}"
            ) from error
        if resource.target in targets:
            raise ValidationError(f"duplicate resource target: {resource.target}")
        targets.add(resource.target)
        if not resource.id or not resource.owner:
            raise ValidationError("resource id and owner must be non-empty")
        if resource.managed and not resource.sources:
            raise ValidationError(f"managed resource must declare canonical sources: {resource.id}")
        if resource.kind == "local-prerequisite":
            if resource.managed:
                raise ValidationError(f"local prerequisite must set managed=false: {resource.id}")
        elif not resource.link_target or not resource.store_path:
            raise ValidationError(f"managed link is missing linkTarget/storePath: {resource.id}")
        if resource.kind == "file-link" and not resource.sha256:
            raise ValidationError(f"file link is missing sha256: {resource.id}")
        if resource.kind == "directory-link" and not resource.directory_sha256:
            raise ValidationError(f"directory link is missing directorySha256: {resource.id}")
    skill_ids: set[str] = set()
    for skill in manifest.skills:
        if skill.target_id in skill_ids:
            raise ValidationError(f"duplicate target skill id: {skill.target_id}")
        skill_ids.add(skill.target_id)
        if skill.source_kind == "external" and (not skill.source_id or not skill.nar_hash):
            raise ValidationError(f"external skill lacks lock identity: {skill.canonical_id}")


def assert_identity(expected: MachineIdentity, manifest: DeploymentManifest) -> None:
    if expected != manifest.identity:
        raise ValidationError(
            f"manifest identity mismatch for {manifest.deployment_domain}",
            next_step="Use a generation built for the current machine identity.",
        )


def dump_manifest(manifest: DeploymentManifest, path: Path) -> None:
    validate_manifest(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(manifest.to_dict()))


def read_manifest(path: Path) -> DeploymentManifest:
    try:
        manifest = DeploymentManifest.from_dict(load_json(path))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValidationError(f"invalid manifest at {path}: {error}") from error
    validate_manifest(manifest)
    return manifest
