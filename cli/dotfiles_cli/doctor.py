from __future__ import annotations

import os
import stat
from pathlib import Path

from .conflict import resource_conforms
from .manifest import assert_identity
from .models import (
    ActivationReceipt,
    DeploymentManifest,
    Diagnostic,
    DiagnosticStatus,
    MachineIdentity,
    ReceiptResourceState,
)
from .state import backup_is_valid


def _local_status(path: Path) -> tuple[DiagnosticStatus, str]:
    if not path.exists() and not path.is_symlink():
        return DiagnosticStatus.LOCAL_ABSENT_OPTIONAL, "optional local file is absent"
    try:
        info = path.lstat()
    except OSError as error:
        return DiagnosticStatus.LOCAL_UNSAFE_PERMISSIONS, f"cannot inspect local file: {error}"
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.getuid()
        or bool(info.st_mode & 0o022)
    ):
        return (
            DiagnosticStatus.LOCAL_UNSAFE_PERMISSIONS,
            "local file must be a user-owned regular file and not group/other writable",
        )
    return DiagnosticStatus.LOCAL_PRESENT, "optional local file is present and safe"


def diagnose_manifest(
    identity: MachineIdentity,
    manifest: DeploymentManifest,
    receipt: ActivationReceipt | None = None,
) -> list[Diagnostic]:
    assert_identity(identity, manifest)
    diagnostics: list[Diagnostic] = []
    receipt_by_id = {item.id: item for item in receipt.resources} if receipt else {}
    for resource in manifest.resources:
        path = Path(resource.target)
        receipt_resource = receipt_by_id.get(resource.id)
        if (
            receipt_resource is not None
            and receipt_resource.state == ReceiptResourceState.SKIPPED_CONFLICT
        ):
            status, reason = (
                DiagnosticStatus.SKIPPED_CONFLICT,
                "resource was skipped because a user-owned target conflicts",
            )
        elif resource.kind == "local-prerequisite":
            status, reason = _local_status(path)
        elif not path.exists() and not path.is_symlink():
            status, reason = DiagnosticStatus.MISSING, "managed target is missing"
        elif resource_conforms(resource):
            status, reason = DiagnosticStatus.HEALTHY, "managed target matches the active manifest"
        else:
            status, reason = (
                DiagnosticStatus.DRIFTED,
                "managed target differs from the active manifest",
            )
        diagnostics.append(
            Diagnostic(
                domain=manifest.deployment_domain,
                status=status,
                reason=reason,
                resource_id=resource.id,
                target=resource.target,
            )
        )
        if (
            receipt_resource is not None
            and receipt_resource.backup_ref is not None
            and not backup_is_valid(
                identity,
                manifest.deployment_domain,
                resource.id,
                resource.target,
                receipt_resource.backup_ref,
            )
        ):
            diagnostics.append(
                Diagnostic(
                    domain=manifest.deployment_domain,
                    status=DiagnosticStatus.BACKUP_MISSING,
                    reason="managed resource backup is missing or incomplete",
                    resource_id=resource.id,
                    target=resource.target,
                )
            )
    if manifest.deployment_domain == "cursor":
        diagnostics.append(
            Diagnostic(
                domain="cursor",
                status=DiagnosticStatus.UNSUPPORTED_OPTIONAL,
                reason="Cursor global rules have no supported filesystem interface",
            )
        )
    return diagnostics


def diagnostics_healthy(diagnostics: list[Diagnostic]) -> bool:
    unhealthy = {
        DiagnosticStatus.MISSING,
        DiagnosticStatus.DRIFTED,
        DiagnosticStatus.LOCAL_UNSAFE_PERMISSIONS,
        DiagnosticStatus.SKIPPED_CONFLICT,
        DiagnosticStatus.BACKUP_MISSING,
    }
    return not any(item.status in unhealthy for item in diagnostics)
