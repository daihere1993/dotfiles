from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path, PurePosixPath

from .errors import ValidationError
from .hashing import directory_sha256, file_sha256
from .jsonutil import canonical_json, load_json
from .models import PLATFORMS, ActivationReceipt, MachineIdentity


def platform_state_root(identity: MachineIdentity, platform: str) -> Path:
    return identity.home / ".local/state/dotfiles/platforms" / platform


def receipt_path(identity: MachineIdentity, platform: str) -> Path:
    return platform_state_root(identity, platform) / "activation.json"


def backup_root(identity: MachineIdentity) -> Path:
    return identity.home / ".local/state/dotfiles/backups"


def atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = path.parent.lstat()
    if parent.st_uid != os.getuid() or not stat.S_ISDIR(parent.st_mode):
        raise ValidationError(f"unsafe state directory: {path.parent}")
    os.chmod(path.parent, 0o700)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def validate_backup_ref(identity: MachineIdentity, reference: str) -> Path:
    relative = PurePosixPath(reference)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValidationError(f"invalid backup reference: {reference!r}")
    path = backup_root(identity).joinpath(*relative.parts)
    try:
        path.relative_to(backup_root(identity))
    except ValueError as error:
        raise ValidationError(f"backup reference escapes backup root: {reference!r}") from error
    return path


def validate_receipt(
    receipt: ActivationReceipt,
    identity: MachineIdentity,
    platform: str,
) -> None:
    if receipt.schema_version != 1 or receipt.platform != platform:
        raise ValidationError(f"invalid activation receipt for {platform}")
    if receipt.identity != identity or platform not in PLATFORMS:
        raise ValidationError(f"activation receipt identity mismatch for {platform}")
    if not Path(receipt.bundle_store_path).is_absolute():
        raise ValidationError("activation receipt bundle Store path must be absolute")
    ids: set[str] = set()
    targets: set[str] = set()
    for resource in receipt.resources:
        if resource.id in ids or resource.target in targets:
            raise ValidationError(f"duplicate activation receipt resource: {resource.id}")
        ids.add(resource.id)
        targets.add(resource.target)
        target = Path(resource.target)
        if not target.is_absolute() or ".." in target.parts:
            raise ValidationError(f"invalid receipt target: {target}")
        try:
            target.relative_to(identity.home)
        except ValueError as error:
            raise ValidationError(f"receipt target is outside home: {target}") from error
        if resource.backup_ref is not None:
            validate_backup_ref(identity, resource.backup_ref)


def read_receipt(
    identity: MachineIdentity, platform: str, *, required: bool = False
) -> ActivationReceipt | None:
    path = receipt_path(identity, platform)
    if not path.exists() and not path.is_symlink():
        if required:
            raise ValidationError(f"activation receipt does not exist: {path}")
        return None
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValidationError(f"activation receipt must be a regular file: {path}")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValidationError(f"unsafe activation receipt permissions: {path}")
    try:
        receipt = ActivationReceipt.from_dict(load_json(path))
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ValidationError(f"invalid activation receipt at {path}: {error}") from error
    validate_receipt(receipt, identity, platform)
    return receipt


def write_receipt(receipt: ActivationReceipt) -> None:
    validate_receipt(receipt, receipt.identity, receipt.platform)
    atomic_write(
        receipt_path(receipt.identity, receipt.platform),
        canonical_json(receipt.to_dict()),
    )


def backup_is_valid(
    identity: MachineIdentity,
    platform: str,
    resource_id: str,
    target: str,
    reference: str,
) -> bool:
    try:
        directory = validate_backup_ref(identity, reference)
        metadata_path = directory / "metadata.json"
        payload = directory / "payload"
        if metadata_path.is_symlink() or not metadata_path.is_file():
            return False
        metadata = load_json(metadata_path)
        if (
            metadata.get("schemaVersion") != 1
            or metadata.get("platform") != platform
            or metadata.get("username") != identity.username
            or metadata.get("homeDirectory") != identity.home_directory
            or metadata.get("resourceId") != resource_id
            or metadata.get("target") != target
            or (not payload.exists() and not payload.is_symlink())
        ):
            return False
        info = payload.lstat()
        kind = metadata.get("kind")
        if kind == "symlink" and stat.S_ISLNK(info.st_mode):
            digest = os.readlink(payload)
        elif kind == "directory" and stat.S_ISDIR(info.st_mode):
            digest = directory_sha256(payload)
        elif kind == "file" and stat.S_ISREG(info.st_mode):
            digest = file_sha256(payload)
        else:
            return False
        return info.st_uid == os.getuid() and digest == metadata.get("digest")
    except (OSError, TypeError, ValueError, ValidationError):
        return False
